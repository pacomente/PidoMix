import 'dart:async';

import 'package:flutter/material.dart';
import 'package:flutter/services.dart';
import 'package:printing/printing.dart';
import 'package:qr_flutter/qr_flutter.dart';
import 'package:window_manager/window_manager.dart';

import 'api.dart';
import 'caja.dart';
import 'theme.dart';
import 'ticket.dart';

// ---------------------------------------------------------------- comunes

void toast(BuildContext context, String text, {bool error = false}) {
  ScaffoldMessenger.of(context)
    ..hideCurrentSnackBar()
    ..showSnackBar(SnackBar(
      content: Text(text, style: const TextStyle(fontSize: 15)),
      backgroundColor: error ? red : dark,
      behavior: SnackBarBehavior.floating,
      width: 520,
      duration: Duration(seconds: error ? 5 : 2),
    ));
}

Widget logo({double size = 22, bool onDark = true}) => Row(mainAxisSize: MainAxisSize.min, children: [
      Container(
        width: size * 1.5,
        height: size * 1.5,
        alignment: Alignment.center,
        decoration: BoxDecoration(color: violet, borderRadius: BorderRadius.circular(size * .4)),
        child: Text('T', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w900, fontSize: size)),
      ),
      SizedBox(width: size * .45),
      Text('Trappi Caja', style: TextStyle(fontWeight: FontWeight.w800, fontSize: size, color: onDark ? Colors.white : ink)),
    ]);

class Kbd extends StatelessWidget {
  const Kbd(this.text, {super.key, this.light = false});
  final String text;
  final bool light;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 6, vertical: 2),
        decoration: BoxDecoration(
          color: light ? Colors.white24 : violetSoft,
          borderRadius: BorderRadius.circular(6),
          border: Border.all(color: light ? Colors.white38 : line),
        ),
        child: Text(text, style: TextStyle(fontSize: 12, fontWeight: FontWeight.w700, color: light ? Colors.white : violetDark)),
      );
}

/// Caja de texto para montos: Enter confirma.
class MoneyField extends StatelessWidget {
  const MoneyField({super.key, required this.controller, this.label, this.onSubmit, this.autofocus = true, this.onChanged});
  final TextEditingController controller;
  final String? label;
  final VoidCallback? onSubmit;
  final bool autofocus;
  final ValueChanged<String>? onChanged;
  @override
  Widget build(BuildContext context) => TextField(
        controller: controller,
        autofocus: autofocus,
        style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800),
        keyboardType: const TextInputType.numberWithOptions(decimal: true),
        inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]'))],
        decoration: InputDecoration(labelText: label, prefixText: '\$ '),
        onChanged: onChanged,
        onSubmitted: (_) => onSubmit?.call(),
      );
}

/// Pide el PIN de un dueño y devuelve su token (o null si se cancela).
Future<String?> askOwner(BuildContext context, Caja caja, String title) async {
  final owners = caja.cashiers.where((c) => c['is_owner'] == true).toList();
  if (owners.isEmpty) {
    toast(context, 'No hay ningún dueño cargado. Crealo en el panel: Caja (punto de venta).', error: true);
    return null;
  }
  return showDialog<String>(context: context, builder: (_) => _OwnerDialog(caja: caja, title: title, owners: owners));
}

class _OwnerDialog extends StatefulWidget {
  const _OwnerDialog({required this.caja, required this.title, required this.owners});
  final Caja caja;
  final String title;
  final List<Map<String, dynamic>> owners;
  @override
  State<_OwnerDialog> createState() => _OwnerDialogState();
}

class _OwnerDialogState extends State<_OwnerDialog> {
  late int owner = (widget.caja.isOwner ? widget.caja.cashier!['id'] : widget.owners.first['id']) as int;
  final pin = TextEditingController();
  String? error;
  bool busy = false;

  Future<void> go() async {
    if (busy) return;
    setState(() => busy = true);
    try {
      final t = await widget.caja.ownerToken(owner, pin.text.trim());
      if (mounted) Navigator.pop(context, t);
    } on ApiError catch (e) {
      setState(() {
        error = e.offline ? 'Hace falta internet para validar el PIN del dueño.' : e.message;
        busy = false;
        pin.clear();
      });
    }
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: Text(widget.title),
        content: SizedBox(
          width: 380,
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            const Text('Necesita la autorización de un dueño.', style: TextStyle(color: muted)),
            const SizedBox(height: 14),
            DropdownButtonFormField<int>(
              initialValue: owner,
              decoration: const InputDecoration(labelText: 'Dueño'),
              items: [for (final o in widget.owners) DropdownMenuItem(value: o['id'] as int, child: Text(o['name'].toString()))],
              onChanged: (v) => setState(() => owner = v ?? owner),
            ),
            const SizedBox(height: 12),
            TextField(
              controller: pin,
              autofocus: true,
              obscureText: true,
              maxLength: 6,
              keyboardType: TextInputType.number,
              inputFormatters: [FilteringTextInputFormatter.digitsOnly],
              style: const TextStyle(fontSize: 24, letterSpacing: 8),
              decoration: const InputDecoration(labelText: 'PIN', counterText: ''),
              onSubmitted: (_) => go(),
            ),
            if (error != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(error!, style: const TextStyle(color: red))),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancelar (Esc)')),
          FilledButton(onPressed: busy ? null : go, child: const Text('Autorizar')),
        ],
      );
}

// ---------------------------------------------------------------- vincular

class LinkScreen extends StatefulWidget {
  const LinkScreen({super.key, required this.caja});
  final Caja caja;
  @override
  State<LinkScreen> createState() => _LinkScreenState();
}

class _LinkScreenState extends State<LinkScreen> {
  final email = TextEditingController();
  final password = TextEditingController();
  String? error;
  bool busy = false;

  Future<void> go() async {
    setState(() {
      busy = true;
      error = null;
    });
    try {
      await widget.caja.link(email.text.trim(), password.text);
    } on ApiError catch (e) {
      if (mounted) setState(() => error = e.message);
    } finally {
      password.clear();
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Row(children: [
          Expanded(
            child: Container(
              color: dark,
              padding: const EdgeInsets.all(56),
              child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                logo(size: 26),
                const Spacer(),
                const Text('Vendé en el mostrador\ny sumale puntos a tus clientes.',
                    style: TextStyle(color: Colors.white, fontSize: 38, fontWeight: FontWeight.w800, height: 1.15)),
                const SizedBox(height: 18),
                const Text('Cada venta imprime un QR de Puntos Trappi. El cliente lo escanea y los puntos quedan en su cuenta.',
                    style: TextStyle(color: Colors.white70, fontSize: 17)),
                const Spacer(),
                const Text('Funciona sin internet: las ventas se guardan y se suben solas.', style: TextStyle(color: Colors.white54)),
              ]),
            ),
          ),
          Expanded(
            child: Center(
              child: SizedBox(
                width: 420,
                child: AutofillGroup(
                  child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                    const Text('Vincular esta compu', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800)),
                    const SizedBox(height: 8),
                    const Text('Entrá con el usuario de tu local en Trappi (el mismo del panel). Se hace una sola vez.', style: TextStyle(color: muted)),
                    const SizedBox(height: 24),
                    TextField(controller: email, autofocus: true, decoration: const InputDecoration(labelText: 'Email'), onSubmitted: (_) => go()),
                    const SizedBox(height: 12),
                    TextField(controller: password, obscureText: true, decoration: const InputDecoration(labelText: 'Contraseña'), onSubmitted: (_) => go()),
                    if (error != null) Padding(padding: const EdgeInsets.only(top: 12), child: Text(error!, style: const TextStyle(color: red))),
                    const SizedBox(height: 20),
                    FilledButton(onPressed: busy ? null : go, child: Text(busy ? 'Vinculando…' : 'Vincular caja')),
                    const SizedBox(height: 14),
                    const Text('La contraseña no se guarda en la compu: Trappi le da a la caja una llave propia que podés anular desde el panel.',
                        style: TextStyle(color: muted, fontSize: 13)),
                  ]),
                ),
              ),
            ),
          ),
        ]),
      );
}

// ---------------------------------------------------------------- cajero (PIN)

class CashierScreen extends StatefulWidget {
  const CashierScreen({super.key, required this.caja});
  final Caja caja;
  @override
  State<CashierScreen> createState() => _CashierScreenState();
}

class _CashierScreenState extends State<CashierScreen> {
  Map<String, dynamic>? chosen;
  String pin = '';
  String? error;
  bool busy = false;
  final focus = FocusNode();

