import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import 'api.dart';
import 'local.dart';

enum Stage { loading, link, cashier, openShift, sell }

/// Una línea del ticket que se está armando. product_id null = monto libre.
/// [modifiers]: opciones del menú elegidas ({id, name, price}); el precio final lo vuelve a calcular el servidor.
/// [note]: aclaración para la cocina ("sin cebolla").
class Line {
  Line({this.productId, required this.name, required this.unitPrice, this.quantity = 1, List<Map<String, dynamic>>? modifiers, this.note = ''})
      : modifiers = modifiers ?? [];
  final int? productId;
  final String name;
  final double unitPrice; // precio del producto, sin las opciones
  final List<Map<String, dynamic>> modifiers;
  String note;
  int quantity;
  double get extras => modifiers.fold(0.0, (a, m) => a + ((m['price'] as num?) ?? 0).toDouble());
  double get unit => unitPrice + extras;
  double get total => unit * quantity;
  String get modifiersText => modifiers.map((m) => m['name']).join(', ');

  /// Mismo producto, mismas opciones y misma aclaración: se suma a la línea en vez de agregar otra.
  bool sameAs(int? id, List<Map<String, dynamic>> mods, String n) =>
      productId == id && n == note && ({for (final m in modifiers) m['id']}.containsAll({for (final m in mods) m['id']})) && modifiers.length == mods.length;

  Map<String, dynamic> toJson() => {
        if (productId != null) 'product_id': productId,
        if (productId == null) 'name': name,
        if (productId == null) 'unit_price': unitPrice,
        'quantity': quantity,
        if (modifiers.isNotEmpty) 'modifiers': [for (final m in modifiers) m['id']],
        if (note.isNotEmpty) 'note': note,
      };

  /// Para guardar el ticket en espera en la compu y volver a armarlo.
  Map<String, dynamic> toLocal() => {'product_id': productId, 'name': name, 'unit_price': unitPrice, 'quantity': quantity, 'modifiers': modifiers, 'note': note};
  static Line fromLocal(Map m) => Line(
        productId: m['product_id'] as int?,
        name: m['name'].toString(),
        unitPrice: (m['unit_price'] as num).toDouble(),
        quantity: (m['quantity'] as num).toInt(),
        modifiers: ((m['modifiers'] as List?) ?? []).cast<Map>().map((x) => x.cast<String, dynamic>()).toList(),
        note: (m['note'] ?? '').toString(),
      );

  /// Como sale en el ticket y en la comanda.
  Map<String, dynamic> preview() => {
        'name': name,
        'quantity': quantity,
        'unit_price': unit,
        'total': total,
        if (modifiers.isNotEmpty) 'modifiers_text': modifiersText,
        if (note.isNotEmpty) 'note': note,
      };
}

String money(num v) {
  final neg = v < 0;
  final cents = (v.abs() * 100).round();
  final whole = (cents ~/ 100).toString().replaceAllMapped(RegExp(r'\B(?=(\d{3})+(?!\d))'), (_) => '.');
  final dec = cents % 100;
  return '${neg ? '-' : ''}\$ $whole${dec == 0 ? '' : ',${dec.toString().padLeft(2, '0')}'}';
}

double? parseMoney(String s) {
  final t = s.trim().replaceAll('\$', '').replaceAll(' ', '').replaceAll('.', '').replaceAll(',', '.');
  if (t.isEmpty) return null;
  return double.tryParse(t);
}

/// Todo el estado de la caja: comercio vinculado, cajero, caja abierta, ticket actual y ventas por subir.
class Caja extends ChangeNotifier {
  Caja(this.local) : api = Api(deviceToken: local.config['token'] as String?);
  final Local local;
  final Api api;

  Stage stage = Stage.loading;
  bool online = true;
  String? notice; // aviso arriba (sin internet, ventas rechazadas, etc.)
  Map<String, dynamic>? cashier;
  Map<String, dynamic>? shift;
  final List<Line> cart = [];
  int selected = -1;
  double discount = 0;
  Map<String, dynamic>? lastSale; // la última venta (para mostrar el QR y reimprimir)
  Timer? _timer;
  bool _syncing = false;

