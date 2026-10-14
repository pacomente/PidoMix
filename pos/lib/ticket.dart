import 'dart:typed_data';

import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';

import 'caja.dart';

/// Ticket para impresora térmica (58 u 80 mm) con el QR de Puntos Trappi.
Future<Uint8List> ticketPdf(Map<String, dynamic> store, Map<String, dynamic> sale, {int paper = 80}) async {
  final doc = pw.Document(title: 'Ticket Trappi');
  final format = paper == 58 ? PdfPageFormat.roll57 : PdfPageFormat.roll80;
  final small = pw.TextStyle(fontSize: paper == 58 ? 7 : 8);
  final normal = pw.TextStyle(fontSize: paper == 58 ? 8 : 9);
  final bold = pw.TextStyle(fontSize: paper == 58 ? 10 : 12, fontWeight: pw.FontWeight.bold);
  final lines = ((sale['lines'] ?? sale['items']) as List).cast<Map>();
  final when = DateTime.tryParse((sale['sold_at'] ?? '').toString())?.toLocal() ?? DateTime.now();
  final claim = (sale['claim'] as Map?)?.cast<String, dynamic>();
  final paidWith = (sale['paid_with'] as num?)?.toDouble();
  final total = (sale['total'] as num).toDouble();
  final discount = ((sale['discount'] as num?) ?? 0).toDouble();
  final pointsOff = ((sale['points_discount'] as num?) ?? 0).toDouble();
  String two(int v) => v.toString().padLeft(2, '0');

  doc.addPage(pw.Page(
    pageFormat: format.copyWith(marginLeft: 3 * PdfPageFormat.mm, marginRight: 3 * PdfPageFormat.mm, marginTop: 4 * PdfPageFormat.mm),
    build: (_) => pw.Column(crossAxisAlignment: pw.CrossAxisAlignment.stretch, children: [
      pw.Text((store['name'] ?? 'Comercio').toString(), style: bold, textAlign: pw.TextAlign.center),
      if ((store['address'] ?? '').toString().isNotEmpty) pw.Text(store['address'].toString(), style: small, textAlign: pw.TextAlign.center),
      if ((store['phone'] ?? '').toString().isNotEmpty) pw.Text('Tel. ${store['phone']}', style: small, textAlign: pw.TextAlign.center),
      pw.SizedBox(height: 4),
      pw.Text('${two(when.day)}/${two(when.month)}/${when.year} ${two(when.hour)}:${two(when.minute)}'
          '${sale['number'] != null ? '   Venta #${sale['number']}' : ''}', style: small, textAlign: pw.TextAlign.center),
      if (sale['cashier_name'] != null) pw.Text('Atendió: ${sale['cashier_name']}', style: small, textAlign: pw.TextAlign.center),
      pw.Text('Comprobante no válido como factura', style: small, textAlign: pw.TextAlign.center),
      pw.Divider(thickness: 0.5),
      for (final l in lines)
        pw.Padding(
          padding: const pw.EdgeInsets.symmetric(vertical: 1),
          child: pw.Row(crossAxisAlignment: pw.CrossAxisAlignment.start, children: [
            pw.Expanded(child: pw.Text('${l['quantity']} x ${l['name']}', style: normal)),
            pw.Text(money((l['total'] as num)), style: normal),
          ]),
        ),
      pw.Divider(thickness: 0.5),
      if (discount > 0 || pointsOff > 0) _row('Subtotal', money((sale['subtotal'] as num?) ?? total + discount + pointsOff), normal),
      if (discount > 0) _row('Descuento', '-${money(discount)}', normal),
      if (pointsOff > 0) _row('Puntos Trappi', '-${money(pointsOff)}', normal),
      _row('TOTAL', money(total), bold),
      _row('Pago', _method(sale['payment_method']), normal),
      if (paidWith != null) ...[
        _row('Recibido', money(paidWith), normal),
        _row('Vuelto', money(paidWith - total), normal),
      ],
      if (claim != null) ...[
        pw.SizedBox(height: 8),
        pw.Text('Sumá ${sale['points']} Puntos Trappi', style: bold, textAlign: pw.TextAlign.center),
        pw.Text('Escaneá el QR con tu celular', style: small, textAlign: pw.TextAlign.center),
        pw.SizedBox(height: 4),
        pw.Center(child: pw.BarcodeWidget(barcode: pw.Barcode.qrCode(), data: claim['url'].toString(), width: paper == 58 ? 90 : 110, height: paper == 58 ? 90 : 110)),
        pw.SizedBox(height: 3),
        pw.Text('Código: ${claim['code']}', style: normal, textAlign: pw.TextAlign.center),
        pw.Text('trappi.com.ar/puntos · un solo uso', style: small, textAlign: pw.TextAlign.center),
      ] else if (sale['pending'] == true) ...[
        pw.SizedBox(height: 6),
        pw.Text('Venta guardada sin internet. Pedí el QR de tus Puntos Trappi en caja.', style: small, textAlign: pw.TextAlign.center),
      ],
      pw.SizedBox(height: 8),
      pw.Text('¡Gracias por tu compra!', style: normal, textAlign: pw.TextAlign.center),
      pw.SizedBox(height: 10),
    ]),
  ));
  return doc.save();
}

pw.Widget _row(String a, String b, pw.TextStyle s) =>
    pw.Row(children: [pw.Expanded(child: pw.Text(a, style: s)), pw.Text(b, style: s)]);

String _method(Object? m) => switch (m) {
      'efectivo' => 'Efectivo',
      'mercadopago' => 'Mercado Pago',
      'transferencia' => 'Transferencia',
      _ => m?.toString() ?? '',
    };

/// Imprime directo en la impresora elegida (sin diálogo). Devuelve un error legible o null.
Future<String?> printTicket(Caja caja, Map<String, dynamic> sale) async {
  final p = (caja.local.config['printer'] as Map?)?.cast<String, dynamic>();
  if (p == null) return 'No hay impresora elegida. Elegila en Configuración (F12).';
  try {
    final bytes = await ticketPdf(caja.store, sale, paper: (caja.local.config['paper'] as int?) ?? 80);
    final ok = await Printing.directPrintPdf(printer: Printer(url: p['url'] as String, name: p['name'] as String?), onLayout: (_) async => bytes, name: 'Ticket Trappi');
    return ok ? null : 'La impresora no respondió.';
  } catch (e) {
    return 'No se pudo imprimir: $e';
  }
}