  Future<void> submit() async {
    if (chosen == null || pin.length < 4 || busy) return;
    setState(() => busy = true);
    try {
      await widget.caja.login(chosen!['id'] as int, pin);
    } on ApiError catch (e) {
      if (mounted) {
        setState(() {
          error = e.offline ? 'Sin internet no se puede entrar. Revisá la conexión.' : e.message;
          pin = '';
        });
      }
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  void key(String k) {
    setState(() {
      error = null;
      if (k == '<') {
        if (pin.isNotEmpty) pin = pin.substring(0, pin.length - 1);
      } else if (pin.length < 6) {
        pin += k;
      }
    });
  }

  KeyEventResult onKey(FocusNode _, KeyEvent e) {
    if (e is! KeyDownEvent || chosen == null) return KeyEventResult.ignored;
    final c = e.character;
    if (c != null && RegExp(r'^\d$').hasMatch(c)) {
      key(c);
      return KeyEventResult.handled;
    }
    if (e.logicalKey == LogicalKeyboardKey.backspace) {
      key('<');
      return KeyEventResult.handled;
    }
    if (e.logicalKey == LogicalKeyboardKey.enter || e.logicalKey == LogicalKeyboardKey.numpadEnter) {
      submit();
      return KeyEventResult.handled;
    }
    if (e.logicalKey == LogicalKeyboardKey.escape) {
      setState(() => chosen = null);
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  @override
  Widget build(BuildContext context) {
    final caja = widget.caja;
    final list = caja.cashiers;
    return Scaffold(
      body: Focus(
        focusNode: focus,
        autofocus: true,
        onKeyEvent: onKey,
        child: Column(children: [
          _TopBar(caja: caja, simple: true),
          Expanded(
            child: Center(
              child: chosen == null
                  ? Column(mainAxisSize: MainAxisSize.min, children: [
                      Text(caja.store['name']?.toString() ?? '', style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w800)),
                      const SizedBox(height: 6),
                      const Text('¿Quién atiende?', style: TextStyle(fontSize: 18, color: muted)),
                      const SizedBox(height: 28),
                      if (list.isEmpty)
                        const SizedBox(
                          width: 480,
                          child: Text('Todavía no hay cajeros. Crealos en el panel de Trappi, en "Caja (punto de venta)", y tocá Actualizar.',
                              textAlign: TextAlign.center, style: TextStyle(fontSize: 16)),
                        ),
                      Wrap(spacing: 16, runSpacing: 16, alignment: WrapAlignment.center, children: [
                        for (final c in list)
                          InkWell(
                            borderRadius: BorderRadius.circular(18),
                            onTap: () => setState(() {
                              chosen = c;
                              pin = '';
                              error = null;
                              focus.requestFocus();
                            }),
                            child: Container(
                              width: 170,
                              height: 164,
                              padding: const EdgeInsets.symmetric(vertical: 24),
                              decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(18), border: Border.all(color: line)),
                              child: Column(children: [
                                CircleAvatar(
                                  radius: 30,
                                  backgroundColor: violetSoft,
                                  child: Text(c['name'].toString().characters.first.toUpperCase(),
                                      style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800, color: violet)),
                                ),
                                const SizedBox(height: 12),
                                Text(c['name'].toString(), style: const TextStyle(fontWeight: FontWeight.w700, fontSize: 16)),
                                if (c['is_owner'] == true) const Text('Dueño', style: TextStyle(color: muted, fontSize: 13)),
                              ]),
                            ),
                          ),
                      ]),
                      const SizedBox(height: 28),
                      OutlinedButton.icon(onPressed: caja.refresh, icon: const Icon(Icons.refresh), label: const Text('Actualizar')),
                    ])
                  : SizedBox(
                      width: 340,
                      child: Column(mainAxisSize: MainAxisSize.min, children: [
                        Text('Hola, ${chosen!['name']}', style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800)),
                        const SizedBox(height: 4),
                        const Text('Poné tu PIN', style: TextStyle(color: muted)),
                        const SizedBox(height: 20),
                        Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                          for (var i = 0; i < 6; i++)
                            Container(
                              margin: const EdgeInsets.all(6),
                              width: 16,
                              height: 16,
                              decoration: BoxDecoration(
                                shape: BoxShape.circle,
                                color: i < pin.length ? violet : Colors.white,
                                border: Border.all(color: i < pin.length ? violet : line, width: 2),
                              ),
                            ),
                        ]),
                        SizedBox(height: 26, child: error == null ? null : Text(error!, style: const TextStyle(color: red))),
                        GridView.count(
                          shrinkWrap: true,
                          crossAxisCount: 3,
                          mainAxisSpacing: 10,
                          crossAxisSpacing: 10,
                          childAspectRatio: 1.5,
                          children: [
                            for (final k in ['1', '2', '3', '4', '5', '6', '7', '8', '9', '<', '0', 'OK'])
                              FilledButton.tonal(
                                onPressed: busy ? null : () => k == 'OK' ? submit() : key(k),
                                style: FilledButton.styleFrom(
                                  backgroundColor: k == 'OK' ? violet : Colors.white,
                                  foregroundColor: k == 'OK' ? Colors.white : ink,
                                  shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14), side: const BorderSide(color: line)),
                                ),
                                child: k == '<' ? const Icon(Icons.backspace_outlined) : Text(k, style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w700)),
                              ),
                          ],
                        ),
                        const SizedBox(height: 16),
                        TextButton(onPressed: () => setState(() => chosen = null), child: const Text('Volver (Esc)')),
                      ]),
                    ),
            ),
          ),
        ]),
      ),
    );
  }
}

// ---------------------------------------------------------------- abrir caja

class OpenShiftScreen extends StatefulWidget {
  const OpenShiftScreen({super.key, required this.caja});
  final Caja caja;
  @override
  State<OpenShiftScreen> createState() => _OpenShiftScreenState();
}

class _OpenShiftScreenState extends State<OpenShiftScreen> {
  final amount = TextEditingController(text: '0');
  String? error;
  bool busy = false;

  Future<void> go() async {
    final v = parseMoney(amount.text) ?? -1;
    if (v < 0) {
      setState(() => error = 'Poné el efectivo con el que arranca la caja.');
      return;
    }
    setState(() => busy = true);
    try {
      await widget.caja.openShift(v);
    } on ApiError catch (e) {
      if (mounted) setState(() => error = e.offline ? 'Hace falta internet para abrir la caja.' : e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) => Scaffold(
        body: Column(children: [
          _TopBar(caja: widget.caja, simple: true),
          Expanded(
            child: Center(
              child: SizedBox(
                width: 420,
                child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                  const Text('Abrir la caja', style: TextStyle(fontSize: 28, fontWeight: FontWeight.w800)),
                  const SizedBox(height: 6),
                  const Text('¿Con cuánto efectivo arranca? (el cambio que hay en el cajón)', style: TextStyle(color: muted)),
                  const SizedBox(height: 20),
                  MoneyField(controller: amount, label: 'Fondo inicial', onSubmit: go),
                  if (error != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(error!, style: const TextStyle(color: red))),
                  const SizedBox(height: 18),
                  FilledButton(onPressed: busy ? null : go, child: const Text('Abrir caja (Enter)')),
                  const SizedBox(height: 10),
                  TextButton(onPressed: widget.caja.logout, child: const Text('Cambiar de cajero')),
                ]),
              ),
            ),
          ),
        ]),
      );
}

// ---------------------------------------------------------------- barra superior

class _TopBar extends StatelessWidget {
  const _TopBar({required this.caja, this.simple = false, this.onSettings});
  final Caja caja;
  final bool simple;
  final VoidCallback? onSettings;

  @override
  Widget build(BuildContext context) {
    final s = caja.shift;
    return Container(
      color: dark,
      padding: const EdgeInsets.symmetric(horizontal: 20, vertical: 12),
      child: Row(children: [
        logo(size: 18),
        const SizedBox(width: 18),
        Text(caja.store['name']?.toString() ?? '', style: const TextStyle(color: Colors.white70, fontSize: 15)),
        const Spacer(),
        if (caja.notice != null)
          Flexible(
            flex: 3,
            child: Container(
              padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 6),
              decoration: BoxDecoration(color: caja.online ? yellow : const Color(0xFFFFE4E1), borderRadius: BorderRadius.circular(20)),
              child: Text(caja.notice!, overflow: TextOverflow.ellipsis, style: const TextStyle(color: ink, fontWeight: FontWeight.w600, fontSize: 13)),
            ),
          ),
        const SizedBox(width: 14),
        _Pill(icon: caja.online ? Icons.wifi : Icons.wifi_off, text: caja.online ? 'En línea' : 'Sin internet', ok: caja.online),
        if (caja.pendingCount > 0) ...[
          const SizedBox(width: 8),
          _Pill(icon: Icons.cloud_upload_outlined, text: '${caja.pendingCount} por subir', ok: false),
        ],
        if (!simple && s != null) ...[
          const SizedBox(width: 8),
          _Pill(icon: Icons.point_of_sale, text: 'Caja: ${money((s['total'] as num?) ?? 0)} · ${s['sales']} ventas', ok: true),
        ],
        if (caja.cashier != null) ...[
          const SizedBox(width: 14),
          const Icon(Icons.person_outline, color: Colors.white70, size: 18),
          const SizedBox(width: 4),
          Text(caja.cashier!['name'].toString(), style: const TextStyle(color: Colors.white, fontWeight: FontWeight.w600)),
        ],
        if (onSettings != null) ...[
          const SizedBox(width: 10),
          TextButton.icon(
            onPressed: onSettings,
            icon: const Icon(Icons.settings_outlined, color: Colors.white70, size: 18),
            label: const Kbd('F12', light: true),
          ),
        ],
      ]),
    );
  }
}

class _Pill extends StatelessWidget {
  const _Pill({required this.icon, required this.text, required this.ok});
  final IconData icon;
  final String text;
  final bool ok;
  @override
  Widget build(BuildContext context) => Container(
        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 5),
        decoration: BoxDecoration(color: ok ? Colors.white10 : const Color(0x33FFD60A), borderRadius: BorderRadius.circular(20)),
        child: Row(mainAxisSize: MainAxisSize.min, children: [
          Icon(icon, size: 15, color: ok ? const Color(0xFF6EE7B7) : yellow),
          const SizedBox(width: 6),
          Text(text, style: const TextStyle(color: Colors.white, fontSize: 13)),
        ]),
      );
}