  Map<String, dynamic> get me => (local.config['me'] as Map?)?.cast<String, dynamic>() ?? {};
  Map<String, dynamic> get store => (me['store'] as Map?)?.cast<String, dynamic>() ?? {};
  List<Map<String, dynamic>> get cashiers => ((me['cashiers'] as List?) ?? []).cast<Map>().map((m) => m.cast<String, dynamic>()).toList();
  List<Map<String, dynamic>> get products =>
      ((local.catalog['products'] as List?) ?? []).cast<Map>().map((m) => m.cast<String, dynamic>()).toList();
  List<Map<String, dynamic>> get sections =>
      ((local.catalog['sections'] as List?) ?? []).cast<Map>().map((m) => m.cast<String, dynamic>()).toList();
  List<Map<String, dynamic>> get methods {
    final m = ((me['methods'] as List?) ?? []).cast<Map>().map((m) => m.cast<String, dynamic>()).toList();
    return m.isNotEmpty
        ? m
        : [
            {'id': 'efectivo', 'label': 'Efectivo'},
            {'id': 'mercadopago', 'label': 'Mercado Pago'},
            {'id': 'transferencia', 'label': 'Transferencia'},
          ];
  }

  bool get isOwner => cashier?['is_owner'] == true;
  int get pendingCount => local.pending.length;
  List<Map<String, dynamic>> get rejected =>
      ((local.config['rejected'] as List?) ?? []).cast<Map>().map((m) => m.cast<String, dynamic>()).toList();
  double get subtotal => cart.fold(0.0, (a, l) => a + l.total);
  /// Total del ticket antes de los Puntos Trappi (con el descuento manual).
  double get ticketTotal => (subtotal - discount).clamp(0, double.infinity).toDouble();
  double get pointsDiscount => pointsPayment == null ? 0 : ((pointsPayment!['discount'] as num?) ?? 0).toDouble();
  /// Lo que paga el cliente.
  double get total => (ticketTotal - pointsDiscount).clamp(0, double.infinity).toDouble();

  /// Pago con Puntos Trappi confirmado por el cliente para el ticket actual. Mientras exista, el ticket no se puede cambiar.
  Map<String, dynamic>? pointsPayment;
  bool get locked => pointsPayment != null;
  bool get pointsPayEnabled => (me['points_pay'] as Map?)?['enabled'] == true;
  String? get counterUrl => (me['points_pay'] as Map?)?['counter_url'] as String?;

  /// Los más vendidos (los calcula el servidor con las ventas del último mes).
  List<Map<String, dynamic>> get favorites {
    final ids = ((local.catalog['favorites'] as List?) ?? []).cast<int>();
    final byId = {for (final p in products) p['id']: p};
    return [for (final id in ids) if (byId[id] != null) byId[id]!];
  }

  /// Teclas 1 a 9: los más vendidos (o los primeros del menú si todavía no hay ventas).
  List<Map<String, dynamic>> get quick => (favorites.isNotEmpty ? favorites : products).take(9).toList();

  List<Map<String, dynamic>> groupsOf(Map<String, dynamic> p) => ((p['groups'] as List?) ?? []).cast<Map>().map((g) => g.cast<String, dynamic>()).toList();

  // ---------- gastronomía ----------

  /// Nombre para llamarlo al mostrador y si es para comer acá o para llevar (del ticket que se está armando).
  String customerName = '';
  String service = '';
  /// Autorización del dueño para el descuento del ticket actual (si lo pide un cajero y es más del 10 %).
  String? discountApproval;
  double get freeDiscountPct => ((me['free_discount_pct'] as num?) ?? 10).toDouble();
  bool get discountNeedsOwner => !isOwner && discount > 0 && discount > subtotal * freeDiscountPct / 100 + 0.009;

  /// Comanda para la cocina: off | print (se imprime) | board (tablero de Comandas) | both.
  String get kitchenMode => (local.config['kitchen'] as String?) ?? 'print';
  String get defaultService => (local.config['service'] as String?) ?? '';
  Map<String, dynamic> get delivery => (me['delivery'] as Map?)?.cast<String, dynamic>() ?? {'enabled': false, 'zones': []};
  List<int> get bills => ((me['bills'] as List?) ?? [20000, 10000, 2000, 1000, 500, 200, 100, 50, 20, 10]).cast<num>().map((b) => b.toInt()).toList();

