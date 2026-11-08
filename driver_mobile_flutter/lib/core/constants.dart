import 'package:flutter/material.dart';

/// Configuración global del cliente móvil Flutter.
/// REGLA DE SEGURIDAD DE AUDITORÍA:
/// - NUNCA almacenar llaves privadas de APIs de mapas, tokens administrativos ni secretos en este archivo.
/// - Toda configuración de entorno se inyecta en tiempo de compilación mediante `--dart-define`:
///   Ejemplo: `flutter build apk --dart-define=JOSEPO_API_URL=https://api.josepo.com --dart-define=JOSEPO_WS_URL=https://api.josepo.com`
class AppConstants {
  static const String baseUrl = String.fromEnvironment(
    'JOSEPO_API_URL',
    defaultValue: 'http://10.0.2.2:5000',
  );

  static const String socketUrl = String.fromEnvironment(
    'JOSEPO_WS_URL',
    defaultValue: 'http://10.0.2.2:5000',
  );

  // Límites locales de integridad de telemetría GPS
  static const int minGpsIntervalSeconds = 3;
  static const double maxAllowedAccuracyMeters = 100.0;

  // Paleta de colores Premium Dark
  static const Color bgMidnight = Color(0xFF0B1120);
  static const Color bgCard = Color(0xFF1E293B);
  static const Color primaryEmerald = Color(0xFF10B981);
  static const Color secondaryBlue = Color(0xFF3B82F6);
  static const Color warningAmber = Color(0xFFF59E0B);
  static const Color dangerRed = Color(0xFFEF4444);
  static const Color textMain = Color(0xFFF8FAFC);
  static const Color textMuted = Color(0xFF94A3B8);
}