// ---------------------------------------------------------------- vender

class SellScreen extends StatefulWidget {
  const SellScreen({super.key, required this.caja});
  final Caja caja;
  @override
  State<SellScreen> createState() => _SellScreenState();
}

class _SellScreenState extends State<SellScreen> {
  final rootFocus = FocusNode();
  final searchFocus = FocusNode();
  final search = TextEditingController();
  int? section;
  String _buffer = '';
  Timer? _bufferTimer;
  bool _dialog = false;

  Caja get caja => widget.caja;

  @override
  void dispose() {
    _bufferTimer?.cancel();
    rootFocus.dispose();
    searchFocus.dispose();
    super.dispose();
  }

  List<Map<String, dynamic>> get visible {
    final q = _norm(search.text);
    return caja.products.where((p) {
      if (section != null && p['section_id'] != section) return false;
      if (q.isEmpty) return true;
      return _norm(p['name'].toString()).contains(q) || (p['barcode'] ?? '').toString().contains(q);
    }).toList();
  }

  static String _norm(String s) => s
      .toLowerCase()
      .replaceAll(RegExp('[áà]'), 'a')
      .replaceAll(RegExp('[éè]'), 'e')
      .replaceAll(RegExp('[íì]'), 'i')
      .replaceAll(RegExp('[óò]'), 'o')
      .replaceAll(RegExp('[úùü]'), 'u')
      .trim();

  Future<T?> dialog<T>(Widget Function(BuildContext) builder) async {
    _dialog = true;
    final r = await showDialog<T>(context: context, builder: builder);
    _dialog = false;
    if (mounted) rootFocus.requestFocus();
    return r;
  }

  /// Con un pago de Puntos Trappi aplicado el ticket queda fijo (el cliente confirmó ese total).
  bool _blocked() {
    if (!caja.locked) return false;
    toast(context, 'El ticket tiene un pago con Puntos Trappi. Para cambiarlo, cancelá los puntos (F4).', error: true);
    return true;
  }

  /// El lector de código de barras "tipea" muy rápido y termina con Enter. Una tecla sola del 1 al 9
  /// (sin nada más enseguida) carga el producto rápido de ese número.
  void _flushBuffer() {
    _bufferTimer?.cancel();
    final b = _buffer;
    _buffer = '';
    if (b.isEmpty) return;
    if (RegExp(r'^\d+$').hasMatch(b) && _blocked()) return;
    if (b.length == 1 && RegExp(r'^[1-9]$').hasMatch(b)) {
      final i = int.parse(b) - 1;
      if (i < caja.quick.length) caja.addProduct(caja.quick[i]);
      return;
    }
    if (RegExp(r'^\d{3,}$').hasMatch(b) || b.length >= 6) {
      if (!caja.addBarcode(b)) toast(context, 'No hay ningún producto con el código $b. Cargalo en el panel (Productos → Código de barras).', error: true);
      return;
    }
    // Alguien empezó a escribir un nombre: se pasa al buscador.
    search.text = b;
    search.selection = TextSelection.collapsed(offset: b.length);
    searchFocus.requestFocus();
    setState(() {});
  }

  KeyEventResult onKey(FocusNode _, KeyEvent e) {
    if (_dialog || e is KeyUpEvent) return KeyEventResult.ignored;
    final k = e.logicalKey;
    final fn = <LogicalKeyboardKey, VoidCallback>{
      LogicalKeyboardKey.f2: charge,
      LogicalKeyboardKey.f3: () => searchFocus.requestFocus(),
      LogicalKeyboardKey.f4: pointsPay,
      LogicalKeyboardKey.f6: freeAmount,
      LogicalKeyboardKey.f7: discount,
      LogicalKeyboardKey.f8: reprint,
      LogicalKeyboardKey.f9: sales,
      LogicalKeyboardKey.f10: closeShift,
      LogicalKeyboardKey.f12: settings,
    }[k];
    if (fn != null) {
      if (e is KeyDownEvent) fn();
      return KeyEventResult.handled;
    }
    if (searchFocus.hasFocus) {
      if (k == LogicalKeyboardKey.escape) {
        search.clear();
        rootFocus.requestFocus();
        setState(() {});
        return KeyEventResult.handled;
      }
      return KeyEventResult.ignored;
    }
    if (k == LogicalKeyboardKey.enter || k == LogicalKeyboardKey.numpadEnter) {
      if (e is KeyDownEvent) _flushBuffer();
      return KeyEventResult.handled;
    }
    if (_buffer.isEmpty) {
      if (k == LogicalKeyboardKey.add || k == LogicalKeyboardKey.numpadAdd || e.character == '+') {
        if (!_blocked()) caja.changeQty(1);
        return KeyEventResult.handled;
      }
      if (k == LogicalKeyboardKey.minus || k == LogicalKeyboardKey.numpadSubtract) {
        if (!_blocked()) caja.changeQty(-1);
        return KeyEventResult.handled;
      }
      if (k == LogicalKeyboardKey.delete) {
        if (!_blocked()) caja.removeSelected();
        return KeyEventResult.handled;
      }
      if (k == LogicalKeyboardKey.arrowUp && caja.cart.isNotEmpty) {
        caja.select((caja.selected - 1).clamp(0, caja.cart.length - 1));
        return KeyEventResult.handled;
      }
      if (k == LogicalKeyboardKey.arrowDown && caja.cart.isNotEmpty) {
        caja.select((caja.selected + 1).clamp(0, caja.cart.length - 1));
        return KeyEventResult.handled;
      }
      if (k == LogicalKeyboardKey.escape && caja.cart.isNotEmpty && e is KeyDownEvent) {
        clearTicket();
        return KeyEventResult.handled;
      }
    }
    final c = e.character;
    if (c != null && c.length == 1 && RegExp(r'[0-9A-Za-zñÑáéíóúÁÉÍÓÚ\- ]').hasMatch(c)) {
      _buffer += c;
      _bufferTimer?.cancel();
      _bufferTimer = Timer(const Duration(milliseconds: 140), _flushBuffer);
      return KeyEventResult.handled;
    }
    return KeyEventResult.ignored;
  }