  /// Número para llamar: arranca en 1 cada día.
  int get nextCallNumber {
    final c = (local.config['call'] as Map?) ?? {};
    return c['day'] == _today ? ((c['n'] as num?) ?? 0).toInt() + 1 : 1;
  }

  String get _today {
    final d = DateTime.now();
    return '${d.year}-${d.month}-${d.day}';
  }

  Future<int> _takeCallNumber() async {
    final n = nextCallNumber;
    local.config['call'] = {'day': _today, 'n': n};
    await local.saveConfig();
    return n;
  }

  void setCustomer(String name) {
    customerName = name.trim();
    notifyListeners();
  }

  void setService(String v) {
    service = v;
    notifyListeners();
  }

  /// Tickets en espera (el cliente está eligiendo el postre): se guardan en la compu.
  List<Map<String, dynamic>> get held => ((local.config['held'] as List?) ?? []).cast<Map>().map((m) => m.cast<String, dynamic>()).toList();

  Future<void> hold() async {
    if (cart.isEmpty || locked) return;
    final list = held
      ..add({
        'lines': [for (final l in cart) l.toLocal()],
        'discount': discount,
        'approval': discountApproval,
        'name': customerName,
        'service': service,
        'total': total,
        'at': DateTime.now().toIso8601String(),
      });
    local.config['held'] = list.take(20).toList();
    await local.saveConfig();
    clearCart();
  }

  /// Retoma un ticket en espera. Si había otro a medio cargar, ese pasa a espera.
  Future<void> resume(int i) async {
    final list = held;
    if (i < 0 || i >= list.length || locked) return;
    final t = list.removeAt(i);
    local.config['held'] = list;
    if (cart.isNotEmpty) await hold();
    cart
      ..clear()
      ..addAll([for (final l in (t['lines'] as List).cast<Map>()) Line.fromLocal(l)]);
    selected = cart.isEmpty ? -1 : cart.length - 1;
    discount = ((t['discount'] as num?) ?? 0).toDouble().clamp(0, subtotal).toDouble();
    discountApproval = t['approval'] as String?;
    customerName = (t['name'] ?? '').toString();
    service = (t['service'] ?? defaultService).toString();
    await local.saveConfig();
    notifyListeners();
  }

  Future<void> dropHeld(int i) async {
    final list = held;
    if (i < 0 || i >= list.length) return;
    list.removeAt(i);
    local.config['held'] = list;
    await local.saveConfig();
    notifyListeners();
  }

  /// Aprobación del dueño para un descuento grande (con su token, de [askOwner]).
  Future<String> approveDiscount(String ownerToken, double amount) async {
    final r = await api.approval('discount', double.parse(amount.toStringAsFixed(2)), ownerToken);
    return r['approval'] as String;
  }

  /// Retiro (autorizado por el dueño: [asToken]) o ingreso de efectivo.
  Future<void> addMovement(String kind, double amount, String reason, {String? asToken}) async {
    final r = await api.cashMovement({'client_uuid': const Uuid().v4(), 'kind': kind, 'amount': amount, 'reason': reason}, asToken: asToken);
    shift = (r['shift'] as Map?)?.cast<String, dynamic>() ?? shift;
    notifyListeners();
  }

  /// Pedido por teléfono con lo que está cargado en el ticket. Si sale bien, el ticket se vacía.
  Future<Map<String, dynamic>> phoneOrder(Map<String, dynamic> data) async {
    final r = await api.phoneOrder({
      'client_uuid': (data.remove('client_uuid') ?? const Uuid().v4()),
      'items': cart.map((l) => l.toJson()).toList(),
      ...data,
    });
    final lines = cart.map((l) => l.preview()).toList();
    clearCart();
    return {...r, 'lines': lines};
  }

