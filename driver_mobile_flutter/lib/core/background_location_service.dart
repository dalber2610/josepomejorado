import 'dart:async';
import 'dart:ui';
import 'package:flutter/widgets.dart';
import 'package:flutter_background_service/flutter_background_service.dart';
import 'package:flutter_background_service_android/flutter_background_service_android.dart';
import 'package:geolocator/geolocator.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'api_service.dart';
import 'constants.dart';

/// Servicio Nativo de Telemetría GPS en Segundo Plano (Fase 6).
/// Garantiza que la ubicación de la grúa continúe transmitiéndose ininterrumpidamente
/// cuando el conductor apaga la pantalla o cambia a Google Maps / Waze para navegar.
class BackgroundLocationService {
  static const String _prefTokenKey = 'josepo_bg_jwt_token';

  /// Guarda el JWT para que el Isolate en segundo plano pueda autenticar la telemetría.
  static Future<void> setAuthToken(String? token) async {
    final prefs = await SharedPreferences.getInstance();
    if (token == null || token.isEmpty) {
      await prefs.remove(_prefTokenKey);
    } else {
      await prefs.setString(_prefTokenKey, token);
    }
  }

  /// Solicita permisos de ubicación en primer y segundo plano (`LocationPermission.always`).
  static Future<bool> requestAlwaysLocationPermission() async {
    bool serviceEnabled = await Geolocator.isLocationServiceEnabled();
    if (!serviceEnabled) return false;

    LocationPermission permission = await Geolocator.checkPermission();
    if (permission == LocationPermission.denied) {
      permission = await Geolocator.requestPermission();
      if (permission == LocationPermission.denied) return false;
    }

    if (permission == LocationPermission.deniedForever) {
      return false;
    }

    return true;
  }

  /// Inicializa el motor de servicio en segundo plano para Android (Foreground Service) e iOS.
  static Future<void> initialize() async {
    final service = FlutterBackgroundService();

    await service.configure(
      androidConfiguration: AndroidConfiguration(
        onStart: onStartBackgroundIsolate,
        autoStart: false,
        isForegroundMode: true,
        notificationChannelId: 'josepo_driver_gps_channel',
        initialNotificationTitle: 'JOSEPO Driver • GPS Activo',
        initialNotificationContent:
            'Transmitiendo ubicación en vivo (compatible con Waze / Google Maps y pantalla apagada).',
        foregroundServiceNotificationId: 888,
      ),
      iosConfiguration: IosConfiguration(
        autoStart: false,
        onForeground: onStartBackgroundIsolate,
        onBackground: onIosBackground,
      ),
    );
  }

  /// Arranca la transmisión persistente en segundo plano.
  static Future<void> startService(String jwtToken) async {
    await setAuthToken(jwtToken);
    final service = FlutterBackgroundService();
    bool isRunning = await service.isRunning();
    if (!isRunning) {
      await service.startService();
    }
  }

  /// Detiene el servicio en segundo plano al cerrar turno o cerrar sesión.
  static Future<void> stopService() async {
    await setAuthToken(null);
    final service = FlutterBackgroundService();
    bool isRunning = await service.isRunning();
    if (isRunning) {
      service.invoke('stopService');
    }
  }
}

@pragma('vm:entry-point')
Future<bool> onIosBackground(ServiceInstance service) async {
  WidgetsFlutterBinding.ensureInitialized();
  DartPluginRegistrant.ensureInitialized();
  return true;
}

@pragma('vm:entry-point')
void onStartBackgroundIsolate(ServiceInstance service) async {
  DartPluginRegistrant.ensureInitialized();

  if (service is AndroidServiceInstance) {
    service.on('setAsForeground').listen((event) {
      service.setAsForegroundService();
    });
    service.on('setAsBackground').listen((event) {
      service.setAsBackgroundService();
    });
  }

  StreamSubscription<Position>? bgPositionSub;

  service.on('stopService').listen((event) {
    bgPositionSub?.cancel();
    service.stopSelf();
  });

  // Escuchar stream de GPS incluso con pantalla bloqueada o en segundo plano
  bgPositionSub = Geolocator.getPositionStream(
    locationSettings: const LocationSettings(
      accuracy: LocationAccuracy.high,
      distanceFilter: 5,
    ),
  ).listen((Position pos) async {
    // Bloquear Mock Location / Fake GPS también en segundo plano (Hallazgo E)
    if (pos.isMocked) return;
    if (pos.accuracy > AppConstants.maxAllowedAccuracyMeters) return;

    final prefs = await SharedPreferences.getInstance();
    final token = prefs.getString('josepo_bg_jwt_token');
    if (token == null || token.isEmpty) return;

    if (service is AndroidServiceInstance) {
      if (await service.isForegroundService()) {
        service.setForegroundNotificationInfo(
          title: 'JOSEPO Driver • Radar GPS Activo',
          content:
              'Ubicación: (${pos.latitude.toStringAsFixed(4)}, ${pos.longitude.toStringAsFixed(4)}) • En línea con Central',
        );
      }
    }

    try {
      await ApiService.sendTelemetryRest(
        token: token,
        lat: pos.latitude,
        lng: pos.longitude,
        isMocked: pos.isMocked,
      );
    } catch (_) {}
  });
}

