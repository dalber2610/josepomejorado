import 'dart:async';
import 'package:flutter/foundation.dart';
import 'package:socket_io_client/socket_io_client.dart' as IO;
import 'package:geolocator/geolocator.dart';
import 'constants.dart';
import 'background_location_service.dart';

class DriverSocketService {
  IO.Socket? _socket;
  StreamSubscription<Position>? _positionStream;
  DateTime? _lastEmittedAt;

  Function(Map<String, dynamic>)? onDispatchOfferReceived;
  Function(String)? onOfferTimeout;
  Function(String)? onTowCancelled;
  Function(Map<String, dynamic>)? onPaymentEvent;
  Function(Position)? onPositionUpdated;
  Function(String)? onSecurityViolation;

  bool get isConnected => _socket?.connected ?? false;

  ///Construye la configuración nativa de geolocalización para Android (Foreground Notification + WakeLock)
  ///e iOS (Background Location Indicator) para operar con pantalla apagada o usando Waze / Google Maps.
  LocationSettings _buildPlatformLocationSettings() {
    if (defaultTargetPlatform == TargetPlatform.android) {
      return AndroidSettings(
        accuracy: LocationAccuracy.high,
        distanceFilter: 5,
        forceLocationManager: false,
        intervalDuration: const Duration(seconds: AppConstants.minGpsIntervalSeconds),
        foregroundNotificationConfig: const ForegroundNotificationConfig(
          notificationTitle: 'JOSEPO Driver • Telemetría GPS en Vivo',
          notificationText:
              'Transmitiendo coordenadas en segundo plano mientras usas Waze/Maps o con pantalla apagada.',
          enableWakeLock: true,
          setOngoing: true,
        ),
      );
    } else if (defaultTargetPlatform == TargetPlatform.iOS ||
        defaultTargetPlatform == TargetPlatform.macOS) {
      return AppleSettings(
        accuracy: LocationAccuracy.high,
        activityType: ActivityType.automotiveNavigation,
        distanceFilter: 5,
        pauseLocationUpdatesAutomatically: false,
        showBackgroundLocationIndicator: true,
        allowBackgroundLocationUpdates: true,
      );
    }
    return const LocationSettings(
      accuracy: LocationAccuracy.high,
      distanceFilter: 5,
    );
  }

  void connect(String jwtToken) {
    _socket = IO.io(
      AppConstants.socketUrl,
      IO.OptionBuilder()
          .setTransports(['websocket'])
          .enableAutoConnect()
          .enableReconnection()
          .setAuth({'token': jwtToken})
          .build(),
    );

    _socket?.onConnect((_) {
      debugPrint('[DriverSocket] Conectado exitosamente');
      startGpsStreaming(jwtToken: jwtToken);
    });

    _socket?.on('dispatch_offer', (data) {
      if (data is Map<String, dynamic> && onDispatchOfferReceived != null) {
        onDispatchOfferReceived!(data);
      }
    });

    _socket?.on('dispatch_offer_timeout', (data) {
      if (onOfferTimeout != null && data is Map) {
        onOfferTimeout!(data['message']?.toString() ?? 'Oferta expirada.');
      }
    });

    _socket?.on('tow_cancelled', (data) {
      if (onTowCancelled != null && data is Map) {
        onTowCancelled!(data['message']?.toString() ?? 'Servicio cancelado por el cliente.');
      }
    });

    _socket?.on('payment_held', (data) {
      if (data is Map<String, dynamic> && onPaymentEvent != null) {
        onPaymentEvent!({'type': 'HELD', 'data': data});
      }
    });

    _socket?.on('payment_released', (data) {
      if (data is Map<String, dynamic> && onPaymentEvent != null) {
        onPaymentEvent!({'type': 'RELEASED', 'data': data});
      }
    });

    _socket?.on('error', (data) {
      if (data is Map && data['code'] == 'GPS_SPOOFING_DETECTED' && onSecurityViolation != null) {
        onSecurityViolation!(data['message']?.toString() ?? 'Anomalía de GPS detectada.');
      }
    });

    _socket?.onDisconnect((_) {
      debugPrint('[DriverSocket] Desconectado');
    });
  }

  Future<void> startGpsStreaming({String? jwtToken}) async {
    final hasPermission = await BackgroundLocationService.requestAlwaysLocationPermission();
    if (!hasPermission) return;

    if (jwtToken != null && jwtToken.isNotEmpty) {
      await BackgroundLocationService.startService(jwtToken);
    }

    await _positionStream?.cancel();
    _positionStream = Geolocator.getPositionStream(
      locationSettings: _buildPlatformLocationSettings(),
    ).listen((Position position) {
      // 1. Detección local Anti-Fake GPS (Mock Location en Android/iOS)
      if (position.isMocked) {
        debugPrint('[DriverSocket][SEGURIDAD] Ubicación simulada (Fake GPS) detectada y bloqueada.');
        if (onSecurityViolation != null) {
          onSecurityViolation!(
            'Se detectó una aplicación de GPS Falso (Mock Location). Desactívala para operar en JOSEPO.',
          );
        }
        return;
      }

      // 2. Descartar lecturas con precisión degradada (> 100m)
      if (position.accuracy > AppConstants.maxAllowedAccuracyMeters) {
        return;
      }

      if (onPositionUpdated != null) {
        onPositionUpdated!(position);
      }

      // 3. Throttling de emisión para proteger concurrencia (mínimo cada 3s)
      final now = DateTime.now();
      if (_lastEmittedAt != null &&
          now.difference(_lastEmittedAt!).inSeconds < AppConstants.minGpsIntervalSeconds) {
        return;
      }
      _lastEmittedAt = now;

      if (isConnected) {
        _socket?.emit('update_driver_position', {
          'lat': position.latitude,
          'lng': position.longitude,
          'accuracy': position.accuracy,
          'speed_mps': position.speed,
          'is_mocked': position.isMocked,
        });
      }
    });
  }

  void respondOffer(String requestId, bool accepted) {
    if (isConnected) {
      _socket?.emit('driver_respond_offer', {
        'request_id': requestId,
        'accepted': accepted,
      });
    }
  }

  void updateTripStatus(String requestId, String status) {
    if (isConnected) {
      _socket?.emit('driver_update_status', {
        'request_id': requestId,
        'status': status,
      });
    }
  }

  Future<void> dispose() async {
    await _positionStream?.cancel();
    await BackgroundLocationService.stopService();
    _socket?.disconnect();
    _socket?.dispose();
  }
}