  Future<void> clearTicket() async {
    final ok = await dialog<bool>((c) => AlertDialog(
          title: const Text('¿Borrar el ticket?'),
          content: Text(caja.locked
              ? 'Se sacan todos los productos y se cancela el pago con Puntos Trappi: los puntos vuelven a la cuenta del cliente.'
              : 'Se sacan todos los productos cargados.'),
          actions: [
            TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('No')),
            FilledButton(autofocus: true, onPressed: () => Navigator.pop(c, true), child: const Text('Sí, borrar')),
          ],
        ));
    if (ok != true) return;
    if (caja.locked) {
      try {
        await caja.cancelPointsPay(caja.pointsPayment!['id'] as int);
      } on ApiError catch (e) {
        if (mounted) toast(context, e.offline ? 'Sin internet no se pueden devolver los puntos. Probá de nuevo cuando vuelva.' : e.message, error: true);
        return;
      }
    }
    caja.clearCart();
  }

  Future<void> pointsPay() async {
    if (!caja.pointsPayEnabled) {
      toast(context, 'Pagar con Puntos Trappi no está habilitado para este local.');
      return;
    }
    if (caja.cart.isEmpty) {
      toast(context, 'Cargá el ticket primero: el cliente usa sus puntos sobre el total.');
      return;
    }
    if (caja.locked) {
      final p = caja.pointsPayment!;
      final cancel = await dialog<bool>((c) => AlertDialog(
            title: const Text('Pago con Puntos Trappi'),
            content: Text('${p['customer'] ?? 'El cliente'} ya usó ${p['points']} puntos (-${money(p['discount'] as num)}).\n¿Cancelarlo? Los puntos vuelven a su cuenta.'),
            actions: [
              TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('Dejarlo')),
              FilledButton(style: FilledButton.styleFrom(backgroundColor: red), onPressed: () => Navigator.pop(c, true), child: const Text('Cancelar los puntos')),
            ],
          ));
      if (cancel == true) {
        try {
          await caja.cancelPointsPay(p['id'] as int);
          if (mounted) toast(context, 'Pago con puntos cancelado: los puntos volvieron al cliente.');
        } on ApiError catch (e) {
          if (mounted) toast(context, e.offline ? 'Sin internet no se puede cancelar. Probá cuando vuelva.' : e.message, error: true);
        }
      }
      return;
    }
    final r = await dialog<Map<String, dynamic>>((_) => PointsPayDialog(caja: caja));
    if (r != null) caja.applyPointsPay(r);
  }

  Future<void> charge() async {
    if (caja.cart.isEmpty) {
      toast(context, 'Cargá algún producto primero.');
      return;
    }
    final r = await dialog<(String, double?)>((_) => ChargeDialog(caja: caja));
    if (r == null) return;
    await caja.charge(r.$1, r.$2);
    if (!mounted) return;
    final sale = caja.lastSale!;
    final printErr = caja.local.config['printer'] != null ? await printTicket(caja, sale) : null;
    if (!mounted) return;
    if (printErr != null) toast(context, printErr, error: true);
    await dialog((_) => SaleDoneDialog(caja: caja));
  }

  Future<void> freeAmount() async {
    if (_blocked()) return;
    final r = await dialog<(String, double)>((_) => const FreeAmountDialog());
    if (r != null) caja.addFree(r.$1, r.$2);
  }

  Future<void> discount() async {
    if (_blocked()) return;
    if (caja.cart.isEmpty) {
      toast(context, 'Cargá algún producto primero.');
      return;
    }
    final r = await dialog<double>((_) => DiscountDialog(subtotal: caja.subtotal, current: caja.discount));
    if (r != null) caja.setDiscount(r);
  }

  Future<void> reprint() async {
    final s = caja.lastSale;
    if (s == null) {
      toast(context, 'Todavía no hay ventas para reimprimir. Las anteriores están en Ventas (F9).');
      return;
    }
    final err = await printTicket(caja, s);
    if (mounted) toast(context, err ?? 'Ticket reimpreso.', error: err != null);
  }

  Future<void> sales() => dialog((_) => SalesDialog(caja: caja));

  Future<void> closeShift() async {
    await caja.reloadShift();
    if (!mounted) return;
    if (caja.shift == null) {
      toast(context, 'No hay una caja abierta.');
      return;
    }
    final summary = await dialog<Map<String, dynamic>>((_) => CloseShiftDialog(caja: caja));
    if (summary == null || !mounted) return;
    await dialog((_) => ShiftResultDialog(caja: caja, summary: summary));
    caja.afterClose();
  }

  Future<void> settings() => dialog((_) => SettingsDialog(caja: caja));

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      body: Focus(
        focusNode: rootFocus,
        autofocus: true,
        onKeyEvent: onKey,
        child: ListenableBuilder(
          listenable: caja,
          builder: (context, _) => Column(children: [
            _TopBar(caja: caja, onSettings: settings),
            Expanded(
              child: Row(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
                Expanded(child: _catalog()),
                SizedBox(width: 430, child: _ticket()),
              ]),
            ),
            _shortcuts(),
          ]),
        ),
      ),
    );
  }

  Widget _catalog() {
    final items = visible;
    final quickIds = {for (var i = 0; i < caja.quick.length; i++) caja.quick[i]['id']: i + 1};
    return Padding(
      padding: const EdgeInsets.fromLTRB(20, 18, 12, 12),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        TextField(
          controller: search,
          focusNode: searchFocus,
          onChanged: (_) => setState(() {}),
          onSubmitted: (v) {
            if (_blocked()) {
              search.clear();
            } else if (caja.addBarcode(v)) {
              search.clear();
            } else if (items.length == 1) {
              caja.addProduct(items.first);
              search.clear();
            }
            setState(() {});
            rootFocus.requestFocus();
          },
          decoration: InputDecoration(
            hintText: 'Buscar producto o escanear código…',
            prefixIcon: const Icon(Icons.search),
            suffixIcon: const Padding(padding: EdgeInsets.all(12), child: Kbd('F3')),
            contentPadding: const EdgeInsets.symmetric(vertical: 16),
          ),
        ),
        const SizedBox(height: 12),
        SizedBox(
          height: 40,
          child: ListView(scrollDirection: Axis.horizontal, children: [
            _chip('Todo', section == null, () => setState(() => section = null)),
            for (final s in caja.sections) _chip(s['name'].toString(), section == s['id'], () => setState(() => section = s['id'] as int)),
          ]),
        ),
        const SizedBox(height: 12),
        Expanded(
          child: items.isEmpty
              ? Center(
                  child: Text(caja.products.isEmpty ? 'El menú está vacío. Cargá productos en el panel de Trappi.' : 'No hay productos con esa búsqueda.',
                      style: const TextStyle(color: muted)))
              : GridView.builder(
                  gridDelegate: const SliverGridDelegateWithMaxCrossAxisExtent(maxCrossAxisExtent: 210, mainAxisExtent: 112, crossAxisSpacing: 12, mainAxisSpacing: 12),
                  itemCount: items.length,
                  itemBuilder: (_, i) {
                    final p = items[i];
                    final n = quickIds[p['id']];
                    final noStock = p['stock'] != null && (p['stock'] as num) <= 0;
                    return Material(
                      color: Colors.white,
                      borderRadius: BorderRadius.circular(14),
                      child: InkWell(
                        borderRadius: BorderRadius.circular(14),
                        onTap: () {
                          if (!_blocked()) caja.addProduct(p);
                          rootFocus.requestFocus();
                        },
                        child: Container(
                          padding: const EdgeInsets.all(12),
                          decoration: BoxDecoration(borderRadius: BorderRadius.circular(14), border: Border.all(color: line)),
                          child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                            Row(children: [
                              if (n != null) Kbd('$n'),
                              const Spacer(),
                              if (noStock) const Text('Sin stock', style: TextStyle(color: red, fontSize: 12)),
                            ]),
                            const Spacer(),
                            Text(p['name'].toString(), maxLines: 2, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600, fontSize: 15)),
                            const SizedBox(height: 4),
                            Text(money(p['price'] as num), style: const TextStyle(color: violet, fontWeight: FontWeight.w800, fontSize: 16)),
                          ]),
                        ),
                      ),
                    );
                  },
                ),
        ),
      ]),
    );
  }

  Widget _chip(String text, bool on, VoidCallback tap) => Padding(
        padding: const EdgeInsets.only(right: 8),
        child: ChoiceChip(
          label: Text(text),
          selected: on,
          onSelected: (_) {
            tap();
            rootFocus.requestFocus();
          },
          selectedColor: violet,
          labelStyle: TextStyle(color: on ? Colors.white : ink, fontWeight: FontWeight.w600),
          showCheckmark: false,
        ),
      );

  Widget _ticket() {
    final last = caja.lastSale;
    return Container(
      margin: const EdgeInsets.fromLTRB(8, 18, 20, 12),
      decoration: BoxDecoration(color: Colors.white, borderRadius: BorderRadius.circular(18), border: Border.all(color: line)),
      child: Column(crossAxisAlignment: CrossAxisAlignment.stretch, children: [
        Padding(
          padding: const EdgeInsets.fromLTRB(18, 16, 10, 8),
          child: Row(children: [
            const Text('Ticket', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w800)),
            const Spacer(),
            if (caja.cart.isNotEmpty) TextButton.icon(onPressed: clearTicket, icon: const Icon(Icons.delete_outline, size: 18), label: const Text('Borrar (Esc)')),
          ]),
        ),
        const Divider(height: 1, color: line),
        Expanded(
          child: caja.cart.isEmpty
              ? Center(
                  child: last != null && last['claim'] != null
                      ? Column(mainAxisSize: MainAxisSize.min, children: [
                          const Text('Última venta: sumá tus puntos', style: TextStyle(color: muted)),
                          const SizedBox(height: 10),
                          QrImageView(data: (last['claim'] as Map)['url'].toString(), size: 170),
                          Text('${last['points']} Puntos Trappi · ${(last['claim'] as Map)['code']}', style: const TextStyle(fontWeight: FontWeight.w700)),
                        ])
                      : const Padding(
                          padding: EdgeInsets.all(30),
                          child: Text('Escaneá un producto, tocá uno de la lista o usá las teclas 1 a 9.', textAlign: TextAlign.center, style: TextStyle(color: muted)),
                        ),
                )
              : ListView.builder(
                  itemCount: caja.cart.length,
                  itemBuilder: (_, i) {
                    final l = caja.cart[i];
                    final on = i == caja.selected;
                    return InkWell(
                      onTap: () {
                        caja.select(i);
                        rootFocus.requestFocus();
                      },
                      child: Container(
                        color: on ? violetSoft : null,
                        padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
                        child: Row(children: [
                          _qtyButton(Icons.remove, () {
                            caja.select(i);
                            if (!_blocked()) caja.changeQty(-1);
                          }),
                          SizedBox(width: 34, child: Text('${l.quantity}', textAlign: TextAlign.center, style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16))),
                          _qtyButton(Icons.add, () {
                            caja.select(i);
                            if (!_blocked()) caja.changeQty(1);
                          }),
                          const SizedBox(width: 10),
                          Expanded(
                            child: Column(crossAxisAlignment: CrossAxisAlignment.start, children: [
                              Text(l.name, maxLines: 1, overflow: TextOverflow.ellipsis, style: const TextStyle(fontWeight: FontWeight.w600)),
                              Text(money(l.unitPrice), style: const TextStyle(color: muted, fontSize: 12)),
                            ]),
                          ),
                          Text(money(l.total), style: const TextStyle(fontWeight: FontWeight.w700)),
                        ]),
                      ),
                    );
                  },
                ),
        ),
        const Divider(height: 1, color: line),
        Padding(
          padding: const EdgeInsets.all(18),
          child: Column(children: [
            if (caja.discount > 0 || caja.locked) _sum('Subtotal', money(caja.subtotal)),
            if (caja.discount > 0) _sum('Descuento', '-${money(caja.discount)}', color: green),
            if (caja.locked) _sum('⭐ Puntos Trappi${caja.pointsPayment!['customer'] != null ? ' (${caja.pointsPayment!['customer']})' : ''}', '-${money(caja.pointsDiscount)}', color: violet),
            if (caja.discount > 0 || caja.locked) const SizedBox(height: 6),
            if (caja.cart.isNotEmpty && !caja.locked && caja.pointsPayEnabled)
              Align(
                alignment: Alignment.centerLeft,
                child: TextButton.icon(
                  onPressed: pointsPay,
                  icon: const Text('⭐', style: TextStyle(fontSize: 16)),
                  label: const Row(mainAxisSize: MainAxisSize.min, children: [Text('Pagar con Puntos Trappi'), SizedBox(width: 6), Kbd('F4')]),
                ),
              ),
            Row(children: [
              const Text('Total', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w700)),
              const Spacer(),
              Text(money(caja.total), style: const TextStyle(fontSize: 34, fontWeight: FontWeight.w900)),
            ]),
            const SizedBox(height: 14),
            SizedBox(
              width: double.infinity,
              child: FilledButton(
                onPressed: caja.cart.isEmpty ? null : charge,
                style: FilledButton.styleFrom(backgroundColor: green, padding: const EdgeInsets.symmetric(vertical: 22)),
                child: const Row(mainAxisAlignment: MainAxisAlignment.center, children: [
                  Text('COBRAR', style: TextStyle(fontSize: 20, fontWeight: FontWeight.w900, letterSpacing: 1)),
                  SizedBox(width: 10),
                  Kbd('F2', light: true),
                ]),
              ),
            ),
          ]),
        ),
      ]),
    );
  }

  Widget _qtyButton(IconData icon, VoidCallback onTap) => InkWell(
        onTap: onTap,
        borderRadius: BorderRadius.circular(8),
        child: Container(
          width: 28,
          height: 28,
          decoration: BoxDecoration(border: Border.all(color: line), borderRadius: BorderRadius.circular(8), color: Colors.white),
          child: Icon(icon, size: 16),
        ),
      );

  Widget _sum(String a, String b, {Color? color}) => Padding(
        padding: const EdgeInsets.symmetric(vertical: 2),
        child: Row(children: [Text(a, style: const TextStyle(color: muted)), const Spacer(), Text(b, style: TextStyle(color: color, fontWeight: FontWeight.w600))]),
      );

  Widget _shortcuts() {
    final items = <(String, String, VoidCallback)>[
      ('F2', 'Cobrar', charge),
      ('F3', 'Buscar', () => searchFocus.requestFocus()),
      if (caja.pointsPayEnabled) ('F4', 'Puntos', pointsPay),
      ('F6', 'Monto libre', freeAmount),
      ('F7', 'Descuento', discount),
      ('F8', 'Reimprimir', reprint),
      ('F9', 'Ventas', sales),
      ('F10', 'Cerrar caja', closeShift),
      ('+ / -', 'Cantidad', () {
        if (!_blocked()) caja.changeQty(1);
      }),
      ('Supr', 'Quitar', () {
        if (!_blocked()) caja.removeSelected();
      }),
    ];
    return Container(
      color: Colors.white,
      padding: const EdgeInsets.symmetric(horizontal: 16, vertical: 8),
      child: Row(children: [
        for (final it in items)
          Padding(
            padding: const EdgeInsets.only(right: 4),
            child: TextButton(
              onPressed: it.$3,
              style: TextButton.styleFrom(padding: const EdgeInsets.symmetric(horizontal: 8)),
              child: Row(mainAxisSize: MainAxisSize.min, children: [Kbd(it.$1), const SizedBox(width: 5), Text(it.$2, style: const TextStyle(color: ink))]),
            ),
          ),
        const Spacer(),
        IconButton(tooltip: 'Cambiar cajero', onPressed: caja.logout, icon: const Icon(Icons.logout, size: 20, color: violet)),
      ]),
    );
  }
}

