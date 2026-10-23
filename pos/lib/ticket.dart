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

/// Hoja del ancho del rollo y alto infinito (mide lo que mide el ticket, sin papel en blanco de más).
PdfPageFormat _format(int paper, int extraMarginMm, double minSideMargin) {
  final side = [safeSideMargin(paper), minSideMargin].reduce((a, b) => a > b ? a : b) + extraMarginMm * PdfPageFormat.mm;
  return PdfPageFormat((paper == 58 ? 58 : 80) * PdfPageFormat.mm, double.infinity,
      marginLeft: side, marginRight: side, marginTop: 3 * PdfPageFormat.mm, marginBottom: 6 * PdfPageFormat.mm);
}

Future<TicketPdf> _done(pw.Document doc) async {
  final bytes = await doc.save();
  // despues de armarlo, la pagina tiene el alto real del contenido
  return TicketPdf(bytes, doc.document.pdfPageList.pages.first.pageFormat);
}

/// "Pedido 23 · Juan" (como se lo llama al mostrador).
String callLabel(Map<String, dynamic> sale) =>
    [if (sale['call_number'] != null) 'Pedido ${sale['call_number']}', if ((sale['customer_name'] ?? '').toString().isNotEmpty) sale['customer_name']].join(' · ');

const services = {'aca': 'Para comer acá', 'llevar': 'Para llevar'};

