import 'package:flutter/material.dart';
import '../core/constants.dart';
import '../core/api_service.dart';

/// Pantalla de Billetera, Liquidaciones Escrow 85/15 y Directorio Pago Móvil (Fase 6).
/// Cumple estrictamente la regla financiera: todos los cálculos acumulados operan sobre centavos enteros (`int`).
class WalletScreen extends StatefulWidget {
  final String token;
  final Map<String, dynamic>? activeOrder;

  const WalletScreen({
    super.key,
    required this.token,
    this.activeOrder,
  });

  @override
  State<WalletScreen> createState() => _WalletScreenState();
}

class _WalletScreenState extends State<WalletScreen> {
  double _bcvRate = 42.50;
  List<dynamic> _banks = [];
  bool _loading = true;

  @override
  void initState() {
    super.initState();
    _loadFinancialData();
  }

  Future<void> _loadFinancialData() async {
    setState(() => _loading = true);
    try {
      final rateData = await ApiService.getExchangeRate();
      final banksList = await ApiService.getSupportedBanks();
      if (!mounted) return;
      setState(() {
        _bcvRate = (rateData['rate'] as num?)?.toDouble() ?? 42.50;
        _banks = banksList;
      });
    } catch (_) {
    } finally {
      if (mounted) setState(() => _loading = false);
    }
  }

  String _formatCents(int cents) {
    final whole = cents ~/ 100;
    final rem = (cents % 100).abs().toString().padLeft(2, '0');
    return '$whole.$rem';
  }

