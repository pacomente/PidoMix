import 'dart:async';

import 'package:flutter/material.dart';
import 'package:window_manager/window_manager.dart';

import 'caja.dart';
import 'local.dart';
import 'screens.dart';
import 'theme.dart';

/// Trappi Caja: punto de venta para Windows. Corre a pantalla completa (modo kiosco):
/// para salir hay que poner el PIN de un dueño.
Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  await windowManager.ensureInitialized();
  const kiosk = bool.fromEnvironment('KIOSK', defaultValue: true);
  await windowManager.waitUntilReadyToShow(
    const WindowOptions(title: 'Trappi Caja', minimumSize: Size(1100, 680), backgroundColor: Color(0xFFF5F2FA)),
    () async {
      if (kiosk) {
        await windowManager.setFullScreen(true);
        await windowManager.setPreventClose(true);
      } else {
        await windowManager.maximize();
      }
      await windowManager.show();
      await windowManager.focus();
    },
  );
  final local = await Local.open();
  final caja = Caja(local);
  runApp(TrappiCaja(caja: caja));
  unawaited(caja.start());
}

final navigatorKey = GlobalKey<NavigatorState>();

class TrappiCaja extends StatefulWidget {
  const TrappiCaja({super.key, required this.caja});
  final Caja caja;

  @override
  State<TrappiCaja> createState() => _TrappiCajaState();
}

class _TrappiCajaState extends State<TrappiCaja> with WindowListener {
  bool _asking = false;

  @override
  void initState() {
    super.initState();
    windowManager.addListener(this);
  }

  @override
  void dispose() {
    windowManager.removeListener(this);
    super.dispose();
  }

  /// Alt+F4 o cerrar: se pide el PIN de un dueño (si la caja no está vinculada, se sale directo).
  @override
  Future<void> onWindowClose() async {
    if (_asking) return;
    final ctx = navigatorKey.currentContext;
    if (widget.caja.api.deviceToken == null || ctx == null) {
      await windowManager.destroy();
      return;
    }
    _asking = true;
    final token = await askOwner(ctx, widget.caja, 'Salir de Trappi Caja');
    _asking = false;
    if (token != null) await windowManager.destroy();
  }

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      navigatorKey: navigatorKey,
      title: 'Trappi Caja',
      debugShowCheckedModeBanner: false,
      theme: trappiTheme(),
      home: ListenableBuilder(
        listenable: widget.caja,
        builder: (context, _) => switch (widget.caja.stage) {
          Stage.loading => const Scaffold(body: Center(child: CircularProgressIndicator())),
          Stage.link => LinkScreen(caja: widget.caja),
          Stage.cashier => CashierScreen(caja: widget.caja),
          Stage.openShift => OpenShiftScreen(caja: widget.caja),
          Stage.sell => SellScreen(caja: widget.caja),
        },
      ),
    );
  }
}