/// Ticket para impresora térmica (58 u 80 mm) con el QR de Puntos Trappi.
/// [extraMarginMm]: márgenes de más para impresoras que igual cortan (Configuración → Márgenes).
/// [minSideMargin]: el borde que la impresora dice que no imprime (si es más grande que el nuestro, manda ese).
Future<TicketPdf> ticketPdf(Map<String, dynamic> store, Map<String, dynamic> sale,
    {int paper = 80, int extraMarginMm = 0, double minSideMargin = 0}) async {
  final doc = pw.Document(title: 'Ticket Trappi');
  final format = _format(paper, extraMarginMm, minSideMargin);
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
  final payments = ((sale['payments'] as List?) ?? []).cast<Map>();
  final cashPart = sale['payment_method'] == 'mixto'
      ? ((sale['cash_part'] as num?) ?? (payments.firstWhere((p) => p['method'] == 'efectivo', orElse: () => {})['amount'] as num?))?.toDouble()
      : total;
  final call = callLabel(sale);
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
      if (call.isNotEmpty) ...[
        pw.SizedBox(height: 4),
        pw.Text(call, style: pw.TextStyle(fontSize: paper == 58 ? 14 : 17, fontWeight: pw.FontWeight.bold), textAlign: pw.TextAlign.center),
      ],
      if (services[sale['service']] != null) pw.Text(services[sale['service']]!, style: normal, textAlign: pw.TextAlign.center),
      pw.Divider(thickness: 0.5),
      for (final l in lines)
        pw.Padding(
          padding: const pw.EdgeInsets.symmetric(vertical: 1),
          child: pw.Column(crossAxisAlignment: pw.CrossAxisAlignment.stretch, children: [
            pw.Row(crossAxisAlignment: pw.CrossAxisAlignment.start, children: [
              pw.Expanded(child: pw.Text('${l['quantity']} x ${l['name']}', style: normal)),
              pw.SizedBox(width: 4),
              pw.Text(money((l['total'] as num)), style: normal, softWrap: false),
            ]),
            if ((l['modifiers_text'] ?? '').toString().isNotEmpty) pw.Text('   + ${l['modifiers_text']}', style: small),
            if ((l['note'] ?? '').toString().isNotEmpty) pw.Text('   * ${l['note']}', style: small),
          ]),
        ),
      pw.Divider(thickness: 0.5),
      if (discount > 0 || pointsOff > 0) _row('Subtotal', money((sale['subtotal'] as num?) ?? total + discount + pointsOff), normal),
      if (discount > 0) _row('Descuento', '-${money(discount)}', normal),
      if (pointsOff > 0) _row('Puntos Trappi', '-${money(pointsOff)}', normal),
      _row('TOTAL', money(total), bold),
      if (sale['payment_method'] == 'mixto')
        for (final p in payments) _row('Pago ${_method(p['method'])}', money((p['amount'] as num)), normal)
      else
        _row('Pago', _method(sale['payment_method']), normal),
      if (paidWith != null && cashPart != null) ...[
        _row('Recibido', money(paidWith), normal),
        _row('Vuelto', money(paidWith - cashPart), normal),
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
  return _done(doc);
}

/// Comanda para la cocina: sin precios, letra grande, con las opciones y aclaraciones.
Future<TicketPdf> kitchenPdf(Map<String, dynamic> sale, {int paper = 80, int extraMarginMm = 0, double minSideMargin = 0, String title = 'COMANDA'}) async {
  final doc = pw.Document(title: 'Comanda Trappi');
  final big = pw.TextStyle(fontSize: paper == 58 ? 12 : 14, fontWeight: pw.FontWeight.bold);
  final normal = pw.TextStyle(fontSize: paper == 58 ? 9 : 11);
  final huge = pw.TextStyle(fontSize: paper == 58 ? 18 : 24, fontWeight: pw.FontWeight.bold);
  final lines = ((sale['lines'] ?? sale['items']) as List).cast<Map>();
  final when = DateTime.tryParse((sale['sold_at'] ?? '').toString())?.toLocal() ?? DateTime.now();
  final call = callLabel(sale);
  String two(int v) => v.toString().padLeft(2, '0');
  doc.addPage(pw.Page(
    pageFormat: _format(paper, extraMarginMm, minSideMargin),
    build: (_) => pw.Column(crossAxisAlignment: pw.CrossAxisAlignment.stretch, children: [
      pw.Text(title, style: big, textAlign: pw.TextAlign.center),
      if (call.isNotEmpty) pw.Text(call, style: huge, textAlign: pw.TextAlign.center),
      pw.Text([
        '${two(when.hour)}:${two(when.minute)}',
        if (services[sale['service']] != null) services[sale['service']],
        if (sale['delivery'] != null) sale['delivery'],
      ].join('  ·  '), style: normal, textAlign: pw.TextAlign.center),
      pw.Divider(thickness: 1),
      for (final l in lines)
        pw.Padding(
          padding: const pw.EdgeInsets.symmetric(vertical: 3),
          child: pw.Column(crossAxisAlignment: pw.CrossAxisAlignment.stretch, children: [
            pw.Text('${l['quantity']}  ${l['name']}', style: big),
            if ((l['modifiers_text'] ?? '').toString().isNotEmpty) pw.Text('   + ${l['modifiers_text']}', style: normal),
            if ((l['note'] ?? '').toString().isNotEmpty) pw.Text('   >> ${l['note']}', style: big),
          ]),
        ),
      if ((sale['notes'] ?? '').toString().isNotEmpty) ...[pw.Divider(thickness: 0.5), pw.Text('Nota: ${sale['notes']}', style: big)],
      pw.SizedBox(height: 12),
    ]),
  ));
  return _done(doc);
}

/// Ticket del cierre de caja: ventas por medio de pago, retiros e ingresos, anuladas, arqueo y diferencia.
Future<TicketPdf> closePdf(Map<String, dynamic> store, Map<String, dynamic> s, {int paper = 80, int extraMarginMm = 0, double minSideMargin = 0}) async {
  final doc = pw.Document(title: 'Cierre de caja');
  final small = pw.TextStyle(fontSize: paper == 58 ? 7 : 8);
  final normal = pw.TextStyle(fontSize: paper == 58 ? 8 : 9);
  final bold = pw.TextStyle(fontSize: paper == 58 ? 10 : 12, fontWeight: pw.FontWeight.bold);
  final by = ((s['by_method'] as Map?) ?? {}).cast<String, dynamic>();
  final moves = ((s['movements'] as List?) ?? []).cast<Map>();
  final bills = ((s['bills'] as Map?) ?? {}).cast<String, dynamic>();
  String fmt(Object? iso) {
    final d = DateTime.tryParse((iso ?? '').toString())?.toLocal();
    if (d == null) return '';
    String two(int v) => v.toString().padLeft(2, '0');
    return '${two(d.day)}/${two(d.month)} ${two(d.hour)}:${two(d.minute)}';
  }

  final diff = ((s['difference'] as num?) ?? 0).toDouble();
  doc.addPage(pw.Page(
    pageFormat: _format(paper, extraMarginMm, minSideMargin),
    build: (_) => pw.Column(crossAxisAlignment: pw.CrossAxisAlignment.stretch, children: [
      pw.Text((store['name'] ?? 'Comercio').toString(), style: bold, textAlign: pw.TextAlign.center),
      pw.Text('CIERRE DE CAJA', style: bold, textAlign: pw.TextAlign.center),
      pw.Text('${fmt(s['opened_at'])} a ${fmt(s['closed_at'])}', style: small, textAlign: pw.TextAlign.center),
      if (s['closed_by'] != null) pw.Text('Cerró: ${s['closed_by']}', style: small, textAlign: pw.TextAlign.center),
      pw.Divider(thickness: 0.5),
      _row('Ventas', '${s['sales']}', normal),
      for (final m in by.values) _row('  ${m['label']} (${m['count']})', money((m['total'] as num)), normal),
      _row('Total vendido', money((s['total'] as num)), bold),
      if (((s['discounts'] as num?) ?? 0) > 0) _row('Descuentos', money((s['discounts'] as num)), normal),
      if (((s['voided'] as num?) ?? 0) > 0) _row('Anuladas (${s['voided']})', money(((s['voided_total'] as num?) ?? 0)), normal),
      pw.Divider(thickness: 0.5),
      _row('Fondo inicial', money((s['opening_cash'] as num)), normal),
      _row('+ Ventas en efectivo', money(((by['efectivo'] as Map?)?['total'] as num?) ?? 0), normal),
      if (((s['cash_in'] as num?) ?? 0) > 0) _row('+ Ingresos', money((s['cash_in'] as num)), normal),
      if (((s['cash_out'] as num?) ?? 0) > 0) _row('- Retiros', money((s['cash_out'] as num)), normal),
      for (final m in moves) pw.Text('   ${m['label']} ${money((m['amount'] as num))} · ${m['reason']}', style: small),
      _row('Efectivo esperado', money((s['expected_cash'] as num)), bold),
      if (bills.isNotEmpty) ...[
        pw.SizedBox(height: 3),
        for (final e in bills.entries)
          _row(e.key == 'monedas' ? '  Monedas' : '  ${e.value} x ${money(int.parse(e.key))}', e.key == 'monedas' ? money((e.value as num)) : money(int.parse(e.key) * (e.value as num)), small),
      ],
      _row('Efectivo contado', money(((s['counted_cash'] as num?) ?? 0)), bold),
      _row(diff.abs() < 0.01 ? 'Cierra justa' : (diff > 0 ? 'Sobran' : 'Faltan'), money(diff.abs()), bold),
      pw.SizedBox(height: 6),
      pw.Text('Puntos Trappi: ${s['points'] ?? 0} en ${s['qr_total'] ?? 0} QR', style: small, textAlign: pw.TextAlign.center),
      pw.SizedBox(height: 10),
    ]),
  ));
  return _done(doc);
}

pw.Widget _row(String a, String b, pw.TextStyle s) =>
    pw.Row(children: [pw.Expanded(child: pw.Text(a, style: s)), pw.SizedBox(width: 4), pw.Text(b, style: s, softWrap: false)]);

String _method(Object? m) => switch (m) {
      'efectivo' => 'Efectivo',
      'mercadopago' => 'Mercado Pago',
      'transferencia' => 'Transferencia',
      'mixto' => 'Mixto',
      _ => m?.toString() ?? '',
    };

/// Imprime directo en la impresora elegida (sin diálogo). Devuelve un error legible o null.
Future<String?> printTicket(Caja caja, Map<String, dynamic> sale) {
  final paper = (caja.local.config['paper'] as int?) ?? 80;
  final extra = (caja.local.config['margin_extra'] as int?) ?? 0;
  return _print(caja, (caja.local.config['printer'] as Map?)?.cast<String, dynamic>(), paper,
      (minSide) => ticketPdf(caja.store, sale, paper: paper, extraMarginMm: extra, minSideMargin: minSide));
}

/// La comanda va a la impresora de la cocina (si se eligió una) o a la de tickets.
Future<String?> printKitchen(Caja caja, Map<String, dynamic> sale, {String title = 'COMANDA'}) {
  final paper = (caja.local.config['paper'] as int?) ?? 80;
  final extra = (caja.local.config['margin_extra'] as int?) ?? 0;
  final printer = ((caja.local.config['kitchen_printer'] ?? caja.local.config['printer']) as Map?)?.cast<String, dynamic>();
  return _print(caja, printer, paper, (minSide) => kitchenPdf(sale, paper: paper, extraMarginMm: extra, minSideMargin: minSide, title: title));
}

Future<String?> printClose(Caja caja, Map<String, dynamic> summary) {
  final paper = (caja.local.config['paper'] as int?) ?? 80;
  final extra = (caja.local.config['margin_extra'] as int?) ?? 0;
  return _print(caja, (caja.local.config['printer'] as Map?)?.cast<String, dynamic>(), paper,
      (minSide) => closePdf(caja.store, summary, paper: paper, extraMarginMm: extra, minSideMargin: minSide));
}

Future<String?> _print(Caja caja, Map<String, dynamic>? p, int paper, Future<TicketPdf> Function(double minSide) build) async {
  if (p == null) return 'No hay impresora elegida. Elegila en Configuración (F12).';
  try {
    final ticket = await build(0);
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
        return (await build(edge + PdfPageFormat.mm)).bytes;
      },
    );
    return ok ? null : 'La impresora no respondió.';
  } catch (e) {
    return 'No se pudo imprimir: $e';
  }
}
