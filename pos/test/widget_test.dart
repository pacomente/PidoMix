import 'package:flutter_test/flutter_test.dart';
import 'package:trappi_caja/caja.dart';

void main() {
  test('formato de plata', () {
    expect(money(0), '\$ 0');
    expect(money(1500), '\$ 1.500');
    expect(money(1234567.5), '\$ 1.234.567,50');
    expect(money(-200), '-\$ 200');
  });

  test('leer montos tipeados', () {
    expect(parseMoney('1.500'), 1500);
    expect(parseMoney('\$ 2.000,50'), 2000.5);
    expect(parseMoney(''), isNull);
  });

  test('línea de monto libre manda nombre y precio; producto solo el id', () {
    expect(Line(productId: 3, name: 'Pizza', unitPrice: 900, quantity: 2).toJson(), {'product_id': 3, 'quantity': 2});
    expect(Line(name: 'Varios', unitPrice: 150).toJson(), {'name': 'Varios', 'unit_price': 150.0, 'quantity': 1});
  });
}
