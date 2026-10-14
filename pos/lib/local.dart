import 'dart:convert';
import 'dart:io';

import 'package:path_provider/path_provider.dart';

/// Lo que la caja guarda en la compu (en la carpeta de datos del programa):
///   config: token de la caja, comercio, impresora elegida
///   catalog: el menú (para vender aunque se corte internet)
///   pending: ventas que todavía no se pudieron subir
class Local {
  Local._(this._dir);
  final Directory _dir;
  Map<String, dynamic> config = {};
  Map<String, dynamic> catalog = {'products': [], 'sections': []};
  List<Map<String, dynamic>> pending = [];

  static Future<Local> open() async {
    final base = await getApplicationSupportDirectory();
    final dir = Directory('${base.path}${Platform.pathSeparator}trappi_caja');
    await dir.create(recursive: true);
    final l = Local._(dir);
    l.config = Map<String, dynamic>.from(await l._read('config', <String, dynamic>{}) as Map);
    l.catalog = Map<String, dynamic>.from(await l._read('catalog', <String, dynamic>{'products': [], 'sections': []}) as Map);
    l.pending = [for (final s in (await l._read('pending', []) as List)) Map<String, dynamic>.from(s as Map)];
    return l;
  }

  File _file(String name) => File('${_dir.path}${Platform.pathSeparator}$name.json');

  Future<Object> _read(String name, Object fallback) async {
    try {
      final f = _file(name);
      if (!await f.exists()) return fallback;
      return jsonDecode(await f.readAsString()) as Object;
    } catch (_) {
      return fallback; // archivo dañado: se arranca de cero, sin romper la caja
    }
  }

  Future<void> _write(String name, Object value) async {
    final f = _file(name);
    final tmp = File('${f.path}.tmp');
    await tmp.writeAsString(jsonEncode(value), flush: true);
    await tmp.rename(f.path); // se escribe completo o no se escribe (por si se corta la luz)
  }

  Future<void> saveConfig() => _write('config', config);
  Future<void> saveCatalog() => _write('catalog', catalog);
  Future<void> savePending() => _write('pending', pending);

  Future<void> unlink() async {
    config = {};
    await saveConfig();
  }
}