  Future<void> start() async {
    service = defaultService;
    if (api.deviceToken == null) {
      stage = Stage.link;
      notifyListeners();
      return;
    }
    await refresh();
    stage = Stage.cashier;
    notifyListeners();
    _timer ??= Timer.periodic(const Duration(seconds: 20), (_) => sync());
  }

  /// Trae comercio, cajeros y menú. Sin internet se sigue con lo guardado.
  Future<void> refresh() async {
    try {
      final m = await api.me();
      local.config['me'] = m;
      await local.saveConfig();
      shift = (m['shift'] as Map?)?.cast<String, dynamic>();
      local.catalog = await api.catalog();
      await local.saveCatalog();
      _setOnline(true);
    } on ApiError catch (e) {
      if (e.status == 401) {
        await unlink();
        return;
      }
      if (e.offline) {
        _setOnline(false);
      } else {
        notice = e.message;
      }
    }
    notifyListeners();
  }

  void _setOnline(bool v) {
    online = v;
    if (v && notice == 'Sin internet: las ventas se guardan y se suben solas cuando vuelva.') notice = null;
    if (!v) notice = 'Sin internet: las ventas se guardan y se suben solas cuando vuelva.';
  }

  Future<void> link(String email, String password) async {
    final r = await api.link(email, password);
    api.deviceToken = r['token'] as String;
    local.config = {'token': r['token'], 'me': r..remove('token')..remove('ok')};
    await local.saveConfig();
    await start();
  }

  Future<void> unlink() async {
    api.deviceToken = null;
    api.cashierToken = null;
    cashier = null;
    // lo de esta compu (impresoras, papel, comanda) queda aunque se desvincule
    final keep = {for (final k in ['printer', 'paper', 'margin_extra', 'kitchen', 'kitchen_printer', 'service']) k: local.config[k]};
    await local.unlink();
    keep.forEach((k, v) {
      if (v != null) local.config[k] = v;
    });
    await local.saveConfig();
    stage = Stage.link;
    notifyListeners();
  }

  Future<void> login(int cashierId, String pin) async {
    final r = await api.cashierLogin(cashierId, pin);
    api.cashierToken = r['token'] as String;
    cashier = (r['cashier'] as Map).cast<String, dynamic>();
    await refresh();
    stage = shift == null ? Stage.openShift : Stage.sell;
    notifyListeners();
  }

  /// Token de un dueño para autorizar algo (cerrar caja, anular, salir). Si el cajero actual es dueño, el suyo.
  Future<String> ownerToken(int cashierId, String pin) async {
    final r = await api.cashierLogin(cashierId, pin);
    if ((r['cashier'] as Map)['is_owner'] != true) throw ApiError('Ese cajero no es dueño.', 403);
    return r['token'] as String;
  }

  void logout() {
    api.cashierToken = null;
    cashier = null;
    clearCart();
    stage = Stage.cashier;
    notifyListeners();
  }

  Future<void> openShift(double amount) async {
    shift = await api.openShift(amount);
    stage = Stage.sell;
    notifyListeners();
  }

  Future<Map<String, dynamic>> closeShift(double counted, {String? asToken, Map<String, dynamic>? bills}) async {
    await sync(); // primero se suben las ventas pendientes, así el cierre las cuenta
    if (local.pending.isNotEmpty) throw ApiError('Quedan ventas sin subir. Conectate a internet antes de cerrar la caja.', 409);
    final summary = await api.closeShift(counted, asToken: asToken, bills: bills);
    shift = null;
    return summary;
  }

  void afterClose() {
    lastSale = null; // el próximo turno no ve el QR de la última venta
    logout();
  }

  Future<void> reloadShift() async {
    try {
      final r = await api.currentShift();
      shift = (r['shift'] as Map?)?.cast<String, dynamic>();
      _setOnline(true);
    } on ApiError catch (e) {
      if (e.offline) _setOnline(false);
    }
    notifyListeners();
  }

  // ---------- ticket ----------

