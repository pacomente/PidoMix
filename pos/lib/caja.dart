import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import 'api.dart';
import 'local.dart';
import 'promos.dart';

enum Stage { loading, link, cashier, openShift, sell }

/// Una línea del ticket que se está armando. product_id null = monto libre.
/// [modifiers]: opciones del menú elegidas ({id, name, price}); el precio final lo vuelve a calcular el servidor.
/// [note]: aclaración para la cocina ("sin cebolla").
/// [sent]: en una mesa, ya se mandó a la cocina (sacarla la autoriza el dueño).
class Line {
  Line({this.productId, required this.name, required this.unitPrice, this.quantity = 1, List<Map<String, dynamic>>? modifiers, this.note = '', this.sent = false})
      : modifiers = modifiers ?? [];
  bool sent;
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
  Map<String, dynamic> toLocal() =>
      {'product_id': productId, 'name': name, 'unit_price': unitPrice, 'quantity': quantity, 'modifiers': modifiers, 'note': note, 'sent': sent};
  Line copy(int qty) => Line(productId: productId, name: name, unitPrice: unitPrice, quantity: qty, modifiers: [...modifiers], note: note, sent: sent);
  static Line fromLocal(Map m) => Line(
        productId: m['product_id'] as int?,
        name: m['name'].toString(),
        unitPrice: (m['unit_price'] as num).toDouble(),
        quantity: (m['quantity'] as num).toInt(),
        modifiers: ((m['modifiers'] as List?) ?? []).cast<Map>().map((x) => x.cast<String, dynamic>()).toList(),
        note: (m['note'] ?? '').toString(),
        sent: m['sent'] == true,
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

  /// Promos del mostrador que aplican a estas líneas ahora (el servidor las vuelve a calcular con la hora de la venta).
  List<AppliedPromo> promosFor(List<Line> lines) {
    final promos = ((local.catalog['promos'] as List?) ?? []).cast<Map>().map((m) => m.cast<String, dynamic>()).toList();
    if (promos.isEmpty) return [];
    final section = {for (final p in products) p['id']: p['section_id'] as int?};
    return applyPromos(
        promos,
        [for (final l in lines) PromoLine(productId: l.productId, sectionId: section[l.productId], quantity: l.quantity, unit: l.unit, base: l.unitPrice)],
        DateTime.now());
  }

  List<AppliedPromo> get appliedPromos => promosFor(cart);
  double get promoDiscount => appliedPromos.fold(0.0, (a, p) => a + p.amount);

  /// Total del ticket antes de los Puntos Trappi (con las promos y el descuento manual).
  double get ticketTotal => (subtotal - promoDiscount - discount).clamp(0, double.infinity).toDouble();
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
    final i = cart.indexWhere((l) => !l.sent && l.sameAs(id, modifiers, n));
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
    discount = v.clamp(0, (subtotal - promoDiscount).clamp(0, double.infinity)).toDouble();
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
    customer = null;
    service = table != null ? 'aca' : defaultService;
    notifyListeners();
  }

  // ---------- cliente frecuente ----------

  /// Cliente con cuenta Trappi elegido para esta venta: los puntos van directo a su cuenta (sin escanear el QR).
  Map<String, dynamic>? customer;

  Future<Map<String, dynamic>?> findCustomer(String phone) async {
    try {
      final r = await api.customer(phone);
      return (r['customer'] as Map).cast<String, dynamic>();
    } on ApiError catch (e) {
      if (e.status == 404) return null;
      rethrow;
    }
  }

  void setAccount(Map<String, dynamic>? c) {
    customer = c;
    if (c != null && customerName.isEmpty) customerName = c['name'].toString().split(' ').first;
    notifyListeners();
  }