// ---------------------------------------------------------------- cobrar

class ChargeDialog extends StatefulWidget {
  const ChargeDialog({super.key, required this.caja});
  final Caja caja;
  @override
  State<ChargeDialog> createState() => _ChargeDialogState();
}

class _ChargeDialogState extends State<ChargeDialog> {
  String method = 'efectivo';
  final paid = TextEditingController();
  String? error;

  double get total => widget.caja.total;
  double? get paidWith => parseMoney(paid.text);

  void confirm() {
    if (method == 'efectivo' && paidWith != null && paidWith! < total) {
      setState(() => error = 'El efectivo recibido es menor que el total.');
      return;
    }
    Navigator.pop(context, (method, method == 'efectivo' ? paidWith : null));
  }

  /// Billetes para cobrar rápido con un toque.
  List<double> get bills {
    final out = <double>{total};
    for (final b in [1000.0, 2000.0, 5000.0, 10000.0, 20000.0]) {
      final up = (total / b).ceil() * b;
      if (up > total) out.add(up);
    }
    return out.take(5).toList();
  }

  @override
  Widget build(BuildContext context) {
    final change = paidWith == null ? null : paidWith! - total;
    return CallbackShortcuts(
      bindings: {
        const SingleActivator(LogicalKeyboardKey.f2): confirm,
        const SingleActivator(LogicalKeyboardKey.digit1, alt: true): () => setState(() => method = 'efectivo'),
        const SingleActivator(LogicalKeyboardKey.digit2, alt: true): () => setState(() => method = 'mercadopago'),
        const SingleActivator(LogicalKeyboardKey.digit3, alt: true): () => setState(() => method = 'transferencia'),
      },
      child: AlertDialog(
        title: Row(children: [const Text('Cobrar'), const Spacer(), Text(money(total), style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w900))]),
        content: SizedBox(
          width: 520,
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            Row(children: [
              for (final (i, m) in widget.caja.methods.indexed)
                Expanded(
                  child: Padding(
                    padding: EdgeInsets.only(right: i < 2 ? 10 : 0),
                    child: InkWell(
                      borderRadius: BorderRadius.circular(14),
                      onTap: () => setState(() => method = m['id'] as String),
                      child: Container(
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        decoration: BoxDecoration(
                          color: method == m['id'] ? violetSoft : Colors.white,
                          borderRadius: BorderRadius.circular(14),
                          border: Border.all(color: method == m['id'] ? violet : line, width: 2),
                        ),
                        child: Column(children: [
                          Icon(switch (m['id']) { 'efectivo' => Icons.payments_outlined, 'mercadopago' => Icons.qr_code_2, _ => Icons.account_balance_outlined }, color: violet),
                          const SizedBox(height: 6),
                          Text(m['label'].toString(), style: const TextStyle(fontWeight: FontWeight.w700)),
                          Text('Alt+${i + 1}', style: const TextStyle(color: muted, fontSize: 12)),
                        ]),
                      ),
                    ),
                  ),
                ),
            ]),
            const SizedBox(height: 18),
            if (method == 'efectivo') ...[
              MoneyField(controller: paid, label: 'Con cuánto paga (opcional)', onSubmit: confirm, onChanged: (_) => setState(() => error = null)),
              const SizedBox(height: 10),
              Wrap(spacing: 8, children: [
                for (final b in bills)
                  ActionChip(
                    label: Text(b == total ? 'Justo' : money(b)),
                    onPressed: () => setState(() => paid.text = b.toStringAsFixed(b == b.roundToDouble() ? 0 : 2).replaceAll('.', ',')),
                  ),
              ]),
              const SizedBox(height: 14),
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(color: change != null && change >= 0 ? greenSoft : bg, borderRadius: BorderRadius.circular(14)),
                child: Row(children: [
                  const Text('Vuelto', style: TextStyle(fontSize: 18, fontWeight: FontWeight.w600)),
                  const Spacer(),
                  Text(change == null ? '—' : money(change < 0 ? 0 : change), style: const TextStyle(fontSize: 30, fontWeight: FontWeight.w900, color: green)),
                ]),
              ),
            ] else
              Container(
                padding: const EdgeInsets.all(16),
                decoration: BoxDecoration(color: bg, borderRadius: BorderRadius.circular(14)),
                child: Text(
                    method == 'mercadopago'
                        ? 'Cobrale con tu QR o posnet de Mercado Pago y confirmá cuando veas el pago acreditado.'
                        : 'Confirmá cuando veas la transferencia en tu cuenta.',
                    style: const TextStyle(color: muted)),
              ),
            if (error != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(error!, style: const TextStyle(color: red))),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Volver (Esc)')),
          FilledButton(
            autofocus: method != 'efectivo',
            onPressed: confirm,
            style: FilledButton.styleFrom(backgroundColor: green),
            child: const Text('Confirmar venta (Enter)'),
          ),
        ],
      ),
    );
  }
}

class SaleDoneDialog extends StatelessWidget {
  const SaleDoneDialog({super.key, required this.caja});
  final Caja caja;

