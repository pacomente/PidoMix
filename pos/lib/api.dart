import 'dart:convert';

import 'package:http/http.dart' as http;

/// Servidor de Trappi. Para probar contra otro: --dart-define=TRAPPI_API=http://localhost:8000
const String apiBase = String.fromEnvironment('TRAPPI_API', defaultValue: 'https://trappi.com.ar');

class ApiError implements Exception {
  ApiError(this.message, [this.status = 0]);
  final String message;
  final int status;
  bool get offline => status == 0;
  @override
  String toString() => message;
}

/// Cliente de /api/pos/v1. El token de la caja se guarda al vincular; el del cajero, al poner el PIN.
class Api {
  Api({this.deviceToken, this.cashierToken});
  String? deviceToken;
  String? cashierToken;
  final http.Client _http = http.Client();

  Map<String, String> _headers(String? cashier) => {
        'Content-Type': 'application/json',
        if (deviceToken != null) 'Authorization': 'Bearer $deviceToken',
        if ((cashier ?? cashierToken) != null) 'X-Cashier': (cashier ?? cashierToken)!,
      };

  /// [asToken] usa el token de otro cajero solo para este pedido (el dueño que autoriza un cierre o una anulación).
  Future<Map<String, dynamic>> _send(String method, String path, [Object? body, String? asToken]) async {
    final uri = Uri.parse('$apiBase/api/pos/v1$path');
    http.Response r;
    try {
      r = method == 'GET'
          ? await _http.get(uri, headers: _headers(asToken)).timeout(const Duration(seconds: 12))
          : await _http.post(uri, headers: _headers(asToken), body: jsonEncode(body ?? {})).timeout(const Duration(seconds: 20));
    } catch (_) {
      throw ApiError('Sin conexión con Trappi.');
    }
    Map<String, dynamic> data;
    try {
      data = jsonDecode(utf8.decode(r.bodyBytes)) as Map<String, dynamic>;
    } catch (_) {
      throw ApiError('Trappi respondió algo inesperado (HTTP ${r.statusCode}).', r.statusCode);
    }
    if (r.statusCode >= 400) {
      throw ApiError((data['error'] ?? data['detail'] ?? 'Error ${r.statusCode}').toString(), r.statusCode);
    }
    return data;
  }

  Future<Map<String, dynamic>> link(String email, String password) => _send('POST', '/link', {'email': email, 'password': password});
  Future<Map<String, dynamic>> me() => _send('GET', '/me');
  Future<Map<String, dynamic>> cashierLogin(int id, String pin) => _send('POST', '/cashiers/login', {'cashier_id': id, 'pin': pin});
  Future<Map<String, dynamic>> catalog() => _send('GET', '/catalog');
  Future<Map<String, dynamic>> openShift(double amount) => _send('POST', '/shifts/open', {'amount': amount});
  Future<Map<String, dynamic>> closeShift(double counted, {String? asToken}) => _send('POST', '/shifts/close', {'amount': counted}, asToken);
  Future<Map<String, dynamic>> currentShift() => _send('GET', '/shifts/current');
  Future<Map<String, dynamic>> uploadSales(List<Map<String, dynamic>> sales) => _send('POST', '/sales', {'sales': sales});
  Future<Map<String, dynamic>> recentSales() => _send('GET', '/sales?limit=40');
  Future<Map<String, dynamic>> voidSale(int id, {String? asToken}) => _send('POST', '/sales/$id/void', null, asToken);
}
