// Dibuja las pantallas de la caja con letra real: si algo no entra (overflow) la prueba falla.
// Con PREVIEW_OUT=carpeta guarda las imágenes (para mirarlas sin una compu con Windows).
import 'dart:io';
import 'dart:ui' as ui;

import 'package:flutter/material.dart';
import 'package:flutter/rendering.dart';
import 'package:flutter/services.dart';
import 'package:flutter_test/flutter_test.dart';
import 'package:trappi_caja/caja.dart';
import 'package:trappi_caja/local.dart';
import 'package:trappi_caja/screens.dart';
import 'package:trappi_caja/theme.dart';

Future<void> _fonts() async {
  const dir = '/opt/flutter/bin/cache/artifacts/material_fonts';
  if (!Directory(dir).existsSync()) return;
  for (final family in ['Segoe UI', 'Roboto']) {  // los botones usan la letra por defecto (en Windows, Segoe UI)
    final f = FontLoader(family);
    for (final n in ['Roboto-Regular', 'Roboto-Medium', 'Roboto-Bold', 'Roboto-Black']) {
      f.addFont(File('$dir/$n.ttf').readAsBytes().then((b) => ByteData.view(b.buffer)));
    }
    await f.load();
  }
  final icons = FontLoader('MaterialIcons')..addFont(File('$dir/MaterialIcons-Regular.otf').readAsBytes().then((b) => ByteData.view(b.buffer)));
  await icons.load();
}

Caja _caja() {
  final local = Local.at(Directory.systemTemp.createTempSync('caja'));
  local.config = {
    'token': 'x',
    'kitchen': 'both',
    'me': {
      'store': {'id': 1, 'name': 'Burger Mix', 'address': 'Alsina 120'},
      'cashiers': [
        {'id': 1, 'name': 'Sofi', 'is_owner': false},
        {'id': 2, 'name': 'Dueño', 'is_owner': true},
      ],
      'methods': [
        {'id': 'efectivo', 'label': 'Efectivo'},
        {'id': 'mercadopago', 'label': 'Mercado Pago'},
        {'id': 'transferencia', 'label': 'Transferencia'},
      ],
      'points_pay': {'enabled': true},
      'free_discount_pct': 10,
      'bills': [20000, 10000, 2000, 1000, 500, 200, 100, 50, 20, 10],
      'delivery': {
        'enabled': true,
        'merchant_pays': false,
        'fixed': null,
        'zones': [
          {'id': 1, 'label': 'Hasta 2 km', 'cost': 900},
          {'id': 2, 'label': 'Hasta 5 km', 'cost': 1800},
        ],
      },
    },
  };
  final groups = [
    {'id': 1, 'name': 'Punto', 'required': true, 'min': 1, 'max': 1, 'options': [{'id': 10, 'name': 'Jugosa', 'price': 0}, {'id': 11, 'name': 'A punto', 'price': 0}, {'id': 12, 'name': 'Bien cocida', 'price': 0}]},
    {'id': 2, 'name': 'Extras', 'required': false, 'min': 0, 'max': 3, 'options': [{'id': 20, 'name': 'Cheddar', 'price': 800}, {'id': 21, 'name': 'Panceta', 'price': 1200}, {'id': 22, 'name': 'Huevo', 'price': 600}]},
  ];
  local.catalog = {
    'sections': [{'id': 1, 'name': 'Hamburguesas'}, {'id': 2, 'name': 'Pizzas'}, {'id': 3, 'name': 'Bebidas'}],
    'products': [
      {'id': 1, 'name': 'Hamburguesa Clásica', 'price': 9000, 'section_id': 1, 'groups': groups},
      {'id': 2, 'name': 'Hamburguesa Doble Bacon', 'price': 12500, 'section_id': 1, 'groups': groups},
      {'id': 3, 'name': 'Pizza Muzzarella', 'price': 11000, 'section_id': 2, 'groups': []},
      {'id': 4, 'name': 'Docena de empanadas', 'price': 15000, 'section_id': 2, 'groups': []},
      {'id': 5, 'name': 'Coca Cola 1,5 L', 'price': 4200, 'section_id': 3, 'groups': []},
      {'id': 6, 'name': 'Agua sin gas', 'price': 1800, 'section_id': 3, 'groups': [], 'stock': 0},
      {'id': 7, 'name': 'Papas fritas', 'price': 5200, 'section_id': 1, 'groups': []},
      {'id': 8, 'name': 'Combo Clásica + papas + bebida', 'price': 15900, 'section_id': 1, 'groups': []},
    ],
    'favorites': [8, 1, 3, 5, 4, 7],
  };
  final c = Caja(local)
    ..stage = Stage.sell
    ..cashier = {'id': 1, 'name': 'Sofi', 'is_owner': false}
    ..shift = {
      'shift_id': 1, 'sales': 37, 'total': 541300, 'opening_cash': 20000, 'expected_cash': 287500, 'cash_in': 5000, 'cash_out': 30000,
      'by_method': {
        'efectivo': {'label': 'Efectivo', 'count': 22, 'total': 292500},
        'mercadopago': {'label': 'Mercado Pago', 'count': 13, 'total': 220800},
        'transferencia': {'label': 'Transferencia', 'count': 2, 'total': 28000},
      },
      'movements': [
        {'label': 'Retiro', 'kind': 'retiro', 'amount': 30000, 'reason': 'Proveedor de pan'},
        {'label': 'Ingreso', 'kind': 'ingreso', 'amount': 5000, 'reason': 'Cambio del banco'},
      ],
    };
  return c;
}