  @override
  Widget build(BuildContext context) => ListenableBuilder(
        listenable: caja,
        builder: (context, _) {
          final s = caja.lastSale!;
          final claim = (s['claim'] as Map?)?.cast<String, dynamic>();
          final paid = (s['paid_with'] as num?)?.toDouble();
          final total = (s['total'] as num).toDouble();
          return AlertDialog(
            content: SizedBox(
              width: 560,
              child: Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
                Expanded(
                  child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
                    const Icon(Icons.check_circle, color: green, size: 46),
                    const SizedBox(height: 10),
                    Text(s['number'] != null ? 'Venta #${s['number']} lista' : 'Venta guardada', style: const TextStyle(fontSize: 24, fontWeight: FontWeight.w800)),
                    const SizedBox(height: 6),
                    Text('Total ${money(total)}', style: const TextStyle(fontSize: 18)),
                    if (paid != null) ...[
                      const SizedBox(height: 14),
                      const Text('Vuelto', style: TextStyle(color: muted)),
                      Text(money(paid - total), style: const TextStyle(fontSize: 40, fontWeight: FontWeight.w900, color: green)),
                    ],
                    if (s['pending'] == true) ...[
                      const SizedBox(height: 14),
                      const Text('Sin internet: la venta quedó guardada en la compu y se sube sola. El QR de puntos aparece cuando se suba (F8 para reimprimir).',
                          style: TextStyle(color: muted)),
                    ],
                  ]),
                ),
                if (claim != null) ...[
                  const SizedBox(width: 20),
                  Container(
                    padding: const EdgeInsets.all(14),
                    decoration: BoxDecoration(color: violetSoft, borderRadius: BorderRadius.circular(16)),
                    child: Column(mainAxisSize: MainAxisSize.min, children: [
                      Text('+${s['points']} Puntos Trappi', style: const TextStyle(fontWeight: FontWeight.w800, color: violetDark, fontSize: 16)),
                      const SizedBox(height: 8),
                      Container(color: Colors.white, padding: const EdgeInsets.all(8), child: QrImageView(data: claim['url'].toString(), size: 180)),
                      const SizedBox(height: 8),
                      Text(claim['code'].toString(), style: const TextStyle(fontWeight: FontWeight.w800, letterSpacing: 2)),
                      const Text('El cliente lo escanea con el celular', style: TextStyle(color: muted, fontSize: 12)),
                    ]),
                  ),
                ],
              ]),
            ),
            actions: [
              TextButton(
                onPressed: () async {
                  final err = await printTicket(caja, s);
                  if (context.mounted) toast(context, err ?? 'Ticket impreso.', error: err != null);
                },
                child: const Text('Imprimir ticket'),
              ),
              FilledButton(autofocus: true, onPressed: () => Navigator.pop(context), child: const Text('Nueva venta (Enter)')),
            ],
          );
        },
      );
}

// ---------------------------------------------------------------- pagar con Puntos Trappi (F4)

/// La caja pide el pago y muestra el código; el cliente escanea el QR del mostrador (o el de esta pantalla),
/// pone el código y confirma desde su celular. Acá se espera la confirmación.
class PointsPayDialog extends StatefulWidget {
  const PointsPayDialog({super.key, required this.caja});
  final Caja caja;
  @override
  State<PointsPayDialog> createState() => _PointsPayDialogState();
}

class _PointsPayDialogState extends State<PointsPayDialog> {
  Map<String, dynamic>? req;
  String? error;
  Timer? _poll;
  Timer? _tick;
  bool _closing = false;

  @override
  void initState() {
    super.initState();
    start();
  }

  @override
  void dispose() {
    _poll?.cancel();
    _tick?.cancel();
    // si el cliente ya confirmó, sus puntos ya se descontaron: el descuento queda en el ticket aunque se cierre la ventana
    final r = req;
    if (r != null && r['status'] == 'pending' && !_closing) {
      widget.caja.cancelPointsPay(r['id'] as int).catchError((_) {});  // se cerró sin cancelar: que no quede esperando
    }
    if (r != null && r['status'] == 'confirmed') {
      final caja = widget.caja;
      Future.microtask(() {
        if (caja.pointsPayment?['id'] != r['id']) caja.applyPointsPay(r);
      });
    }
    super.dispose();
  }

  Future<void> start() async {
    setState(() {
      req = null;
      error = null;
    });
    try {
      final r = await widget.caja.startPointsPay();
      if (!mounted) return;
      setState(() => req = r);
      _poll?.cancel();
      _poll = Timer.periodic(const Duration(seconds: 2), (_) => check());
      _tick?.cancel();
      _tick = Timer.periodic(const Duration(seconds: 1), (_) {
        if (mounted) setState(() {});
      });
    } on ApiError catch (e) {
      if (mounted) setState(() => error = e.offline ? 'Sin internet no se puede pagar con puntos.' : e.message);
    }
  }

  Future<void> check() async {
    final r = req;
    if (r == null || r['status'] != 'pending') return;
    try {
      final s = await widget.caja.pointsPayStatus(r['id'] as int);
      if (!mounted || _closing) return;
      setState(() => req = s);
      if (s['status'] != 'pending') {
        _poll?.cancel();
        _tick?.cancel();
      }
    } on ApiError {
      // sin internet un rato: se reintenta en el próximo tick
    }
  }

  int get secondsLeft {
    final exp = DateTime.tryParse((req?['expires_at'] ?? '').toString());
    if (exp == null) return 0;
    return exp.difference(DateTime.now().toUtc()).inSeconds.clamp(0, 999);
  }

  Future<void> close() async {
    _closing = true;
    final r = req;
    if (r != null && r['status'] == 'confirmed') {
      if (mounted) Navigator.pop(context, r);
      return;
    }
    if (r != null && r['status'] == 'pending') {
      try {
        await widget.caja.cancelPointsPay(r['id'] as int);
      } on ApiError {
        // vence solo a los 3 minutos
      }
    }
    if (mounted) Navigator.pop(context);
  }

  @override
  Widget build(BuildContext context) {
    final r = req;
    final status = r?['status'];
    final url = widget.caja.counterUrl;
    Widget body;
    if (error != null) {
      body = Text(error!, style: const TextStyle(color: red, fontSize: 16));
    } else if (r == null) {
      body = const Padding(padding: EdgeInsets.all(30), child: Center(child: CircularProgressIndicator()));
    } else if (status == 'confirmed') {
      body = Column(mainAxisSize: MainAxisSize.min, children: [
        const Icon(Icons.check_circle, color: green, size: 56),
        const SizedBox(height: 10),
        Text('${r['customer'] ?? 'El cliente'} usó ${r['points']} puntos', style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w800)),
        const SizedBox(height: 6),
        Text('-${money(r['discount'] as num)}', style: const TextStyle(fontSize: 40, fontWeight: FontWeight.w900, color: violet)),
        const SizedBox(height: 6),
        Text('Ahora cobrale ${money(((r['amount'] as num) - (r['discount'] as num)))}', style: const TextStyle(fontSize: 18)),
      ]);
    } else if (status == 'pending') {
      body = Row(crossAxisAlignment: CrossAxisAlignment.start, children: [
        Expanded(
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.start, children: [
            Text('Ticket de ${money(r['amount'] as num)}', style: const TextStyle(fontSize: 18)),
            const SizedBox(height: 16),
            const Text('El cliente escanea el QR del mostrador y pone este código:', style: TextStyle(color: muted)),
            const SizedBox(height: 8),
            Container(
              padding: const EdgeInsets.symmetric(horizontal: 22, vertical: 12),
              decoration: BoxDecoration(color: violetSoft, borderRadius: BorderRadius.circular(16)),
              child: Text(r['code'].toString(), style: const TextStyle(fontSize: 56, fontWeight: FontWeight.w900, letterSpacing: 14, color: violetDark)),
            ),
            const SizedBox(height: 14),
            Row(children: [
              const SizedBox(width: 18, height: 18, child: CircularProgressIndicator(strokeWidth: 2)),
              const SizedBox(width: 10),
              Text('Esperando que confirme… ${secondsLeft ~/ 60}:${(secondsLeft % 60).toString().padLeft(2, '0')}', style: const TextStyle(color: muted)),
            ]),
          ]),
        ),
        if (url != null) ...[
          const SizedBox(width: 18),
          Column(mainAxisSize: MainAxisSize.min, children: [
            Container(
              padding: const EdgeInsets.all(8),
              decoration: BoxDecoration(border: Border.all(color: line), borderRadius: BorderRadius.circular(12)),
              child: QrImageView(data: url, size: 170),
            ),
            const SizedBox(height: 6),
            const Text('o que escanee este', style: TextStyle(color: muted, fontSize: 12)),
          ]),
        ],
      ]);
    } else {
      body = Text(
          switch (status) {
            'expired' => 'El código venció sin que el cliente confirme.',
            'cancelled' => 'El pago con puntos se canceló.',
            _ => 'El pago con puntos no se completó.',
          },
          style: const TextStyle(fontSize: 16));
    }
    // Esc o tocar afuera pasan por close(): si el código seguía esperando se cancela, y si ya confirmó se aplica
    return PopScope(
      canPop: false,
      onPopInvokedWithResult: (didPop, _) {
        if (!didPop && !_closing) close();
      },
      child: AlertDialog(
        title: const Row(children: [Text('⭐', style: TextStyle(fontSize: 22)), SizedBox(width: 8), Text('Pagar con Puntos Trappi')]),
        content: SizedBox(width: 600, child: body),
        actions: [
          if (status == 'confirmed')
            FilledButton(autofocus: true, onPressed: () => Navigator.pop(context, r), child: const Text('Aplicar al ticket (Enter)'))
          else ...[
            TextButton(onPressed: close, child: const Text('Cancelar (Esc)')),
            if (error != null || (status != null && status != 'pending')) FilledButton(onPressed: start, child: const Text('Pedir otro código')),
          ],
        ],
      ),
    );
  }
}

// ---------------------------------------------------------------- monto libre y descuento

class FreeAmountDialog extends StatefulWidget {
  const FreeAmountDialog({super.key});
  @override
  State<FreeAmountDialog> createState() => _FreeAmountDialogState();
}