  void addProduct(Map<String, dynamic> p, {List<Map<String, dynamic>> modifiers = const [], String note = '', int quantity = 1}) {
    if (locked) return;
    final id = p['id'] as int;
    final n = note.trim();
    final i = cart.indexWhere((l) => l.sameAs(id, modifiers, n));
    if (i >= 0) {
      cart[i].quantity = (cart[i].quantity + quantity).clamp(1, 999);
      selected = i;
    } else {
      cart.add(Line(productId: id, name: p['name'] as String, unitPrice: (p['price'] as num).toDouble(), quantity: quantity.clamp(1, 999),
          modifiers: [...modifiers], note: n));
      selected = cart.length - 1;
    }
    notifyListeners();
  }

  /// Aclaración de la línea elegida ("sin cebolla"). Si esa misma línea está dos veces, quedan separadas.
  void setNote(int i, String note) {
    if (locked || i < 0 || i >= cart.length) return;
    cart[i].note = note.trim().length > 120 ? note.trim().substring(0, 120) : note.trim();
    notifyListeners();
  }

  void addFree(String name, double amount) {
    if (locked) return;
    cart.add(Line(name: name.trim().isEmpty ? 'Monto libre' : name.trim(), unitPrice: amount));
    selected = cart.length - 1;
    notifyListeners();
  }

  /// Busca por código de barras exacto. Devuelve si lo encontró.
  Map<String, dynamic>? byBarcode(String code) {
    final c = code.trim();
    if (c.isEmpty) return null;
    for (final p in products) {
      if ((p['barcode'] ?? '').toString().trim() == c) return p;
    }
    return null;
  }

  bool addBarcode(String code) {
    final p = byBarcode(code);
    if (p == null) return false;
    addProduct(p);
    return true;
  }

  void changeQty(int delta) {
    if (locked) return;
    if (selected < 0 || selected >= cart.length) return;
    final l = cart[selected];
    l.quantity += delta;
    if (l.quantity < 1) {
      removeSelected();
      return;
    }
    if (l.quantity > 999) l.quantity = 999;
    notifyListeners();
  }

  void removeSelected() {
    if (locked) return;
    if (selected < 0 || selected >= cart.length) return;
    cart.removeAt(selected);
    selected = cart.isEmpty ? -1 : selected.clamp(0, cart.length - 1);
    if (discount > subtotal) discount = subtotal;
    notifyListeners();
  }

  void select(int i) {
    selected = i;
    notifyListeners();
  }

  void setDiscount(double v, {String? approval}) {
    if (locked) return;
    discount = v.clamp(0, subtotal).toDouble();
    discountApproval = approval;
    notifyListeners();
  }

  void clearCart() {
    pointsPayment = null;
    cart.clear();
    selected = -1;
    discount = 0;
    discountApproval = null;
    customerName = '';
    service = defaultService;
    notifyListeners();
  }

  /// Cobra el ticket actual. Se guarda primero en la compu y después se intenta subir:
  /// si no hay internet, la venta queda pendiente (sin QR de puntos hasta que se suba).
  /// [payments]: pago mixto ([{method, amount}], dos o tres medios).
  Future<Map<String, dynamic>> charge(String method, double? paidWith, {List<Map<String, dynamic>>? payments}) async {
    final call = await _takeCallNumber();
    final cashPart = method == 'efectivo' ? total : payments?.firstWhere((p) => p['method'] == 'efectivo', orElse: () => {})['amount'] as num?;
    final sale = <String, dynamic>{
      'client_uuid': const Uuid().v4(),
      'cashier_id': cashier!['id'],
      'items': cart.map((l) => l.toJson()).toList(),
      'discount': double.parse(discount.toStringAsFixed(2)),
      if (pointsPayment != null) 'points_payment_id': pointsPayment!['id'],
      'payment_method': method,
      'payments': ?payments,
      if (cashPart != null && paidWith != null) 'paid_with': paidWith,
      'sold_at': DateTime.now().toUtc().toIso8601String(),
      'call_number': call,
      if (customerName.isNotEmpty) 'customer_name': customerName,
      if (service.isNotEmpty) 'service': service,
      if (kitchenMode == 'board' || kitchenMode == 'both') 'kitchen': true,
      if (discountApproval != null) 'approval': discountApproval,
    };
    final preview = <String, dynamic>{
      ...sale,
      'number': null,
      'pending': true,
      'subtotal': subtotal,
      'total': total,
      'points_discount': pointsDiscount,
      'cashier_name': cashier!['name'],
      'lines': cart.map((l) => l.preview()).toList(),
      if (cashPart != null && paidWith != null) 'cash_part': cashPart,
    };
    local.pending.add(sale);
    await local.savePending();
    clearCart();
    lastSale = preview;
    notifyListeners();
    await sync();
    return lastSale!;
  }