  /// Vuelve a cargar lo que compró la última vez (los productos que siguen a la venta, con sus opciones si todavía existen).
  int repeat(List<Map<String, dynamic>> items) {
    var n = 0;
    final byId = {for (final p in products) p['id']: p};
    for (final i in items) {
      final p = byId[i['product_id']];
      if (p == null || (p['stock'] != null && (p['stock'] as num) <= 0)) continue;
      final wanted = ((i['modifiers'] as List?) ?? []).cast<num>().map((x) => x.toInt()).toSet();
      final mods = [
        for (final g in groupsOf(p))
          for (final o in ((g['options'] as List?) ?? []).cast<Map>())
            if (wanted.contains(o['id'])) o.cast<String, dynamic>()
      ];
      addProduct(p, modifiers: mods, note: (i['note'] ?? '').toString(), quantity: ((i['quantity'] as num?) ?? 1).toInt());
      n++;
    }
    return n;
  }

  // ---------- agotar desde la caja y resumen del día ----------

  /// out | tomorrow | back. También cambia en la app y la web.
  Future<void> setStock(int productId, String action) async {
    final r = await api.setStock(productId, action);
    final list = ((local.catalog['products'] as List?) ?? []).cast<Map>();
    for (final p in list) {
      if (p['id'] == productId) p['stock'] = r['stock'];
    }
    await local.saveCatalog();
    notifyListeners();
  }

  Future<Map<String, dynamic>> dayReport({String? asToken}) => api.reportToday(asToken: asToken);

  // ---------- salón (mesas) ----------

  List<Map<String, dynamic>> get tables => ((local.catalog['tables'] as List?) ?? []).cast<Map>().map((m) => m.cast<String, dynamic>()).toList();

  /// Cuentas abiertas por mesa (quedan en la compu): {"3": {lines, guests, waiter, opened_at, bill}}.
  Map<String, dynamic> get tabs => (local.config['tabs'] as Map?)?.cast<String, dynamic>() ?? {};

  /// La mesa que se está atendiendo (null: mostrador).
  int? table;
  Map<String, dynamic>? get currentTable => table == null ? null : tables.where((t) => t['id'] == table).firstOrNull;
  Map<String, dynamic>? tabOf(int id) => (tabs['$id'] as Map?)?.cast<String, dynamic>();
  String tableLabel(int id) {
    final t = tables.where((x) => x['id'] == id).firstOrNull;
    final name = (t?['name'] ?? id).toString();
    return RegExp(r'^\d+$').hasMatch(name) ? 'Mesa $name' : name;
  }

  double tabTotal(Map<String, dynamic> tab) {
    final lines = [for (final l in ((tab['lines'] as List?) ?? []).cast<Map>()) Line.fromLocal(l)];
    final sub = lines.fold(0.0, (a, l) => a + l.total);
    return (sub - promosFor(lines).fold(0.0, (a, p) => a + p.amount)).clamp(0, double.infinity).toDouble();
  }

  void _saveTab() {
    final id = table;
    if (id == null) return;
    final all = tabs;
    if (cart.isEmpty) {
      all.remove('$id');
    } else {
      final old = tabOf(id) ?? {};
      all['$id'] = {
        ...old,
        'lines': [for (final l in cart) l.toLocal()],
        'opened_at': old['opened_at'] ?? DateTime.now().toIso8601String(),
        'waiter': old['waiter'] ?? cashier?['name'],
        'discount': discount,
        'approval': discountApproval,
      };
    }
    local.config['tabs'] = all;
    local.saveConfig();
  }

  @override
  void notifyListeners() {
    if (table != null) _saveTab(); // cada cambio de la mesa queda guardado en la compu al instante
    super.notifyListeners();
  }

  /// Abre (o retoma) la cuenta de una mesa. Lo que estaba cargado en el mostrador pasa a espera.
  Future<void> openTable(int id) async {
    if (locked) return;
    if (table == null && cart.isNotEmpty) await hold();
    if (table != null) _saveTab();
    final tab = tabOf(id);
    table = null; // mientras se arma, que no se guarde en la mesa equivocada
    cart
      ..clear()
      ..addAll([for (final l in ((tab?['lines'] as List?) ?? []).cast<Map>()) Line.fromLocal(l)]);
    selected = cart.isEmpty ? -1 : cart.length - 1;
    discount = ((tab?['discount'] as num?) ?? 0).toDouble();
    discountApproval = tab?['approval'] as String?;
    customerName = '';
    customer = null;
    service = 'aca';
    table = id;
    notifyListeners();
  }

