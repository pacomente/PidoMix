import 'dart:async';

import 'package:flutter/foundation.dart';
import 'package:uuid/uuid.dart';

import 'api.dart';
import 'local.dart';

enum Stage { loading, link, cashier, openShift, sell }

/// Una línea del ticket que se está armando. product_id null = monto libre.
class Line {
  Line({this.productId, required this.name, required this.unitPrice, this.quantity = 1});
  final int? productId;
  final String name;
  final double unitPrice;
  int quantity;
  double get total => unitPrice * quantity;

  Map<String, dynamic> toJson() => {
        if (productId != null) 'product_id': productId,
        if (productId == null) 'name': name,
        if (productId == null) 'unit_price': unitPrice,
        'quantity': quantity,
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
  double get total => (subtotal - discount).clamp(0, double.infinity).toDouble();

  /// Primeros 9 productos: se cargan con las teclas 1 a 9.
  List<Map<String, dynamic>> get quick => products.take(9).toList();

  Future<void> start() async {
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
    final printer = local.config['printer'];
    final width = local.config['paper'];
    await local.unlink();
    if (printer != null) local.config['printer'] = printer;
    if (width != null) local.config['paper'] = width;
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

  Future<Map<String, dynamic>> closeShift(double counted, {String? asToken}) async {
    await sync(); // primero se suben las ventas pendientes, así el cierre las cuenta
    if (local.pending.isNotEmpty) throw ApiError('Quedan ventas sin subir. Conectate a internet antes de cerrar la caja.', 409);
    final summary = await api.closeShift(counted, asToken: asToken);
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

  void addProduct(Map<String, dynamic> p) {
    final id = p['id'] as int;
    final i = cart.indexWhere((l) => l.productId == id);
    if (i >= 0) {
      cart[i].quantity = (cart[i].quantity + 1).clamp(1, 999);
      selected = i;
    } else {
      cart.add(Line(productId: id, name: p['name'] as String, unitPrice: (p['price'] as num).toDouble()));
      selected = cart.length - 1;
    }
    notifyListeners();
  }

  void addFree(String name, double amount) {
    cart.add(Line(name: name.trim().isEmpty ? 'Monto libre' : name.trim(), unitPrice: amount));
    selected = cart.length - 1;
    notifyListeners();
  }

  /// Busca por código de barras exacto. Devuelve si lo encontró.
  bool addBarcode(String code) {
    final c = code.trim();
    if (c.isEmpty) return false;
    for (final p in products) {
      if ((p['barcode'] ?? '').toString().trim() == c) {
        addProduct(p);
        return true;
      }
    }
    return false;
  }

  void changeQty(int delta) {
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

  void setDiscount(double v) {
    discount = v.clamp(0, subtotal).toDouble();
    notifyListeners();
  }

  void clearCart() {
    cart.clear();
    selected = -1;
    discount = 0;
    notifyListeners();
  }

  /// Cobra el ticket actual. Se guarda primero en la compu y después se intenta subir:
  /// si no hay internet, la venta queda pendiente (sin QR de puntos hasta que se suba).
  Future<Map<String, dynamic>> charge(String method, double? paidWith) async {
    final sale = <String, dynamic>{
      'client_uuid': const Uuid().v4(),
      'cashier_id': cashier!['id'],
      'items': cart.map((l) => l.toJson()).toList(),
      'discount': double.parse(discount.toStringAsFixed(2)),
      'payment_method': method,
      if (method == 'efectivo' && paidWith != null) 'paid_with': paidWith,
      'sold_at': DateTime.now().toUtc().toIso8601String(),
    };
    final preview = <String, dynamic>{
      ...sale,
      'number': null,
      'pending': true,
      'subtotal': subtotal,
      'total': total,
      'cashier_name': cashier!['name'],
      'lines': cart.map((l) => {'name': l.name, 'quantity': l.quantity, 'unit_price': l.unitPrice, 'total': l.total}).toList(),
    };
    local.pending.add(sale);
    await local.savePending();
    clearCart();
    lastSale = preview;
    notifyListeners();
    await sync();
    return lastSale!;
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

  @override
  void dispose() {
    _timer?.cancel();
    super.dispose();
  }
}
