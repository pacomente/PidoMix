import 'dart:typed_data';

import 'package:pdf/pdf.dart';
import 'package:pdf/widgets.dart' as pw;
import 'package:printing/printing.dart';

import 'caja.dart';

/// Lo que el ticket le pide a la impresora: el PDF y el tamaño real de la hoja (ancho del rollo × largo del contenido).
class TicketPdf {
  const TicketPdf(this.bytes, this.format);
  final Uint8List bytes;
  final PdfPageFormat format;
}

/// Las térmicas no imprimen unos milímetros en cada borde (en 80 mm imprimen ~72 mm, en 58 mm ~48 mm):
/// si el ticket usa ese borde, se cortan los importes, que van pegados a la derecha. Se deja 1 mm de aire de mas.
double safeSideMargin(int paper) => (paper == 58 ? 6 : 5) * PdfPageFormat.mm;

/// Ticket para impresora térmica (58 u 80 mm) con el QR de Puntos Trappi.
/// [extraMarginMm]: márgenes de más para impresoras que igual cortan (Configuración → Márgenes).
/// [minSideMargin]: el borde que la impresora dice que no imprime (si es más grande que el nuestro, manda ese).
Future<TicketPdf> ticketPdf(Map<String, dynamic> store, Map<String, dynamic> sale,
    {int paper = 80, int extraMarginMm = 0, double minSideMargin = 0}) async {
  final doc = pw.Document(title: 'Ticket Trappi');
  final side = [safeSideMargin(paper), minSideMargin].reduce((a, b) => a > b ? a : b) + extraMarginMm * PdfPageFormat.mm;
  // alto infinito: la hoja mide lo que mide el ticket (sin papel en blanco de más)
  final format = PdfPageFormat((paper == 58 ? 58 : 80) * PdfPageFormat.mm, double.infinity,
      marginLeft: side, marginRight: side, marginTop: 3 * PdfPageFormat.mm, marginBottom: 6 * PdfPageFormat.mm);
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
    pageFormat: format,
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
            pw.SizedBox(width: 4),
            pw.Text(money((l['total'] as num)), style: normal, softWrap: false),
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
  final bytes = await doc.save();
  // despues de armarlo, la pagina tiene el alto real del contenido
  return TicketPdf(bytes, doc.document.pdfPageList.pages.first.pageFormat);
}

pw.Widget _row(String a, String b, pw.TextStyle s) =>
    pw.Row(children: [pw.Expanded(child: pw.Text(a, style: s)), pw.SizedBox(width: 4), pw.Text(b, style: s, softWrap: false)]);

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
    final paper = (caja.local.config['paper'] as int?) ?? 80;
    final extra = (caja.local.config['margin_extra'] as int?) ?? 0;
    final ticket = await ticketPdf(caja.store, sale, paper: paper, extraMarginMm: extra);
    final ok = await Printing.directPrintPdf(
      printer: Printer(url: p['url'] as String, name: p['name'] as String?),
      name: 'Ticket Trappi',
      // el tamaño real del ticket (sin esto Windows lo manda como hoja A4 y la térmica lo recorta);
      // unos mm de alto de más por si se rehace con márgenes más grandes
      format: ticket.format.copyWith(height: ticket.format.height + 15 * PdfPageFormat.mm),
      onLayout: (printerFormat) async {
        // la impresora informa cuánto no imprime en los bordes: si es más que nuestro margen, se rehace el ticket
        final edge = [printerFormat.marginLeft, printerFormat.marginRight].reduce((a, b) => a > b ? a : b);
        if (edge + 0.5 * PdfPageFormat.mm <= safeSideMargin(paper)) return ticket.bytes;
        return (await ticketPdf(caja.store, sale, paper: paper, extraMarginMm: extra, minSideMargin: edge + PdfPageFormat.mm)).bytes;
      },
    );
    return ok ? null : 'La impresora no respondió.';
  } catch (e) {
    return 'No se pudo imprimir: $e';
  }
}
