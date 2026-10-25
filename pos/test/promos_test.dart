import 'package:flutter_test/flutter_test.dart';
import 'package:trappi_caja/promos.dart';

// Los mismos casos que tests/test_pos_salon.py::test_motor_de_promos: la caja y el servidor tienen que dar lo mismo.
void main() {
  final two4one = {'id': 1, 'name': '2x1 cervezas', 'kind': 'nxm', 'buy': 2, 'pay': 1, 'value': 0, 'product_ids': [10], 'section_ids': [], 'days': '0123456', 'start': '18:00', 'end': '21:00'};
  final combo = {'id': 2, 'name': 'Combo', 'kind': 'combo', 'buy': 2, 'pay': 1, 'value': 12000, 'product_ids': [1, 2, 3], 'section_ids': [], 'days': '0123456', 'start': null, 'end': null};
  final pct = {'id': 3, 'name': '20% pizzas', 'kind': 'percent', 'buy': 2, 'pay': 1, 'value': 20, 'product_ids': [], 'section_ids': [7], 'days': '1', 'start': null, 'end': null};
  const lines = [
    PromoLine(productId: 10, sectionId: null, quantity: 3, unit: 3500, base: 3500),
    PromoLine(productId: 1, sectionId: 1, quantity: 2, unit: 9800, base: 9000),
    PromoLine(productId: 2, sectionId: 1, quantity: 1, unit: 3000, base: 3000),
    PromoLine(productId: 3, sectionId: 1, quantity: 1, unit: 2500, base: 2500),
    PromoLine(productId: 20, sectionId: 7, quantity: 1, unit: 11000, base: 11000),
  ];

  Map<int, double> run(DateTime at) => {for (final a in applyPromos([two4one, combo, pct], lines, at)) a.id: a.amount};

  test('lunes en el happy hour: 2x1 y combo; el % es solo los martes', () {
    expect(run(DateTime(2026, 10, 26, 19, 30)), {1: 3500.0, 2: 2500.0});
  });

  test('martes fuera del happy hour: combo y 20% en pizzas', () {
    expect(run(DateTime(2026, 10, 27, 22, 0)), {2: 2500.0, 3: 2200.0});
  });

  test('franja que pasa la medianoche', () {
    final night = {...two4one, 'start': '22:00', 'end': '02:00'};
    expect(promoOn(night, DateTime(2026, 10, 26, 1, 0)), isTrue);
    expect(promoOn(night, DateTime(2026, 10, 26, 12, 0)), isFalse);
  });
}
