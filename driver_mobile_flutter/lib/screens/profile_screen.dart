import 'package:flutter/material.dart';
import 'package:geolocator/geolocator.dart';
import '../core/constants.dart';
import '../core/api_service.dart';

/// Pantalla de Perfil del Operador, Estado de GPS en Segundo Plano y Club Guardián Vial (Fase 6).
class ProfileScreen extends StatefulWidget {
  final String token;
  final Map<String, dynamic>? truckData;
  final VoidCallback onLogout;

  const ProfileScreen({
    super.key,
    required this.token,
    required this.truckData,
    required this.onLogout,
  });

  @override
  State<ProfileScreen> createState() => _ProfileScreenState();
}

class _ProfileScreenState extends State<ProfileScreen> {
  Map<String, dynamic>? _gamificationProfile;
  List<dynamic> _rewards = [];
  LocationPermission _locationPermission = LocationPermission.unableToDetermine;
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadProfileData();
  }

  Future<void> _loadProfileData() async {
    setState(() => _loading = true);
    try {
      final perm = await Geolocator.checkPermission();
      final gamProfile = await ApiService.getGamificationProfile(widget.token);
      final rewardsList = await ApiService.getPartnerRewards();
      if (!mounted) return;
      setState(() {
        _locationPermission = perm;
        _gamificationProfile = gamProfile;
        _rewards = rewardsList;
      });
    } catch (_) {
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  Future<void> _redeemReward(int rewardId) async {
    try {
      final res = await ApiService.redeemReward(widget.token, rewardId);
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(res['message']?.toString() ?? 'Canje exitoso'),
          backgroundColor: AppConstants.primaryEmerald,
        ),
      );
      await _loadProfileData();
    } catch (e) {
      if (!mounted) return;
      ScaffoldMessenger.of(context).showSnackBar(
        SnackBar(
          content: Text(e.toString().replaceFirst('Exception: ', '')),
          backgroundColor: AppConstants.dangerRed,
        ),
      );
    }
  }

  @override
  Widget build(BuildContext context) {
    final pts = _gamificationProfile?['points_balance'] ?? 0;
    final lifetimePts = _gamificationProfile?['lifetime_points'] ?? 0;
    final repLevel = _gamificationProfile?['reputation_level'] ?? 'BRONCE';
    final isAlwaysGranted = _locationPermission == LocationPermission.always;

    return RefreshIndicator(
      onRefresh: _loadProfileData,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Ficha de la Unidad de Grúa
          Container(
            padding: const EdgeInsets.all(18),
            decoration: BoxDecoration(
              color: AppConstants.bgCard,
              borderRadius: BorderRadius.circular(18),
              border: Border.all(color: Colors.white12),
            ),
            child: Row(
              children: [
                Container(
                  width: 54,
                  height: 54,
                  decoration: BoxDecoration(
                    color: AppConstants.primaryEmerald.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(14),
                  ),
                  child: const Icon(Icons.fire_truck, color: AppConstants.primaryEmerald, size: 30),
                ),
                const SizedBox(width: 14),
                Expanded(
                  child: Column(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Text(
                        widget.truckData?['license_plate']?.toString() ?? 'UNIDAD ASIGNADA',
                        style: const TextStyle(fontSize: 18, fontWeight: FontWeight.w900, color: AppConstants.primaryEmerald),
                      ),
                      Text(
                        widget.truckData?['brand_model']?.toString() ?? 'Plataforma de Auxilio Vial',
                        style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600),
                      ),
                      Text(
                        'Operador: ${widget.truckData?['driver_name'] ?? 'Conductor Josepo'}',
                        style: const TextStyle(fontSize: 12, color: AppConstants.textMuted),
                      ),
                    ],
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),

          // Estado de Permiso Nativo de GPS en Segundo Plano (Fase 6)
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: AppConstants.bgCard,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(
                color: isAlwaysGranted ? AppConstants.primaryEmerald : AppConstants.warningAmber,
              ),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  children: [
                    Icon(
                      isAlwaysGranted ? Icons.gps_fixed : Icons.gps_not_fixed,
                      color: isAlwaysGranted ? AppConstants.primaryEmerald : AppConstants.warningAmber,
                    ),
                    const SizedBox(width: 8),
                    Expanded(
                      child: Text(
                        isAlwaysGranted
                            ? 'GPS en Segundo Plano: Activo (Always-On)'
                            : 'GPS en Segundo Plano: Permiso Parcial',
                        style: const TextStyle(fontWeight: FontWeight.w800, fontSize: 14),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 6),
                const Text(
                  'Permite seguir enviando tus coordenadas a la central y al cliente incluso con la pantalla apagada o mientras usas Waze / Google Maps.',
                  style: TextStyle(fontSize: 12, color: AppConstants.textMuted),
                ),
                const SizedBox(height: 10),
                OutlinedButton.icon(
                  onPressed: () async {
                    await Geolocator.openAppSettings();
                    await _loadProfileData();
                  },
                  icon: const Icon(Icons.settings_outlined, size: 16),
                  label: const Text('Verificar Permiso "Permitir Siempre" en Ajustes'),
                ),
              ],
            ),
          ),
          const SizedBox(height: 14),

          // Tarjeta Fase 5: Puntos y Nivel de Reputación Vial
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [Color(0xFF0F172A), Color(0xFF1E293B)],
              ),
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: AppConstants.secondaryBlue.withOpacity(0.5)),
            ),
            child: Row(
              mainAxisAlignment: MainAxisAlignment.spaceBetween,
              children: [
                Column(
                  crossAxisAlignment: CrossAxisAlignment.start,
                  children: [
                    const Text(
                      'CLUB GUARDIÁN VIAL',
                      style: TextStyle(fontSize: 11, fontWeight: FontWeight.w800, color: AppConstants.secondaryBlue),
                    ),
                    const SizedBox(height: 4),
                    Text(
                      '$pts Puntos Disponibles',
                      style: const TextStyle(fontSize: 20, fontWeight: FontWeight.w900),
                    ),
                    Text(
                      'Acumulado histórico: $lifetimePts pts',
                      style: const TextStyle(fontSize: 12, color: AppConstants.textMuted),
                    ),
                  ],
                ),
                Container(
                  padding: const EdgeInsets.symmetric(horizontal: 12, vertical: 8),
                  decoration: BoxDecoration(
                    color: AppConstants.warningAmber.withOpacity(0.15),
                    borderRadius: BorderRadius.circular(12),
                    border: Border.all(color: AppConstants.warningAmber),
                  ),
                  child: Text(
                    '🏅 $repLevel',
                    style: const TextStyle(fontWeight: FontWeight.w900, color: AppConstants.warningAmber),
                  ),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),

          const Text(
            'Catálogo de Talleres y Comercios Aliados (Canje)',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 14),
          ),
          const SizedBox(height: 8),
          if (_loading)
            const Center(child: Padding(padding: EdgeInsets.all(16), child: CircularProgressIndicator()))
          else
            ..._rewards.map(
              (r) => Card(
                color: AppConstants.bgCard,
                margin: const EdgeInsets.only(bottom: 10),
                shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                child: ListTile(
                  title: Text(
                    r['title']?.toString() ?? '',
                    style: const TextStyle(fontSize: 13, fontWeight: FontWeight.bold),
                  ),
                  subtitle: Text(
                    '${r['partner_name']} • ${r['city_location']}',
                    style: const TextStyle(fontSize: 11, color: AppConstants.textMuted),
                  ),
                  trailing: ElevatedButton(
                    onPressed: () => _redeemReward(r['id'] as int),
                    style: ElevatedButton.styleFrom(
                      backgroundColor: AppConstants.primaryEmerald,
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 8),
                    ),
                    child: Text(
                      '${r['points_cost']} pts',
                      style: const TextStyle(fontSize: 12, fontWeight: FontWeight.bold, color: Colors.white),
                    ),
                  ),
                ),
              ),
            ),

          const SizedBox(height: 20),
          ElevatedButton.icon(
            onPressed: widget.onLogout,
            icon: const Icon(Icons.logout, color: Colors.white),
            label: const Text(
              'CERRAR SESIÓN DEL CONDUCTOR',
              style: TextStyle(fontWeight: FontWeight.w800, color: Colors.white),
            ),
            style: ElevatedButton.styleFrom(
              backgroundColor: AppConstants.dangerRed,
              padding: const EdgeInsets.symmetric(vertical: 15),
              shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
            ),
          ),
        ],
      ),
    );
  }
}