  /// Vuelve al salón: la cuenta de la mesa queda guardada.
  void leaveTable() {
    if (table == null) return;
    _saveTab();
    table = null;
    cart.clear();
    selected = -1;
    discount = 0;
    discountApproval = null;
    service = defaultService;
    notifyListeners();
  }

  void setGuests(int n) {
    if (table == null) return;
    final all = tabs;
    all['$table'] = {...?tabOf(table!), 'guests': n};
    local.config['tabs'] = all;
    if (cart.isEmpty) {
      local.saveConfig();
      super.notifyListeners();
    } else {
      notifyListeners();
    }
  }

  /// Pasa la cuenta a otra mesa. Si la otra está ocupada, se juntan.
  Future<void> moveTable(int to) async {
    final from = table;
    if (from == null || from == to) return;
    _saveTab();
    final all = tabs;
    final mine = (all.remove('$from') as Map?)?.cast<String, dynamic>() ?? {};
    final other = (all['$to'] as Map?)?.cast<String, dynamic>();
    all['$to'] = other == null
        ? mine
        : {...other, 'lines': [...((other['lines'] as List?) ?? []), ...((mine['lines'] as List?) ?? [])], 'guests': ((other['guests'] as num?) ?? 0) + ((mine['guests'] as num?) ?? 0)};
    local.config['tabs'] = all;
    await local.saveConfig();
    table = null;
    await openTable(to);
  }

  /// Marca que se imprimió la pre-cuenta (la mesa se ve "pidió la cuenta").
  void markBill() {
    if (table == null) return;
    final all = tabs;
    all['$table'] = {...?tabOf(table!), 'bill': true};
    local.config['tabs'] = all;
    notifyListeners();
  }

  List<Line> get unsent => cart.where((l) => !l.sent).toList();

  /// Manda a la cocina lo nuevo de la mesa: comanda impresa y/o tablero de Comandas. Devuelve la comanda (para imprimir) o null.
  Future<Map<String, dynamic>?> sendToKitchen() async {
    final id = table;
    final news = unsent;
    if (id == null || news.isEmpty) return null;
    final label = '${tableLabel(id)}${cashier != null ? ' · ${cashier!['name']}' : ''}';
    final ticket = {
      'client_uuid': const Uuid().v4(),
      'label': label,
      'cashier_id': cashier?['id'],
      'sent_at': DateTime.now().toUtc().toIso8601String(),
      'items': [for (final l in news) l.preview()..remove('unit_price')..remove('total')],
    };
    for (final l in news) {
      l.sent = true;
    }
    if (kitchenMode == 'board' || kitchenMode == 'both') {
      final q = ((local.config['pending_kitchen'] as List?) ?? []).cast<Map>().toList()..add(ticket);
      local.config['pending_kitchen'] = q;
    }
    notifyListeners();
    unawaited(sync());
    return {...ticket, 'customer_name': label, 'service': 'aca', 'lines': ticket['items']};
  }

  /// Cobra el ticket actual. Se guarda primero en la compu y después se intenta subir:
  /// si no hay internet, la venta queda pendiente (sin QR de puntos hasta que se suba).
  /// Lo que se cobra: el ticket entero, o una parte de la mesa ([part]: índice de línea → cantidad).
  List<Line> linesFor(Map<int, int>? part) =>
      part == null ? cart : [for (final e in part.entries) if (e.value > 0 && e.key < cart.length) cart[e.key].copy(e.value.clamp(1, cart[e.key].quantity))];

  double totalFor(Map<int, int>? part) {
    if (part == null) return total;
    final lines = linesFor(part);
    final sub = lines.fold(0.0, (a, l) => a + l.total);
    return (sub - promosFor(lines).fold(0.0, (a, p) => a + p.amount)).clamp(0, double.infinity).toDouble();
  }