class _FreeAmountDialogState extends State<FreeAmountDialog> {
  final amount = TextEditingController();
  final name = TextEditingController();

  void go() {
    final v = parseMoney(amount.text);
    if (v == null || v <= 0) return;
    Navigator.pop(context, (name.text, v));
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Monto libre'),
        content: SizedBox(
          width: 400,
          child: Column(mainAxisSize: MainAxisSize.min, children: [
            MoneyField(controller: amount, label: 'Importe', onSubmit: go),
            const SizedBox(height: 12),
            TextField(controller: name, decoration: const InputDecoration(labelText: 'Detalle (opcional)'), onSubmitted: (_) => go()),
          ]),
        ),
        actions: [
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancelar')),
          FilledButton(onPressed: go, child: const Text('Agregar')),
        ],
      );
}

class DiscountDialog extends StatefulWidget {
  const DiscountDialog({super.key, required this.subtotal, required this.current});
  final double subtotal;
  final double current;
  @override
  State<DiscountDialog> createState() => _DiscountDialogState();
}

class _DiscountDialogState extends State<DiscountDialog> {
  bool percent = true;
  final value = TextEditingController();

  double get amount {
    final v = parseMoney(value.text) ?? 0;
    final a = percent ? widget.subtotal * v.clamp(0, 100) / 100 : v;
    return double.parse(a.clamp(0, widget.subtotal).toStringAsFixed(2));
  }

  @override
  Widget build(BuildContext context) => AlertDialog(
        title: const Text('Descuento'),
        content: SizedBox(
          width: 400,
          child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
            SegmentedButton<bool>(
              segments: const [ButtonSegment(value: true, label: Text('Porcentaje %')), ButtonSegment(value: false, label: Text('Importe \$'))],
              selected: {percent},
              onSelectionChanged: (s) => setState(() => percent = s.first),
            ),
            const SizedBox(height: 14),
            TextField(
              controller: value,
              autofocus: true,
              style: const TextStyle(fontSize: 26, fontWeight: FontWeight.w800),
              inputFormatters: [FilteringTextInputFormatter.allow(RegExp(r'[0-9.,]'))],
              decoration: InputDecoration(suffixText: percent ? '%' : null, prefixText: percent ? null : '\$ '),
              onChanged: (_) => setState(() {}),
              onSubmitted: (_) => Navigator.pop(context, amount),
            ),
            const SizedBox(height: 10),
            Text('Descuento: ${money(amount)}  ·  Queda ${money(widget.subtotal - amount)}', style: const TextStyle(color: muted)),
          ]),
        ),
        actions: [
          if (widget.current > 0) TextButton(onPressed: () => Navigator.pop(context, 0.0), child: const Text('Quitar descuento')),
          TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancelar')),
          FilledButton(onPressed: () => Navigator.pop(context, amount), child: const Text('Aplicar')),
        ],
      );
}

// ---------------------------------------------------------------- ventas (F9)

class SalesDialog extends StatefulWidget {
  const SalesDialog({super.key, required this.caja});
  final Caja caja;
  @override
  State<SalesDialog> createState() => _SalesDialogState();
}

class _SalesDialogState extends State<SalesDialog> {
  List<Map<String, dynamic>>? sales;
  String? error;

  @override
  void initState() {
    super.initState();
    load();
  }

  Future<void> load() async {
    await widget.caja.sync();
    try {
      final r = await widget.caja.api.recentSales();
      if (mounted) setState(() => sales = ((r['sales'] as List?) ?? []).cast<Map>().map((m) => m.cast<String, dynamic>()).toList());
    } on ApiError catch (e) {
      if (mounted) setState(() => error = e.offline ? 'Sin internet: solo se ven las ventas guardadas en la compu.' : e.message);
    }
  }

  String names(Map<String, dynamic> s) => ((s['items'] as List?) ?? []).cast<Map>().map((i) => '${i['quantity']}× ${i['name'] ?? 'Producto'}').join(', ');

  Future<void> voidSale(Map<String, dynamic> s) async {
    final caja = widget.caja;
    final token = caja.isOwner ? caja.api.cashierToken : await askOwner(context, caja, 'Anular la venta #${s['number']}');
    if (token == null || !mounted) return;
    final ok = await showDialog<bool>(
      context: context,
      builder: (c) => AlertDialog(
        title: Text('¿Anular la venta #${s['number']}?'),
        content: Text('${money(s['total'] as num)} · ${names(s)}\n\nSi tenía QR de puntos sin usar, el QR deja de valer.'),
        actions: [
          TextButton(onPressed: () => Navigator.pop(c, false), child: const Text('No')),
          FilledButton(style: FilledButton.styleFrom(backgroundColor: red), onPressed: () => Navigator.pop(c, true), child: const Text('Anular')),
        ],
      ),
    );
    if (ok != true) return;
    try {
      await caja.api.voidSale(s['id'] as int, asToken: token);
      await caja.reloadShift();
      await load();
      if (mounted) toast(context, 'Venta anulada.');
    } on ApiError catch (e) {
      if (mounted) toast(context, e.message, error: true);
    }
  }

  @override
  Widget build(BuildContext context) {
    final caja = widget.caja;
    final cashierNames = {for (final c in caja.cashiers) c['id']: c['name']};
    return AlertDialog(
      title: Row(children: [
        const Text('Ventas'),
        const Spacer(),
        IconButton(onPressed: () {
          setState(() => sales = null);
          load();
        }, icon: const Icon(Icons.refresh)),
      ]),
      content: SizedBox(
        width: 820,
        height: 520,
        child: ListView(children: [
          if (caja.rejected.isNotEmpty) ...[
            Row(children: [
              const Text('No se pudieron registrar', style: TextStyle(fontWeight: FontWeight.w800, color: red)),
              const Spacer(),
              TextButton(onPressed: () async {
                await caja.dismissRejected();
                setState(() {});
              }, child: const Text('Ya las revisé')),
            ]),
            for (final r in caja.rejected)
              ListTile(
                dense: true,
                leading: const Icon(Icons.error_outline, color: red),
                title: Text(r['error'].toString()),
                subtitle: Text('Venta del ${(r['sale'] as Map?)?['sold_at'] ?? ''}'),
              ),
            const Divider(),
          ],
          if (caja.local.pending.isNotEmpty) ...[
            Text('Por subir (${caja.local.pending.length})', style: const TextStyle(fontWeight: FontWeight.w800)),
            for (final p in caja.local.pending)
              ListTile(
                dense: true,
                leading: const Icon(Icons.cloud_upload_outlined, color: muted),
                title: Text('${((p['items'] as List?) ?? []).length} productos · ${_methodLabel(p['payment_method'])}'),
                subtitle: Text(p['sold_at'].toString()),
              ),
            const Divider(),
          ],
          if (error != null) Padding(padding: const EdgeInsets.all(12), child: Text(error!, style: const TextStyle(color: muted))),
          if (sales == null && error == null) const Padding(padding: EdgeInsets.all(30), child: Center(child: CircularProgressIndicator())),
          for (final s in sales ?? <Map<String, dynamic>>[])
            ListTile(
              leading: CircleAvatar(
                backgroundColor: s['voided'] == true ? const Color(0xFFFFE4E1) : violetSoft,
                child: Text('${s['number']}', style: TextStyle(fontSize: 13, color: s['voided'] == true ? red : violet, fontWeight: FontWeight.w700)),
              ),
              title: Text(names(s), maxLines: 1, overflow: TextOverflow.ellipsis,
                  style: TextStyle(decoration: s['voided'] == true ? TextDecoration.lineThrough : null)),
              subtitle: Text([
                _time(s['sold_at']),
                _methodLabel(s['payment_method']),
                if (cashierNames[s['cashier_id']] != null) cashierNames[s['cashier_id']].toString(),
                if (s['claim'] != null) (s['claim']['claimed'] == true ? 'puntos sumados' : '${s['points']} pts sin usar'),
                if (s['voided'] == true) 'ANULADA',
              ].join(' · ')),
              trailing: Row(mainAxisSize: MainAxisSize.min, children: [
                Text(money(s['total'] as num), style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 16)),
                const SizedBox(width: 8),
                IconButton(
                  tooltip: 'Reimprimir',
                  icon: const Icon(Icons.print_outlined),
                  onPressed: () async {
                    final err = await printTicket(caja, {...s, 'cashier_name': cashierNames[s['cashier_id']]});
                    if (context.mounted) toast(context, err ?? 'Ticket reimpreso.', error: err != null);
                  },
                ),
                if (s['voided'] != true)
                  IconButton(tooltip: 'Anular (dueño)', icon: const Icon(Icons.block, color: red), onPressed: () => voidSale(s)),
              ]),
            ),
        ]),
      ),
      actions: [FilledButton(onPressed: () => Navigator.pop(context), child: const Text('Cerrar (Esc)'))],
    );
  }
}

String _methodLabel(Object? m) => switch (m) {
      'efectivo' => 'Efectivo',
      'mercadopago' => 'Mercado Pago',
      'transferencia' => 'Transferencia',
      _ => (m ?? '').toString(),
    };

String _time(Object? iso) {
  final d = DateTime.tryParse((iso ?? '').toString())?.toLocal();
  if (d == null) return '';
  String two(int v) => v.toString().padLeft(2, '0');
  return '${two(d.day)}/${two(d.month)} ${two(d.hour)}:${two(d.minute)}';
}

