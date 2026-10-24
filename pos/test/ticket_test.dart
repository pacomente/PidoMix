import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:pdf/pdf.dart';
import 'package:trappi_caja/ticket.dart';

void main() {
  final store = {'name': 'Burger Mix', 'address': 'Alsina 120', 'phone': '291 455 6677'};
  final sale = {
    'number': 152,
    'sold_at': '2026-10-22T21:30:00Z',
    'lines': [
      {'name': 'Hamburguesa doble con cheddar y panceta', 'quantity': 2, 'total': 25800},
      {'name': 'Coca Cola 1,5 L', 'quantity': 1, 'total': 4200},
    ],
    'subtotal': 30000,
    'discount': 1500,
    'total': 28500,
    'payment_method': 'efectivo',
    'paid_with': 1000000,
  };

  test('el ticket mide lo que el rollo y deja libre el borde que la térmica no imprime', () async {
    for (final paper in [80, 58]) {
      final t = await ticketPdf(store, sale, paper: paper);
      expect(t.format.width, closeTo(paper * PdfPageFormat.mm, 0.01));
      expect(t.format.height.isFinite, isTrue); // alto real del contenido, no una hoja A4
      expect(t.format.height, lessThan(200 * PdfPageFormat.mm));
      expect(t.format.marginLeft, greaterThanOrEqualTo(safeSideMargin(paper)));
      expect(t.format.marginRight, greaterThanOrEqualTo(safeSideMargin(paper)));
      final out = Platform.environment['TICKET_OUT'];
      if (out != null) File('$out/ticket-$paper.pdf').writeAsBytesSync(t.bytes);
    }
  });

  test('márgenes de más y los que informa la impresora', () async {
    final extra = await ticketPdf(store, sale, paper: 80, extraMarginMm: 2);
    expect(extra.format.marginLeft, closeTo(7 * PdfPageFormat.mm, 0.01));
    final printer = await ticketPdf(store, sale, paper: 80, minSideMargin: 7.5 * PdfPageFormat.mm);
    expect(printer.format.marginRight, closeTo(7.5 * PdfPageFormat.mm, 0.01));
  });
}
