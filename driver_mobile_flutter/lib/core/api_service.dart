import 'dart:convert';
import 'package:http/http.dart' as http;
import 'constants.dart';

/// Cliente REST centralizado para la aplicación móvil de Josepo Driver (Fase 6).
/// Todos los importes monetarios del servidor se reciben y procesan respetando la precisión en centavos enteros.
class ApiService {
  static Map<String, String> _headers([String? token]) {
    final headers = <String, String>{'Content-Type': 'application/json'};
    if (token != null && token.isNotEmpty) {
      headers['Authorization'] = 'Bearer $token';
    }
    return headers;
  }

  /// 1. Login con correo y contraseña
  static Future<Map<String, dynamic>> loginPassword(String email, String password) async {
    final res = await http.post(
      Uri.parse('${AppConstants.baseUrl}/api/auth/login'),
      headers: _headers(),
      body: jsonEncode({'email': email.trim(), 'password': password}),
    );
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode != 200) {
      throw Exception(data['error'] ?? 'Error al iniciar sesión');
    }
    return data;
  }

  /// 2. Solicitar código OTP de 6 dígitos (SMS / WhatsApp)
  static Future<Map<String, dynamic>> requestOtpCode(String phoneNumber) async {
    final res = await http.post(
      Uri.parse('${AppConstants.baseUrl}/api/auth/otp/send'),
      headers: _headers(),
      body: jsonEncode({'phone_number': phoneNumber.trim(), 'purpose': 'SOS_LOGIN'}),
    );
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode != 200) {
      throw Exception(data['error'] ?? 'Error solicitando código OTP');
    }
    return data;
  }

  /// 3. Verificar código OTP de 6 dígitos y obtener JWT
  static Future<Map<String, dynamic>> verifyOtpCode({
    required String phoneNumber,
    required String code,
    String? fullName,
  }) async {
    final res = await http.post(
      Uri.parse('${AppConstants.baseUrl}/api/auth/otp/verify'),
      headers: _headers(),
      body: jsonEncode({
        'phone_number': phoneNumber.trim(),
        'code': code.trim(),
        'purpose': 'SOS_LOGIN',
        if (fullName != null && fullName.isNotEmpty) 'full_name': fullName.trim(),
      }),
    );
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode != 200) {
      throw Exception(data['error'] ?? 'Código OTP inválido o expirado');
    }
    return data;
  }

  /// 4. Consultar perfil actual y validez del JWT
  static Future<Map<String, dynamic>> getMe(String token) async {
    final res = await http.get(
      Uri.parse('${AppConstants.baseUrl}/api/auth/me'),
      headers: _headers(token),
    );
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode != 200) {
      throw Exception(data['error'] ?? 'Sesión expirada');
    }
    return data;
  }

  /// 5. Obtener datos de la grúa vinculada al chofer
  static Future<Map<String, dynamic>> getMyTruck(String token) async {
    final res = await http.get(
      Uri.parse('${AppConstants.baseUrl}/api/driver/my-truck'),
      headers: _headers(token),
    );
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode != 200) {
      throw Exception(data['error'] ?? 'No se encontró grúa vinculada');
    }
    return data;
  }

  /// 6. Alternar estado de turno (En Turno / Fuera de Turno)
  static Future<Map<String, dynamic>> toggleShift(String token, {bool? isActive}) async {
    final res = await http.post(
      Uri.parse('${AppConstants.baseUrl}/api/driver/toggle-shift'),
      headers: _headers(token),
      body: jsonEncode(isActive != null ? {'is_active': isActive} : {}),
    );
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode != 200) {
      throw Exception(data['error'] ?? 'No se pudo cambiar el turno');
    }
    return data;
  }

  /// 7. Consultar orden activa u oferta pendiente
  static Future<Map<String, dynamic>> getCurrentOrder(String token) async {
    final res = await http.get(
      Uri.parse('${AppConstants.baseUrl}/api/driver/current-order'),
      headers: _headers(token),
    );
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode != 200) {
      throw Exception(data['error'] ?? 'Error consultando orden actual');
    }
    return data;
  }

  /// 8. Simular pedido SOS de prueba para la grúa del conductor
  static Future<Map<String, dynamic>> simulateSosRequest(String token) async {
    final res = await http.post(
      Uri.parse('${AppConstants.baseUrl}/api/driver/simulate-request'),
      headers: _headers(token),
    );
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode != 201 && res.statusCode != 200) {
      throw Exception(data['error'] ?? 'No se pudo simular el pedido SOS');
    }
    return data;
  }

  /// 9. Responder oferta de despacho (Aceptar / Rechazar dentro del SLA de 30s)
  static Future<Map<String, dynamic>> respondOffer(
    String token,
    String requestId,
    bool accepted,
  ) async {
    final res = await http.post(
      Uri.parse('${AppConstants.baseUrl}/api/driver/respond-offer'),
      headers: _headers(token),
      body: jsonEncode({'request_id': requestId, 'accepted': accepted}),
    );
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode != 200) {
      throw Exception(data['error'] ?? 'Error respondiendo a la oferta');
    }
    return data;
  }

  /// 10. Actualizar etapa del viaje (IN_TRANSIT_TO_USER, ARRIVED_AT_USER, IN_TRANSIT_TO_DEST, COMPLETED)
  static Future<Map<String, dynamic>> updateTripStatus(
    String token,
    String requestId,
    String status,
  ) async {
    final res = await http.post(
      Uri.parse('${AppConstants.baseUrl}/api/driver/update-trip-status'),
      headers: _headers(token),
      body: jsonEncode({'request_id': requestId, 'status': status}),
    );
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode != 200) {
      throw Exception(data['error'] ?? 'Error actualizando fase del remolque');
    }
    return data;
  }

  /// 11. Registrar Acta Digital de Inspección Vehicular (Fase 4 - Protección SHA-256)
  static Future<Map<String, dynamic>> submitVehicleInspection({
    required String token,
    required String requestId,
    required String vehiclePlate,
    required String vehicleModel,
    required String vehicleColor,
    required String preExistingDamages,
  }) async {
    final res = await http.post(
      Uri.parse('${AppConstants.baseUrl}/api/contracts/inspect'),
      headers: _headers(token),
      body: jsonEncode({
        'request_id': requestId,
        'vehicle_plate': vehiclePlate.trim(),
        'vehicle_model': vehicleModel.trim(),
        'vehicle_color': vehicleColor.trim(),
        'pre_existing_damages': preExistingDamages.trim(),
      }),
    );
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode != 201 && res.statusCode != 200) {
      throw Exception(data['error'] ?? 'Error registrando acta de inspección');
    }
    return data;
  }

  /// 12. Transmitir telemetría GPS por REST (Usado por el servicio en segundo plano con pantalla apagada)
  static Future<void> sendTelemetryRest({
    required String token,
    required double lat,
    required double lng,
    required bool isMocked,
  }) async {
    await http.post(
      Uri.parse('${AppConstants.baseUrl}/api/driver/telemetry'),
      headers: _headers(token),
      body: jsonEncode({
        'lat': lat,
        'lng': lng,
        'is_mocked': isMocked,
      }),
    );
  }

  /// 13. Obtener tasa oficial BCV y bancos soportados para Billetera / Escrow
  static Future<Map<String, dynamic>> getExchangeRate() async {
    final res = await http.get(Uri.parse('${AppConstants.baseUrl}/api/currency/rate'));
    return jsonDecode(res.body) as Map<String, dynamic>;
  }

  static Future<List<dynamic>> getSupportedBanks() async {
    final res = await http.get(Uri.parse('${AppConstants.baseUrl}/api/payments/banks'));
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return (data['banks'] as List<dynamic>?) ?? [];
  }

  /// 14. Consultar perfil de Gamificación, Puntos y Recompensas (Fase 5)
  static Future<Map<String, dynamic>> getGamificationProfile(String token) async {
    final res = await http.get(
      Uri.parse('${AppConstants.baseUrl}/api/gamification/profile'),
      headers: _headers(token),
    );
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode != 200) {
      throw Exception(data['error'] ?? 'Error consultando puntos');
    }
    return data;
  }

  static Future<List<dynamic>> getPartnerRewards() async {
    final res = await http.get(Uri.parse('${AppConstants.baseUrl}/api/gamification/rewards'));
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    return (data['rewards'] as List<dynamic>?) ?? [];
  }

  static Future<Map<String, dynamic>> redeemReward(String token, int rewardId) async {
    final res = await http.post(
      Uri.parse('${AppConstants.baseUrl}/api/gamification/redeem'),
      headers: _headers(token),
      body: jsonEncode({'reward_id': rewardId}),
    );
    final data = jsonDecode(res.body) as Map<String, dynamic>;
    if (res.statusCode != 201 && res.statusCode != 200) {
      throw Exception(data['error'] ?? 'No se pudo canjear el beneficio');
    }
    return data;
  }
}

