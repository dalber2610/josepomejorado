import 'dart:async';
import 'package:flutter/material.dart';
import 'package:flutter_map/flutter_map.dart';
import 'package:latlong2/latlong.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'package:url_launcher/url_launcher.dart';
import '../core/constants.dart';
import '../core/api_service.dart';
import '../core/socket_service.dart';
import 'login_screen.dart';
import 'wallet_screen.dart';
import 'profile_screen.dart';

/// Pantalla Principal de Mapa de Despacho, SLA 30s, Navegación Externa Waze/Google Maps
/// y Telemetría GPS Persistente en Segundo Plano (Fase 6).
class HomeMapScreen extends StatefulWidget {
  final String token;
  final Map<String, dynamic> initialUser;

  const HomeMapScreen({
    super.key,
    required this.token,
    required this.initialUser,
  });

  @override
  State<HomeMapScreen> createState() => _HomeMapScreenState();
}

class _HomeMapScreenState extends State<HomeMapScreen> {
  final DriverSocketService _socketService = DriverSocketService();
  final MapController _mapController = MapController();

  int _currentTabIndex = 0;
  bool _isOnShift = true;
  bool _simulatingOrder = false;

  Map<String, dynamic>? _truckData;
  Map<String, dynamic>? _activeOrder;
  LatLng _currentLatLng = const LatLng(10.5000, -66.9167);

  @override
  void initState() {
    super.initState();
    _initDriverSession();
  }

  Future<void> _initDriverSession() async {
    _socketService.onDispatchOfferReceived = _showIncomingOfferDialog;
    _socketService.onOfferTimeout = (msg) {
      if (!mounted) return;
      Navigator.of(context, rootNavigator: true).maybePop();
      _showSnack(msg, isError: true);
    };
    _socketService.onTowCancelled = (msg) {
      if (!mounted) return;
      setState(() => _activeOrder = null);
      _showSnack(msg, isError: true);
    };
    _socketService.onPaymentEvent = (evt) {
      if (!mounted) return;
      final msg = evt['data']?['notification_message']?.toString() ?? 'Actualización de pago en Escrow.';
      _showSnack(msg);
    };
    _socketService.onSecurityViolation = (msg) {
      if (!mounted) return;
      _showSnack(msg, isError: true);
    };
    _socketService.onPositionUpdated = (pos) {
      if (!mounted) return;
      setState(() {
        _currentLatLng = LatLng(pos.latitude, pos.longitude);
      });
    };

    _socketService.connect(widget.token);
    await _loadTruckAndActiveOrder();
  }

  Future<void> _loadTruckAndActiveOrder() async {
    try {
      final truckRes = await ApiService.getMyTruck(widget.token);
      final orderRes = await ApiService.getCurrentOrder(widget.token);
      if (!mounted) return;

      final truck = truckRes['truck'] as Map<String, dynamic>?;
      if (truck != null) {
        final pos = truck['current_position'] as Map<String, dynamic>?;
        setState(() {
          _truckData = truck;
          _isOnShift = (truck['is_active'] as bool?) ?? true;
          if (pos != null && pos['lat'] != null && pos['lng'] != null) {
            _currentLatLng = LatLng(
              (pos['lat'] as num).toDouble(),
              (pos['lng'] as num).toDouble(),
            );
          }
        });
      }

      if (orderRes['type'] == 'active' && orderRes['order'] != null) {
        setState(() => _activeOrder = orderRes['order'] as Map<String, dynamic>);
      } else if (orderRes['type'] == 'offer' && orderRes['order'] != null) {
        _showIncomingOfferDialog(orderRes['order'] as Map<String, dynamic>);
      }
    } catch (_) {}
  }