  // ---------- pagar con Puntos Trappi (el cliente escanea el QR del mostrador) ----------

  Future<Map<String, dynamic>> startPointsPay() async {
    final r = await api.createPointsPay(double.parse(ticketTotal.toStringAsFixed(2)));
    return r;
  }

  Future<Map<String, dynamic>> pointsPayStatus(int id) => api.pointsPayStatus(id);

  Future<void> cancelPointsPay(int id) async {
    try {
      await api.cancelPointsPay(id);
    } finally {
      if (pointsPayment?['id'] == id) pointsPayment = null;
      notifyListeners();
    }
  }

  void applyPointsPay(Map<String, dynamic> p) {
    pointsPayment = p;
    notifyListeners();
  }

  /// Sube las ventas pendientes. Las que el servidor rechaza (por ejemplo, un producto que ya no existe) se apartan
  /// para que no traben a las demás, y quedan a la vista.
  Future<void> sync() async {
    if (_syncing || local.pending.isEmpty || api.deviceToken == null) return;
    _syncing = true;
    try {
      final batch = local.pending.take(50).toList();
      final r = await api.uploadSales(batch);
      final results = ((r['results'] as List?) ?? []).cast<Map>();
      final done = <String>{};
      final rej = rejected;
      for (final res in results) {
        final uuid = res['client_uuid'] as String?;
        if (uuid == null) continue;
        done.add(uuid);
        if (res['ok'] == true) {
          if (lastSale != null && lastSale!['client_uuid'] == uuid) {
            lastSale = {...lastSale!, ...res.cast<String, dynamic>(), 'pending': false};
          }
        } else {
          rej.insert(0, {'client_uuid': uuid, 'error': res['error'], 'sale': batch.firstWhere((s) => s['client_uuid'] == uuid)});
        }
      }
      local.pending.removeWhere((s) => done.contains(s['client_uuid']));
      await local.savePending();
      local.config['rejected'] = rej.take(50).toList();
      await local.saveConfig();
      _setOnline(true);
      if (rej.isNotEmpty) notice = '${rej.length} venta(s) no se pudieron registrar. Revisalas en Ventas (F9).';
      await reloadShift();
    } on ApiError catch (e) {
      if (e.offline) {
        _setOnline(false);
      } else if (e.status == 401) {
        notice = 'Esta caja fue desvinculada del comercio. Las ventas sin subir quedaron guardadas.';
      }
    } finally {
      _syncing = false;
      notifyListeners();
    }
  }

  Future<void> dismissRejected() async {
    local.config['rejected'] = [];
    await local.saveConfig();
    notice = null;
    notifyListeners();
  }

  Future<void> setPrinter(String? url, String? name, int paper) async {
    local.config['printer'] = url == null ? null : {'url': url, 'name': name};
    local.config['paper'] = paper;
    await local.saveConfig();
    notifyListeners();
  }

  /// Comanda de cocina (off | print | board | both), impresora de la cocina (null = la de tickets) y servicio por defecto.
  Future<void> setKitchen({String? mode, Map<String, dynamic>? printer, bool clearPrinter = false, String? service}) async {
    if (mode != null) local.config['kitchen'] = mode;
    if (printer != null || clearPrinter) local.config['kitchen_printer'] = printer;
    if (service != null) {
      local.config['service'] = service;
      if (cart.isEmpty) this.service = service;
    }
    await local.saveConfig();
    notifyListeners();
  }

  /// Milímetros de margen de más en el ticket (0, 2 o 4), para impresoras que igual cortan los bordes.
  Future<void> setTicketMargin(int mm) async {
    local.config['margin_extra'] = mm;
    await local.saveConfig();
    notifyListeners();
  }

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}
