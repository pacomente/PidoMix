/// Promos del mostrador (2x1, % y combos con días y horario). Misma cuenta que app/services/pos_salon.py:
/// primero los combos, después los NxM y al final los %; cada unidad entra en una sola promo. La caja las muestra;
/// el servidor las vuelve a calcular al registrar la venta.
class PromoLine {
  const PromoLine({required this.productId, required this.sectionId, required this.quantity, required this.unit, required this.base});
  final int? productId;
  final int? sectionId;
  final int quantity;
  final double unit; // con las opciones
  final double base; // precio del producto
}

class AppliedPromo {
  const AppliedPromo(this.id, this.name, this.amount);
  final int id;
  final String name;
  final double amount;
}

double _cents(double v) => (v * 100).roundToDouble() / 100;

String _hm(DateTime t) => '${t.hour.toString().padLeft(2, '0')}:${t.minute.toString().padLeft(2, '0')}';

bool promoOn(Map<String, dynamic> p, DateTime local) {
  final day = (local.weekday - 1).toString(); // 0 = lunes, como en el servidor
  if (!(p['days'] ?? '').toString().contains(day)) return false;
  final start = p['start'] as String?, end = p['end'] as String?;
  if (start == null || end == null || start.isEmpty || end.isEmpty) return true;
  final hm = _hm(local);
  return start.compareTo(end) <= 0 ? (hm.compareTo(start) >= 0 && hm.compareTo(end) < 0) : (hm.compareTo(start) >= 0 || hm.compareTo(end) < 0);
}

List<AppliedPromo> applyPromos(List<Map<String, dynamic>> promos, List<PromoLine> lines, DateTime local) {
  final units = <({int line, int product, int? section, double unit, double base})>[];
  for (final (i, l) in lines.indexed) {
    if (l.productId == null) continue;
    for (var q = 0; q < l.quantity; q++) {
      units.add((line: i, product: l.productId!, section: l.sectionId, unit: l.unit, base: l.base));
    }
  }
  final used = List<bool>.filled(units.length, false);
  final order = List<int>.generate(units.length, (k) => k)
    ..sort((a, b) {
      final c = units[b].unit.compareTo(units[a].unit); // de la más cara a la más barata
      return c != 0 ? c : units[a].line.compareTo(units[b].line);
    });
  final on = promos.where((p) => promoOn(p, local)).toList();
  List<int> ids(Object? v) => ((v as List?) ?? []).map((x) => (x as num).toInt()).toList();
  bool eligible(Map<String, dynamic> p, int k) => ids(p['product_ids']).contains(units[k].product) || (units[k].section != null && ids(p['section_ids']).contains(units[k].section));
  final out = <AppliedPromo>[];

  for (final p in on.where((x) => x['kind'] == 'combo')) {
    final need = <int, int>{};
    for (final id in ids(p['product_ids'])) {
      need[id] = (need[id] ?? 0) + 1;
    }
    final price = ((p['value'] as num?) ?? 0).toDouble();
    if (need.isEmpty || price <= 0) continue;
    var total = 0.0;
    while (true) {
      final pick = <int>[];
      var ok = true;
      for (final e in need.entries) {
        final got = order.where((k) => !used[k] && units[k].product == e.key && !pick.contains(k)).take(e.value).toList();
        if (got.length < e.value) {
          ok = false;
          break;
        }
        pick.addAll(got);
      }
      if (!ok || pick.isEmpty) break;
      final saving = pick.fold(0.0, (a, k) => a + units[k].base) - price;
      if (saving <= 0) break;
      for (final k in pick) {
        used[k] = true;
      }
      total += saving;
    }
    if (total > 0) out.add(AppliedPromo((p['id'] as num).toInt(), p['name'].toString(), _cents(total)));
  }
  for (final p in on.where((x) => x['kind'] == 'nxm')) {
    final buy = ((p['buy'] as num?) ?? 2).toInt(), pay = ((p['pay'] as num?) ?? 1).toInt();
    if (buy < 2 || pay < 0 || pay >= buy) continue;
    final pool = order.where((k) => !used[k] && eligible(p, k)).toList();
    var total = 0.0;
    for (var g = 0; g + buy <= pool.length; g += buy) {
      final group = pool.sublist(g, g + buy);
      total += group.skip(pay).fold(0.0, (a, k) => a + units[k].unit); // las más baratas del grupo van gratis
      for (final k in group) {
        used[k] = true;
      }
    }
    if (total > 0) out.add(AppliedPromo((p['id'] as num).toInt(), p['name'].toString(), _cents(total)));
  }
  for (final p in on.where((x) => x['kind'] == 'percent')) {
    final pct = ((p['value'] as num?) ?? 0).toDouble();
    if (pct <= 0 || pct > 100) continue;
    var total = 0.0;
    for (final k in order) {
      if (!used[k] && eligible(p, k)) {
        total += units[k].unit * pct / 100;
        used[k] = true;
      }
    }
    if (total > 0) out.add(AppliedPromo((p['id'] as num).toInt(), p['name'].toString(), _cents(total)));
  }
  return out;
}