// ---------------------------------------------------------------- cerrar caja (F10)

class CloseShiftDialog extends StatefulWidget {
  const CloseShiftDialog({super.key, required this.caja});
  final Caja caja;
  @override
  State<CloseShiftDialog> createState() => _CloseShiftDialogState();
}

class _CloseShiftDialogState extends State<CloseShiftDialog> {
  final counted = TextEditingController();
  String? error;
  bool busy = false;

  Future<void> go() async {
    final v = parseMoney(counted.text);
    if (v == null || v < 0) {
      setState(() => error = 'Contá el efectivo del cajón y ponelo acá.');
      return;
    }
    final caja = widget.caja;
    final token = caja.isOwner ? caja.api.cashierToken : await askOwner(context, caja, 'Cerrar la caja');
    if (token == null) return;
    setState(() => busy = true);
    try {
      final summary = await caja.closeShift(v, asToken: token);
      if (mounted) Navigator.pop(context, summary);
    } on ApiError catch (e) {
      if (mounted) setState(() => error = e.offline ? 'Hace falta internet para cerrar la caja.' : e.message);
    } finally {
      if (mounted) setState(() => busy = false);
    }
  }

  @override
  Widget build(BuildContext context) {
    final s = widget.caja.shift!;
    final by = ((s['by_method'] as Map?) ?? {}).cast<String, dynamic>();
    return AlertDialog(
      title: const Text('Cerrar la caja'),
      content: SizedBox(
        width: 480,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _kv('Ventas', '${s['sales']}'),
          for (final m in by.values) _kv('  ${m['label']} (${m['count']})', money(m['total'] as num)),
          _kv('Total vendido', money(s['total'] as num), bold: true),
          const Divider(),
          _kv('Fondo inicial', money(s['opening_cash'] as num)),
          _kv('Efectivo que debería haber', money(s['expected_cash'] as num), bold: true),
          const SizedBox(height: 14),
          MoneyField(controller: counted, label: 'Efectivo contado en el cajón', onSubmit: go),
          if (error != null) Padding(padding: const EdgeInsets.only(top: 10), child: Text(error!, style: const TextStyle(color: red))),
        ]),
      ),
      actions: [
        TextButton(onPressed: () => Navigator.pop(context), child: const Text('Cancelar')),
        FilledButton(onPressed: busy ? null : go, child: const Text('Cerrar caja')),
      ],
    );
  }
}

Widget _kv(String a, String b, {bool bold = false}) => Padding(
      padding: const EdgeInsets.symmetric(vertical: 3),
      child: Row(children: [
        Text(a, style: TextStyle(color: bold ? ink : muted, fontWeight: bold ? FontWeight.w700 : null)),
        const Spacer(),
        Text(b, style: TextStyle(fontWeight: bold ? FontWeight.w800 : FontWeight.w600)),
      ]),
    );

class ShiftResultDialog extends StatelessWidget {
  const ShiftResultDialog({super.key, required this.caja, required this.summary});
  final Caja caja;
  final Map<String, dynamic> summary;
  @override
  Widget build(BuildContext context) {
    final diff = (summary['difference'] as num?)?.toDouble() ?? 0;
    return AlertDialog(
      title: const Text('Caja cerrada'),
      content: SizedBox(
        width: 440,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          _kv('Total vendido', money(summary['total'] as num), bold: true),
          _kv('Ventas', '${summary['sales']}'),
          _kv('Efectivo esperado', money(summary['expected_cash'] as num)),
          _kv('Efectivo contado', money((summary['counted_cash'] as num?) ?? 0)),
          const SizedBox(height: 8),
          Container(
            padding: const EdgeInsets.all(14),
            decoration: BoxDecoration(color: diff.abs() < 0.01 ? greenSoft : const Color(0xFFFFF4E5), borderRadius: BorderRadius.circular(12)),
            child: Text(
              diff.abs() < 0.01 ? 'La caja cierra justa.' : (diff > 0 ? 'Sobran ${money(diff)}.' : 'Faltan ${money(-diff)}.'),
              style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w800),
            ),
          ),
          const SizedBox(height: 10),
          Text('Puntos Trappi entregados: ${summary['points']} en ${summary['qr_total']} QR (${summary['qr_claimed']} ya usados).', style: const TextStyle(color: muted)),
        ]),
      ),
      actions: [FilledButton(autofocus: true, onPressed: () => Navigator.pop(context), child: const Text('Listo'))],
    );
  }
}

// ---------------------------------------------------------------- configuración (F12)

class SettingsDialog extends StatefulWidget {
  const SettingsDialog({super.key, required this.caja});
  final Caja caja;
  @override
  State<SettingsDialog> createState() => _SettingsDialogState();
}

class _SettingsDialogState extends State<SettingsDialog> {
  List<Printer>? printers;
  String? error;

  @override
  void initState() {
    super.initState();
    Printing.listPrinters().then((p) {
      if (mounted) setState(() => printers = p);
    }).catchError((Object e) {
      if (mounted) setState(() => error = 'No se pudieron leer las impresoras: $e');
    });
  }

  @override
  Widget build(BuildContext context) {
    final caja = widget.caja;
    final current = (caja.local.config['printer'] as Map?)?['url'] as String?;
    final paper = (caja.local.config['paper'] as int?) ?? 80;
    return AlertDialog(
      title: const Text('Configuración'),
      content: SizedBox(
        width: 560,
        child: Column(mainAxisSize: MainAxisSize.min, crossAxisAlignment: CrossAxisAlignment.stretch, children: [
          const Text('Impresora de tickets', style: TextStyle(fontWeight: FontWeight.w800)),
          const SizedBox(height: 8),
          if (printers == null && error == null) const LinearProgressIndicator(),
          if (error != null) Text(error!, style: const TextStyle(color: red)),
          if (printers != null)
            DropdownButtonFormField<String?>(
              initialValue: printers!.any((p) => p.url == current) ? current : null,
              decoration: const InputDecoration(labelText: 'Impresora'),
              items: [
                const DropdownMenuItem<String?>(value: null, child: Text('Sin impresora')),
                for (final p in printers!) DropdownMenuItem<String?>(value: p.url, child: Text(p.name + (p.isDefault ? ' (predeterminada)' : ''))),
              ],
              onChanged: (v) async {
                final p = printers!.where((x) => x.url == v).firstOrNull;
                await caja.setPrinter(p?.url, p?.name, paper);
                setState(() {});
              },
            ),
          const SizedBox(height: 10),
          SegmentedButton<int>(
            segments: const [ButtonSegment(value: 58, label: Text('Papel 58 mm')), ButtonSegment(value: 80, label: Text('Papel 80 mm'))],
            selected: {paper},
            onSelectionChanged: (s) async {
              final p = (caja.local.config['printer'] as Map?)?.cast<String, dynamic>();
              await caja.setPrinter(p?['url'] as String?, p?['name'] as String?, s.first);
              setState(() {});
            },
          ),
          const SizedBox(height: 8),
          Align(
            alignment: Alignment.centerLeft,
            child: TextButton.icon(
              icon: const Icon(Icons.print_outlined),
              label: const Text('Imprimir ticket de prueba'),
              onPressed: () async {
                final err = await printTicket(caja, {
                  'number': 0,
                  'sold_at': DateTime.now().toUtc().toIso8601String(),
                  'lines': [
                    {'name': 'Ticket de prueba', 'quantity': 1, 'total': 0},
                  ],
                  'total': 0,
                  'payment_method': 'efectivo',
                });
                if (context.mounted) toast(context, err ?? 'Listo: si salió el ticket, la impresora está bien.', error: err != null);
              },
            ),
          ),
          const Divider(height: 28),
          Text('Comercio: ${caja.store['name'] ?? ''}', style: const TextStyle(fontWeight: FontWeight.w700)),
          Text('Servidor: $apiBase', style: const TextStyle(color: muted, fontSize: 12)),
          const SizedBox(height: 10),
          Wrap(spacing: 10, runSpacing: 10, children: [
            OutlinedButton.icon(
              icon: const Icon(Icons.sync),
              label: const Text('Actualizar menú'),
              onPressed: () async {
                await caja.refresh();
                if (context.mounted) toast(context, caja.online ? 'Menú actualizado.' : 'Sin internet: se usa el último menú guardado.');
              },
            ),
            OutlinedButton.icon(
              icon: const Icon(Icons.link_off),
              label: const Text('Desvincular esta compu'),
              onPressed: () async {
                if (caja.pendingCount > 0) {
                  toast(context, 'Hay ventas sin subir. Conectate a internet antes de desvincular.', error: true);
                  return;
                }
                final t = await askOwner(context, caja, 'Desvincular esta compu');
                if (t == null) return;
                if (context.mounted) Navigator.pop(context);
                await caja.unlink();
              },
            ),
            OutlinedButton.icon(
              icon: const Icon(Icons.power_settings_new, color: red),
              label: const Text('Salir del programa'),
              onPressed: () async {
                final t = await askOwner(context, caja, 'Salir de Trappi Caja');
                if (t != null) await windowManager.destroy();
              },
            ),
          ]),
        ]),
      ),
      actions: [FilledButton(onPressed: () => Navigator.pop(context), child: const Text('Cerrar'))],
    );
  }
}