  void _showSnack(String msg, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg),
        backgroundColor: isError ? AppConstants.dangerRed : AppConstants.primaryEmerald,
      ),
    );
  }

  Future<void> _toggleShift() async {
    try {
      final res = await ApiService.toggleShift(widget.token);
      final truck = res['truck'] as Map<String, dynamic>?;
      if (!mounted) return;
      setState(() {
        _truckData = truck ?? _truckData;
        _isOnShift = (truck?['is_active'] as bool?) ?? !_isOnShift;
      });
      _showSnack(res['message']?.toString() ?? 'Estado de turno actualizado.');
    } catch (e) {
      _showSnack(e.toString().replaceFirst('Exception: ', ''), isError: true);
    }
  }

  Future<void> _simulateSosOrder() async {
    setState(() => _simulatingOrder = true);
    try {
      final res = await ApiService.simulateSosRequest(widget.token);
      final req = res['request'] as Map<String, dynamic>?;
      if (req != null && mounted) {
        _showIncomingOfferDialog(req);
      }
    } catch (e) {
      _showSnack(e.toString().replaceFirst('Exception: ', ''), isError: true);
    } finally {
      if (mounted) setState(() => _simulatingOrder = false);
    }
  }

  /// Abre Waze o Google Maps manteniendo la telemetría GPS de Josepo activa en segundo plano.
  Future<void> _openExternalNavigation(double targetLat, double targetLng) async {
    final wazeUri = Uri.parse('https://waze.com/ul?ll=$targetLat,$targetLng&navigate=yes');
    final gmapsUri = Uri.parse('https://www.google.com/maps/dir/?api=1&destination=$targetLat,$targetLng');

    if (await canLaunchUrl(wazeUri)) {
      await launchUrl(wazeUri, mode: LaunchMode.externalApplication);
    } else {
      await launchUrl(gmapsUri, mode: LaunchMode.externalApplication);
    }
  }

  void _showIncomingOfferDialog(Map<String, dynamic> offer) {
    final requestId = (offer['request_id'] ?? offer['id'])?.toString() ?? '';
    final origin = (offer['origin'] as Map<String, dynamic>?) ?? {};
    final pricing = (offer['pricing'] as Map<String, dynamic>?) ?? {};
    final costUsd = pricing['cost_usd'] ?? offer['cost_usd'] ?? 0;
    final netUsd = offer['driver_net_usd'] ?? ((costUsd as num) * 0.85).toStringAsFixed(2);

    showDialog(
      context: context,
      barrierDismissible: false,
      builder: (ctx) {
        return AlertDialog(
          backgroundColor: AppConstants.bgCard,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(20),
            side: const BorderSide(color: AppConstants.warningAmber, width: 2),
          ),
          title: const Row(
            children: [
              Icon(Icons.emergency_share, color: AppConstants.warningAmber),
              SizedBox(width: 8),
              Expanded(
                child: Text(
                  '🚨 ¡AUXILIO VIAL ENTRANTE! (SLA 30s)',
                  style: TextStyle(color: AppConstants.warningAmber, fontSize: 16, fontWeight: FontWeight.w900),
                ),
              ),
            ],
          ),
          content: Column(
            mainAxisSize: MainAxisSize.min,
            crossAxisAlignment: CrossAxisAlignment.start,
            children: [
              Text('Cliente: ${offer['client_name'] ?? 'Conductor SOS'}', style: const TextStyle(fontWeight: FontWeight.bold)),
              const SizedBox(height: 6),
              Text(
                'Ubicación: ${origin['address'] ?? 'Coordenadas GPS verificadas'}',
                style: const TextStyle(fontSize: 12, color: AppConstants.textMuted),
              ),
              const SizedBox(height: 10),
              Container(
                padding: const EdgeInsets.all(10),
                decoration: BoxDecoration(
                  color: AppConstants.bgMidnight,
                  borderRadius: BorderRadius.circular(10),
                ),
                child: Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text('Tu Ganancia Neta (85%):', style: TextStyle(fontSize: 12)),
                    Text(
                      '$netUsd USD',
                      style: const TextStyle(fontSize: 16, fontWeight: FontWeight.w900, color: AppConstants.primaryEmerald),
                    ),
                  ],
                ),
              ),
            ],
          ),
          actions: [
            TextButton(
              onPressed: () async {
                Navigator.pop(ctx);
                await ApiService.respondOffer(widget.token, requestId, false);
              },
              child: const Text('RECHAZAR', style: TextStyle(color: AppConstants.dangerRed, fontWeight: FontWeight.bold)),
            ),
            ElevatedButton(
              onPressed: () async {
                Navigator.pop(ctx);
                try {
                  final res = await ApiService.respondOffer(widget.token, requestId, true);
                  if (!mounted) return;
                  setState(() {
                    _activeOrder = (res['request'] as Map<String, dynamic>?) ?? offer;
                  });
                  _showSnack('¡Servicio asignado! GPS en segundo plano activo.');
                } catch (e) {
                  _showSnack(e.toString().replaceFirst('Exception: ', ''), isError: true);
                }
              },
              style: ElevatedButton.styleFrom(backgroundColor: AppConstants.primaryEmerald),
              child: const Text('ACEPTAR RESCATE', style: TextStyle(color: Colors.white, fontWeight: FontWeight.w900)),
            ),
          ],
        );
      },
    );
  }

  Future<void> _updateTripStage(String newStatus) async {
    if (_activeOrder == null) return;
    final reqId = (_activeOrder!['id'] ?? _activeOrder!['request_id'])?.toString() ?? '';
    try {
      await ApiService.updateTripStatus(widget.token, reqId, newStatus);
      if (!mounted) return;
      if (newStatus == 'ARRIVED_AT_USER') {
        setState(() => _activeOrder!['status'] = newStatus);
        _showVehicleInspectionDialog(reqId);
      } else if (newStatus == 'COMPLETED') {
        setState(() => _activeOrder = null);
        _showSnack('¡Remolque finalizado! Fondos Escrow liberados (85%) y +50 pts acreditados.');
      } else {
        setState(() => _activeOrder!['status'] = newStatus);
        _showSnack('Estado actualizado a $newStatus');
      }
    } catch (e) {
      _showSnack(e.toString().replaceFirst('Exception: ', ''), isError: true);
    }
  }

  void _showVehicleInspectionDialog(String requestId) {
    final plateCtrl = TextEditingController(text: 'AB890CD');
    final modelCtrl = TextEditingController(text: 'Toyota Corolla 2019');
    final colorCtrl = TextEditingController(text: 'Plata');
    final damagesCtrl = TextEditingController(text: 'Rayón previo en parachoques delantero.');

    showDialog(
      context: context,
      builder: (ctx) => AlertDialog(
        backgroundColor: AppConstants.bgCard,
        title: const Text(
          '📋 Acta Digital de Inspección (SHA-256)',
          style: TextStyle(fontSize: 16, fontWeight: FontWeight.bold, color: AppConstants.secondaryBlue),
        ),
        content: SingleChildScrollView(
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              TextField(controller: plateCtrl, decoration: const InputDecoration(labelText: 'Placa del Vehículo')),
              const SizedBox(height: 8),
              TextField(controller: modelCtrl, decoration: const InputDecoration(labelText: 'Marca y Modelo')),
              const SizedBox(height: 8),
              TextField(controller: colorCtrl, decoration: const InputDecoration(labelText: 'Color')),
              const SizedBox(height: 8),
              TextField(controller: damagesCtrl, decoration: const InputDecoration(labelText: 'Daños Previos / Rayones')),
            ],
          ),
        ),
        actions: [
          ElevatedButton(
            onPressed: () async {
              Navigator.pop(ctx);
              try {
                await ApiService.submitVehicleInspection(
                  token: widget.token,
                  requestId: requestId,
                  vehiclePlate: plateCtrl.text,
                  vehicleModel: modelCtrl.text,
                  vehicleColor: colorCtrl.text,
                  preExistingDamages: damagesCtrl.text,
                );
                _showSnack('Acta de Inspección Vehicular firmada y sellada (SHA-256).');
              } catch (e) {
                _showSnack(e.toString(), isError: true);
              }
            },
            style: ElevatedButton.styleFrom(backgroundColor: AppConstants.secondaryBlue),
            child: const Text('CERTIFICAR ACTA Y SLA', style: TextStyle(color: Colors.white, fontWeight: FontWeight.bold)),
          ),
        ],
      ),
    );
  }

  Future<void> _handleLogout() async {
    await _socketService.dispose();
    final prefs = await SharedPreferences.getInstance();
    await prefs.remove('josepo_driver_jwt');
    if (!mounted) return;
    Navigator.pushReplacement(context, MaterialPageRoute(builder: (_) => const LoginScreen()));
  }

  @override
  void dispose() {
    _socketService.dispose();
    super.dispose();
  }

  Widget _buildDispatchMapTab() {
    final origin = _activeOrder?['origin'] as Map<String, dynamic>?;
    final LatLng? clientLatLng = (origin != null && origin['lat'] != null && origin['lng'] != null)
        ? LatLng((origin['lat'] as num).toDouble(), (origin['lng'] as num).toDouble())
        : null;

    return Stack(
      children: [
        // Mapa Interactivo OpenStreetMap
        FlutterMap(
          mapController: _mapController,
          options: MapOptions(
            initialCenter: _currentLatLng,
            initialZoom: 14.0,
          ),
          children: [
            TileLayer(
              urlTemplate: 'https://tile.openstreetmap.org/{z}/{x}/{y}.png',
              userAgentPackageName: 'com.josepo.driver',
            ),
            MarkerLayer(
              markers: [
                Marker(
                  point: _currentLatLng,
                  width: 44,
                  height: 44,
                  child: Container(
                    decoration: BoxDecoration(
                      color: AppConstants.primaryEmerald,
                      shape: BoxShape.circle,
                      border: Border.all(color: Colors.white, width: 3),
                    ),
                    child: const Icon(Icons.fire_truck, color: Colors.white, size: 22),
                  ),
                ),
                if (clientLatLng != null)
                  Marker(
                    point: clientLatLng,
                    width: 42,
                    height: 42,
                    child: Container(
                      decoration: BoxDecoration(
                        color: AppConstants.dangerRed,
                        shape: BoxShape.circle,
                        border: Border.all(color: Colors.white, width: 3),
                      ),
                      child: const Icon(Icons.person_pin_circle, color: Colors.white, size: 22),
                    ),
                  ),
              ],
            ),
          ],
        ),

        // Banner Superior de GPS en Segundo Plano (Foreground Notification Activa)
        Positioned(
          top: 12,
          left: 12,
          right: 12,
          child: Container(
            padding: const EdgeInsets.symmetric(horizontal: 14, vertical: 10),
            decoration: BoxDecoration(
              color: AppConstants.bgMidnight.withOpacity(0.92),
              borderRadius: BorderRadius.circular(14),
              border: Border.all(color: AppConstants.primaryEmerald.withOpacity(0.6)),
            ),
            child: Row(
              children: [
                const Icon(Icons.satellite_alt, color: AppConstants.primaryEmerald, size: 18),
                const SizedBox(width: 8),
                const Expanded(
                  child: Text(
                    'GPS 2do Plano Activo • Compatible con pantalla apagada y Waze/Maps',
                    style: TextStyle(fontSize: 11, fontWeight: FontWeight.w700),
                  ),
                ),
                GestureDetector(
                  onTap: _simulateSosOrder,
                  child: Container(
                    padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 6),
                    decoration: BoxDecoration(
                      color: AppConstants.dangerRed,
                      borderRadius: BorderRadius.circular(8),
                    ),
                    child: Text(
                      _simulatingOrder ? '...' : '🚨 Simular SOS',
                      style: const TextStyle(fontSize: 11, fontWeight: FontWeight.w900, color: Colors.white),
                    ),
                  ),
                ),
              ],
            ),
          ),
        ),

        // Panel Inferior de Control de Viaje Activo
        if (_activeOrder != null)
          Positioned(
            bottom: 12,
            left: 12,
            right: 12,
            child: Container(
              padding: const EdgeInsets.all(16),
              decoration: BoxDecoration(
                color: AppConstants.bgCard,
                borderRadius: BorderRadius.circular(20),
                border: Border.all(color: AppConstants.primaryEmerald, width: 1.5),
                boxShadow: const [BoxShadow(color: Colors.black54, blurRadius: 16)],
              ),
              child: Column(
                mainAxisSize: MainAxisSize.min,
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      Text(
                        'Cliente: ${_activeOrder!['client_name'] ?? 'Conductor'}',
                        style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 15),
                      ),
                      if (clientLatLng != null)
                        TextButton.icon(
                          onPressed: () => _openExternalNavigation(clientLatLng.latitude, clientLatLng.longitude),
                          icon: const Icon(Icons.navigation, size: 16, color: AppConstants.secondaryBlue),
                          label: const Text('Waze / Maps', style: TextStyle(fontWeight: FontWeight.bold)),
                        ),
                    ],
                  ),
                  const SizedBox(height: 8),
                  Wrap(
                    spacing: 8,
                    runSpacing: 8,
                    children: [
                      ElevatedButton(
                        onPressed: () => _updateTripStage('IN_TRANSIT_TO_USER'),
                        child: const Text('1. En Camino', style: TextStyle(fontSize: 12)),
                      ),
                      ElevatedButton(
                        onPressed: () => _updateTripStage('ARRIVED_AT_USER'),
                        child: const Text('2. Llegué (Inspección)', style: TextStyle(fontSize: 12)),
                      ),
                      ElevatedButton(
                        onPressed: () => _updateTripStage('IN_TRANSIT_TO_DEST'),
                        child: const Text('3. Remolcando', style: TextStyle(fontSize: 12)),
                      ),
                      ElevatedButton(
                        onPressed: () => _updateTripStage('COMPLETED'),
                        style: ElevatedButton.styleFrom(backgroundColor: AppConstants.primaryEmerald),
                        child: const Text('4. Finalizar y Cobrar ✓', style: TextStyle(fontSize: 12, color: Colors.white, fontWeight: FontWeight.bold)),
                      ),
                    ],
                  ),
                ],
              ),
            ),
          ),
      ],
    );
  }

  @override
  Widget build(BuildContext context) {
    final pages = [
      _buildDispatchMapTab(),
      WalletScreen(token: widget.token, activeOrder: _activeOrder),
      ProfileScreen(token: widget.token, truckData: _truckData, onLogout: _handleLogout),
    ];

    return Scaffold(
      appBar: AppBar(
        backgroundColor: AppConstants.bgCard,
        title: Row(
          children: [
            Container(
              width: 10,
              height: 10,
              decoration: BoxDecoration(
                color: _isOnShift ? AppConstants.primaryEmerald : AppConstants.dangerRed,
                shape: BoxShape.circle,
              ),
            ),
            const SizedBox(width: 8),
            Text(
              _truckData?['license_plate']?.toString() ?? 'JOSEPO DRIVER',
              style: const TextStyle(fontWeight: FontWeight.w900, fontSize: 16),
            ),
          ],
        ),
        actions: [
          TextButton.icon(
            onPressed: _toggleShift,
            icon: Icon(
              _isOnShift ? Icons.power_settings_new : Icons.pause_circle_outline,
              color: _isOnShift ? AppConstants.primaryEmerald : AppConstants.warningAmber,
              size: 18,
            ),
            label: Text(
              _isOnShift ? 'EN TURNO' : 'PAUSADO',
              style: TextStyle(
                color: _isOnShift ? AppConstants.primaryEmerald : AppConstants.warningAmber,
                fontWeight: FontWeight.w900,
                fontSize: 12,
              ),
            ),
          ),
          IconButton(
            onPressed: _handleLogout,
            tooltip: 'Cerrar Sesión',
            icon: const Icon(Icons.logout, color: AppConstants.dangerRed, size: 20),
          ),
        ],
      ),
      body: pages[_currentTabIndex],
      bottomNavigationBar: BottomNavigationBar(
        currentIndex: _currentTabIndex,
        backgroundColor: AppConstants.bgCard,
        selectedItemColor: AppConstants.primaryEmerald,
        unselectedItemColor: AppConstants.textMuted,
        onTap: (idx) => setState(() => _currentTabIndex = idx),
        items: const [
          BottomNavigationBarItem(icon: Icon(Icons.map_outlined), label: 'Mapa & Despacho'),
          BottomNavigationBarItem(icon: Icon(Icons.account_balance_wallet_outlined), label: 'Billetera Escrow'),
          BottomNavigationBarItem(icon: Icon(Icons.verified_user_outlined), label: 'Perfil & Club Vial'),
        ],
      ),
    );
  }
}