void main() {
  final out = Platform.environment['PREVIEW_OUT'];
  final shot = GlobalKey();

  Future<void> save(WidgetTester t, String name) async {
    await t.pumpAndSettle();
    if (out == null) return;
    await t.runAsync(() async {
      final b = shot.currentContext!.findRenderObject()! as RenderRepaintBoundary;
      final img = await b.toImage(pixelRatio: 1);
      final png = await img.toByteData(format: ui.ImageByteFormat.png);
      File('$out/$name.png').writeAsBytesSync(png!.buffer.asUint8List());
    });
  }

  testWidgets('caja gastronómica: vender con opciones, cobrar mixto, teléfono, retiros y cierre', (t) async {
    await t.runAsync(_fonts);
    t.view.physicalSize = const Size(1366, 800);
    t.view.devicePixelRatio = 1;
    addTearDown(t.view.reset);
    final caja = _caja();
    await t.pumpWidget(RepaintBoundary(key: shot, child: MaterialApp(theme: trappiTheme(), debugShowCheckedModeBanner: false, home: SellScreen(caja: caja))));
    await t.pump();

    // una hamburguesa con opciones: se abren las opciones del menú
    await t.tap(find.text('Hamburguesa Clásica').first);
    await t.pumpAndSettle();
    expect(find.text('Punto'), findsOneWidget);
    await t.tap(find.widgetWithText(ChoiceChip, 'Jugosa'));
    await t.tap(find.widgetWithText(ChoiceChip, 'Cheddar  +\$ 800'));
    await t.tap(find.text('Sin cebolla').first);
    await t.pump();
    await save(t, '1-opciones');
    await t.tap(find.text('Agregar al ticket (Enter)'));
    await t.pumpAndSettle();
    expect(caja.cart.single.modifiersText, 'Jugosa, Cheddar');
    expect(caja.cart.single.note, 'Sin cebolla');
    caja.addProduct(caja.products.firstWhere((p) => p['id'] == 5));
    caja.addProduct(caja.products.firstWhere((p) => p['id'] == 7), quantity: 2);
    await t.enterText(find.widgetWithText(TextField, 'Nombre para llamarlo (opcional)'), 'Juan');
    caja.setService('llevar');
    await t.runAsync(caja.hold); // uno en espera (guarda en la compu: con tiempo real)
    caja.addProduct(caja.products.firstWhere((p) => p['id'] == 1), modifiers: [{'id': 10, 'name': 'Jugosa', 'price': 0}, {'id': 20, 'name': 'Cheddar', 'price': 800}], note: 'Sin cebolla');
    caja.addProduct(caja.products.firstWhere((p) => p['id'] == 5));
    caja.addProduct(caja.products.firstWhere((p) => p['id'] == 7), quantity: 2);
    caja.setCustomer('Juan');
    caja.setService('llevar');
    await t.pumpAndSettle();
    expect(find.text('Espera (1)'), findsOneWidget);
    await save(t, '2-vender');

    final ctx = t.element(find.byType(SellScreen));
    // cobrar: pago mixto
    showDialog(context: ctx, builder: (_) => ChargeDialog(caja: caja));
    await t.pumpAndSettle();
    await t.tap(find.text('Mixto'));
    await t.pumpAndSettle();
    final fields = find.descendant(of: find.byType(AlertDialog), matching: find.byType(TextField));
    await t.enterText(fields.at(0), '10000');
    await t.tap(find.text('Lo que falta').at(1));
    await t.pumpAndSettle();
    await t.enterText(fields.last, '20000');
    await save(t, '3-cobro-mixto');
    Navigator.of(ctx).pop();
    await t.pumpAndSettle();

    showDialog(context: ctx, builder: (_) => PhoneOrderDialog(caja: caja));
    await t.pumpAndSettle();
    await t.enterText(find.widgetWithText(TextField, 'Nombre'), 'Marta');
    await t.enterText(find.widgetWithText(TextField, 'Teléfono (WhatsApp)'), '291 455 6677');
    await t.enterText(find.widgetWithText(TextField, 'Dirección'), 'Alsina 123');
    await t.tap(find.textContaining('Hasta 2 km'));
    await save(t, '4-telefono');
    Navigator.of(ctx).pop();
    await t.pumpAndSettle();

    showDialog(context: ctx, builder: (_) => PhoneDoneDialog(order: {'id': 1482, 'total': 26300, 'shipping': 900, 'track_url': 'https://trappi.com.ar/pedido/1482?t=x', 'whatsapp_url': 'https://wa.me/5492914556677?text=Hola'}));
    await save(t, '5-telefono-listo');
    Navigator.of(ctx).pop();
    await t.pumpAndSettle();

    showDialog(context: ctx, builder: (_) => CashMovementDialog(caja: caja));
    await t.pumpAndSettle();
    final mv = find.descendant(of: find.byType(AlertDialog), matching: find.byType(TextField));
    await t.enterText(mv.at(0), '15000');
    await t.enterText(mv.at(1), 'Proveedor de bebidas');
    await save(t, '6-retiro');
    Navigator.of(ctx).pop();
    await t.pumpAndSettle();

    showDialog(context: ctx, builder: (_) => CloseShiftDialog(caja: caja));
    await t.pumpAndSettle();
    final counts = find.descendant(of: find.byType(AlertDialog), matching: find.byType(TextField));
    await t.enterText(counts.at(0), '10');
    await t.enterText(counts.at(1), '6');
    await t.enterText(counts.at(3), '25');
    await t.enterText(counts.at(4), '4');
    await save(t, '7-cierre-arqueo');
    Navigator.of(ctx).pop();
    await t.pumpAndSettle();

    showDialog(context: ctx, builder: (_) => HeldDialog(caja: caja));
    await save(t, '8-en-espera');
    await t.runAsync(() => caja.resume(0));
    Navigator.of(ctx).pop();
    await t.pumpAndSettle();
    expect(caja.customerName, 'Juan');
    expect(caja.held.length, 1); // el que estaba cargado pasó a espera
  });
}