  @override
  Widget build(BuildContext context) {
    // Cálculo estricto en centavos enteros para la orden activa si existe
    final pricing = widget.activeOrder?['pricing'] as Map<String, dynamic>?;
    final int totalUsdCents = pricing != null
        ? ((pricing['cost_usd'] as num? ?? 0) * 100).round()
        : ((widget.activeOrder?['cost_usd'] as num? ?? 0) * 100).round();
    final int totalVesCents = pricing != null
        ? ((pricing['cost_ves'] as num? ?? 0) * 100).round()
        : ((widget.activeOrder?['cost_ves'] as num? ?? 0) * 100).round();

    final int driverNetUsdCents = (totalUsdCents * 85) ~/ 100;
    final int platformFeeUsdCents = totalUsdCents - driverNetUsdCents;
    final int driverNetVesCents = (totalVesCents * 85) ~/ 100;

    return RefreshIndicator(
      onRefresh: _loadFinancialData,
      child: ListView(
        padding: const EdgeInsets.all(16),
        children: [
          // Tarjeta Principal de Billetera y Tasa BCV
          Container(
            padding: const EdgeInsets.all(20),
            decoration: BoxDecoration(
              gradient: const LinearGradient(
                colors: [Color(0xFF0F172A), Color(0xFF1E293B)],
                begin: Alignment.topLeft,
                end: Alignment.bottomRight,
              ),
              borderRadius: BorderRadius.circular(20),
              border: Border.all(color: AppConstants.primaryEmerald.withOpacity(0.5)),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                Row(
                  mainAxisAlignment: MainAxisAlignment.spaceBetween,
                  children: [
                    const Text(
                      'BILLETERA ESCROW DEL CONDUCTOR',
                      style: TextStyle(
                        fontSize: 12,
                        fontWeight: FontWeight.w800,
                        color: AppConstants.primaryEmerald,
                      ),
                    ),
                    Container(
                      padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                      decoration: BoxDecoration(
                        color: AppConstants.bgMidnight,
                        borderRadius: BorderRadius.circular(8),
                        border: Border.all(color: Colors.white12),
                      ),
                      child: Text(
                        'BCV: ${_bcvRate.toStringAsFixed(2)} VES/USD',
                        style: const TextStyle(fontSize: 11, fontWeight: FontWeight.bold, color: AppConstants.primaryEmerald),
                      ),
                    ),
                  ],
                ),
                const SizedBox(height: 14),
                Text(
                  totalUsdCents > 0
                      ? '${_formatCents(driverNetUsdCents)} USD en Garantía Activa'
                      : 'Sin Garantías Retenidas en Curso',
                  style: const TextStyle(fontSize: 22, fontWeight: FontWeight.w900),
                ),
                const SizedBox(height: 4),
                Text(
                  totalVesCents > 0
                      ? 'Equivalente neto (85%): ${_formatCents(driverNetVesCents)} VES'
                      : 'Tus liquidaciones se acreditan automáticamente al completar cada remolque.',
                  style: const TextStyle(fontSize: 13, color: AppConstants.textMuted),
                ),
              ],
            ),
          ),
          const SizedBox(height: 16),

          // Desglose de Esquema 85% / 15%
          Container(
            padding: const EdgeInsets.all(16),
            decoration: BoxDecoration(
              color: AppConstants.bgCard,
              borderRadius: BorderRadius.circular(16),
              border: Border.all(color: Colors.white10),
            ),
            child: Column(
              crossAxisAlignment: CrossAxisAlignment.start,
              children: [
                const Row(
                  children: [
                    Icon(Icons.shield_outlined, color: AppConstants.primaryEmerald, size: 20),
                    SizedBox(width: 8),
                    Text(
                      'Esquema de Protección Escrow (85 / 15)',
                      style: TextStyle(fontWeight: FontWeight.w800, fontSize: 15),
                    ),
                  ],
                ),
                const SizedBox(height: 10),
                const Text(
                  '• 85% Neto para el Operador: Se libera de inmediato a tu cuenta al marcar "Finalizar Servicio".\n'
                  '• 15% Comisión Josepo: Cubre despacho satelital, pasarela bancaria y auditoría legal SHA-256.',
                  style: TextStyle(fontSize: 12, color: AppConstants.textMuted, height: 1.5),
                ),
                if (totalUsdCents > 0) ...[
                  const Divider(height: 24),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text('Tarifa Bruta de la Orden:', style: TextStyle(fontSize: 13, color: AppConstants.textMuted)),
                      Text('${_formatCents(totalUsdCents)} USD', style: const TextStyle(fontWeight: FontWeight.bold)),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text('Tu Ganancia Neta (85%):', style: TextStyle(fontSize: 13, color: AppConstants.primaryEmerald)),
                      Text(
                        '${_formatCents(driverNetUsdCents)} USD (${_formatCents(driverNetVesCents)} VES)',
                        style: const TextStyle(fontWeight: FontWeight.w900, color: AppConstants.primaryEmerald),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  Row(
                    mainAxisAlignment: MainAxisAlignment.spaceBetween,
                    children: [
                      const Text('Comisión Plataforma (15%):', style: TextStyle(fontSize: 12, color: AppConstants.textMuted)),
                      Text('${_formatCents(platformFeeUsdCents)} USD', style: const TextStyle(fontSize: 12)),
                    ],
                  ),
                ],
              ],
            ),
          ),
          const SizedBox(height: 16),

          // Directorio Nacional de Bancos Habilitados para Pago Móvil
          const Text(
            'Directorio Interbancario Pago Móvil Habilitado',
            style: TextStyle(fontWeight: FontWeight.w800, fontSize: 14),
          ),
          const SizedBox(height: 8),
          if (_loading)
            const Center(child: Padding(padding: EdgeInsets.all(20), child: CircularProgressIndicator()))
          else
            ..._banks.take(10).map(
                  (b) => Card(
                    color: AppConstants.bgCard,
                    margin: const EdgeInsets.only(bottom: 8),
                    shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                    child: ListTile(
                      dense: true,
                      leading: Container(
                        padding: const EdgeInsets.symmetric(horizontal: 8, vertical: 4),
                        decoration: BoxDecoration(
                          color: AppConstants.bgMidnight,
                          borderRadius: BorderRadius.circular(6),
                        ),
                        child: Text(
                          b['code']?.toString() ?? '',
                          style: const TextStyle(fontWeight: FontWeight.bold, color: AppConstants.secondaryBlue),
                        ),
                      ),
                      title: Text(b['name']?.toString() ?? '', style: const TextStyle(fontSize: 13, fontWeight: FontWeight.w600)),
                      trailing: const Icon(Icons.verified, size: 16, color: AppConstants.primaryEmerald),
                    ),
                  ),
                ),
        ],
      ),
    );
  }
}

