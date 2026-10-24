import 'dart:io';

import 'package:flutter_test/flutter_test.dart';
import 'package:pdf/pdf.dart';
import 'package:trappi_caja/caja.dart';
import 'package:trappi_caja/ticket.dart';

void main() {
  final store = {'name': 'Burger Mix', 'address': 'Alsina 120', 'phone': '291 455 6677'};
  final cheddar = {'id': 11, 'name': 'Cheddar', 'price': 800};
  final jugosa = {'id': 10, 'name': 'Jugosa', 'price': 0};

  test('línea con opciones y aclaración: precio, comparación y lo que se manda al servidor', () {
    final l = Line(productId: 5, name: 'Hamburguesa', unitPrice: 9000, quantity: 2, modifiers: [jugosa, cheddar], note: 'sin cebolla');
    expect(l.unit, 9800);
    expect(l.total, 19600);
    expect(l.modifiersText, 'Jugosa, Cheddar');
    expect(l.sameAs(5, [cheddar, jugosa], 'sin cebolla'), isTrue); // el orden de las opciones no importa
    expect(l.sameAs(5, [jugosa], 'sin cebolla'), isFalse);
    expect(l.sameAs(5, [jugosa, cheddar], ''), isFalse); // otra aclaración: otra línea
    expect(l.toJson(), {'product_id': 5, 'quantity': 2, 'modifiers': [10, 11], 'note': 'sin cebolla'}); // el precio lo pone el servidor
    final back = Line.fromLocal(l.toLocal()); // ticket en espera guardado en la compu
    expect(back.total, l.total);
    expect(back.note, 'sin cebolla');
    expect(Line(name: 'Monto libre', unitPrice: 500).toJson(), {'name': 'Monto libre', 'unit_price': 500.0, 'quantity': 1});
  });

  final sale = {
    'number': 812,
    'call_number': 23,
    'customer_name': 'Juan',
    'service': 'llevar',
    'sold_at': '2026-10-23T21:30:00Z',
    'lines': [
      {'name': 'Hamburguesa Clásica', 'quantity': 2, 'total': 19600, 'modifiers_text': 'Jugosa, Cheddar', 'note': 'sin cebolla'},
      {'name': 'Coca Cola 1,5 L', 'quantity': 1, 'total': 4200},
    ],
    'subtotal': 23800,
    'total': 23800,
    'payment_method': 'mixto',
    'payments': [
      {'method': 'efectivo', 'amount': 13800},
      {'method': 'mercadopago', 'amount': 10000},
    ],
    'paid_with': 20000,
  };

  test('ticket con número para llamar, opciones y pago mixto; comanda de cocina; cierre de caja', () async {
    final out = Platform.environment['TICKET_OUT'];
    for (final paper in [80, 58]) {
      final t = await ticketPdf(store, sale, paper: paper);
      final k = await kitchenPdf(sale, paper: paper);
      expect(t.format.width, closeTo(paper * PdfPageFormat.mm, 0.01));
      expect(k.format.width, closeTo(paper * PdfPageFormat.mm, 0.01));
      expect(k.format.marginLeft, greaterThanOrEqualTo(safeSideMargin(paper)));
      if (out != null) {
        File('$out/venta-$paper.pdf').writeAsBytesSync(t.bytes);
        File('$out/comanda-$paper.pdf').writeAsBytesSync(k.bytes);
      }
    }
    expect(callLabel(sale), 'Pedido 23 · Juan');
    expect(callLabel({'number': 3}), '');
    final close = await closePdf(store, {
      'opened_at': '2026-10-23T12:00:00Z',
      'closed_at': '2026-10-23T23:40:00Z',
      'closed_by': 'Dueño',
      'sales': 41,
      'total': 612300,
      'by_method': {
        'efectivo': {'label': 'Efectivo', 'count': 25, 'total': 350000},
        'mercadopago': {'label': 'Mercado Pago', 'count': 14, 'total': 220300},
        'transferencia': {'label': 'Transferencia', 'count': 3, 'total': 42000},
      },
      'discounts': 3500,
      'voided': 1,
      'voided_total': 8200,
      'opening_cash': 20000,
      'cash_in': 5000,
      'cash_out': 30000,
      'movements': [
        {'label': 'Retiro', 'kind': 'retiro', 'amount': 30000, 'reason': 'Proveedor de pan'},
        {'label': 'Ingreso', 'kind': 'ingreso', 'amount': 5000, 'reason': 'Cambio'},
      ],
      'expected_cash': 345000,
      'bills': {'20000': 12, '10000': 8, '1000': 24, 'monedas': 500},
      'counted_cash': 344500,
      'difference': -500,
      'points': 120,
      'qr_total': 30,
    });
    expect(close.format.height.isFinite, isTrue);
    if (out != null) File('$out/cierre-80.pdf').writeAsBytesSync(close.bytes);
  });
}