  /// [payments]: pago mixto o cuenta dividida ([{method, amount}], de dos a ocho pagos; el medio puede repetirse).
  /// [tip]: propina (va aparte del total, con el primer medio). [part]: cobrar solo esas líneas de la mesa.
  Future<Map<String, dynamic>> charge(String method, double? paidWith, {List<Map<String, dynamic>>? payments, double tip = 0, Map<int, int>? part}) async {
    final lines = linesFor(part);
    final atTable = table != null;
    final applied = promosFor(lines);
    final promoOff = applied.fold(0.0, (a, p) => a + p.amount);
    final disc = part == null ? discount : 0.0;
    final points = part == null ? pointsDiscount : 0.0;
    final sub = lines.fold(0.0, (a, l) => a + l.total);
    final tot = (sub - promoOff - disc - points).clamp(0, double.infinity).toDouble();
    final call = atTable ? null : await _takeCallNumber();
    final cashPart = method == 'efectivo'
        ? tot + tip
        : payments?.where((p) => p['method'] == 'efectivo').fold<double>(0, (a, p) => a + (p['amount'] as num).toDouble());
    final sale = <String, dynamic>{
      'client_uuid': const Uuid().v4(),
      'cashier_id': cashier!['id'],
      'items': lines.map((l) => l.toJson()).toList(),
      'discount': double.parse(disc.toStringAsFixed(2)),
      if (part == null && pointsPayment != null) 'points_payment_id': pointsPayment!['id'],
      'payment_method': method,
      'payments': ?payments,
      if (cashPart != null && cashPart > 0 && paidWith != null) 'paid_with': paidWith,
      'sold_at': DateTime.now().toUtc().toIso8601String(),
      'call_number': ?call,
      if (customerName.isNotEmpty) 'customer_name': customerName,
      if (service.isNotEmpty) 'service': service,
      if (!atTable && (kitchenMode == 'board' || kitchenMode == 'both')) 'kitchen': true, // la mesa ya mandó sus tandas
      if (part == null && discountApproval != null) 'approval': discountApproval,
      if (tip > 0) 'tip': double.parse(tip.toStringAsFixed(2)),
      if (customer != null) 'account_id': customer!['id'],
      if (atTable) 'table_name': tableLabel(table!),
    };
    final preview = <String, dynamic>{
      ...sale,
      'number': null,
      'pending': true,
      'subtotal': sub,
      'total': tot,
      'promo_discount': promoOff,
      'promos': [for (final p in applied) {'id': p.id, 'name': p.name, 'amount': p.amount}],
      'points_discount': points,
      'cashier_name': cashier!['name'],
      'lines': lines.map((l) => l.preview()).toList(),
      if (cashPart != null && cashPart > 0 && paidWith != null) 'cash_part': cashPart,
    };
    local.pending.add(sale);
    await local.savePending();
    if (part != null) {
      // se cobró una parte de la mesa: se descuenta de la cuenta y el resto sigue abierto
      for (final e in part.entries.toList()..sort((a, b) => b.key.compareTo(a.key))) {
        if (e.key >= cart.length) continue;
        cart[e.key].quantity -= e.value;
        if (cart[e.key].quantity <= 0) cart.removeAt(e.key);
      }
      selected = cart.isEmpty ? -1 : 0;
      customer = null;
      notifyListeners();
    } else if (atTable) {
      final id = table!;
      table = null;
      final all = tabs..remove('$id');
      local.config['tabs'] = all;
      await local.saveConfig();
      cart.clear();
      clearCart();
    } else {
      clearCart();
    }
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
    final kitchen = ((local.config['pending_kitchen'] as List?) ?? []).cast<Map>().map((m) => m.cast<String, dynamic>()).toList();
    if (_syncing || (local.pending.isEmpty && kitchen.isEmpty) || api.deviceToken == null) return;
    _syncing = true;
    try {
      if (kitchen.isNotEmpty) {
        // las tandas de las mesas al tablero de Comandas (las que el servidor rechaza no traban a las demás)
        final r = await api.uploadKitchen(kitchen.take(50).toList());
        final done = {for (final x in ((r['results'] as List?) ?? []).cast<Map>()) x['client_uuid']};
        local.config['pending_kitchen'] = kitchen.where((k) => !done.contains(k['client_uuid'])).toList();
        await local.saveConfig();
      }
      if (local.pending.isEmpty) {
        _setOnline(true);
        return;
      }
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
