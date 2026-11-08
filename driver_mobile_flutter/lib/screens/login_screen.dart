import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import '../core/constants.dart';
import '../core/api_service.dart';
import 'home_map_screen.dart';

class LoginScreen extends StatefulWidget {
  const LoginScreen({super.key});

  @override
  State<LoginScreen> createState() => _LoginScreenState();
}

class _LoginScreenState extends State<LoginScreen> {
  // 'password' | 'otp'
  String _activeTab = 'password';
  bool _isLoading = false;
  bool _otpSent = false;

  // Controladores Login Contraseña
  String _selectedFleetUnit = 'chofer1@josepo.com';
  final _emailCtrl = TextEditingController(text: 'chofer1@josepo.com');
  final _passwordCtrl = TextEditingController(text: 'ChoferPass2026!');

  // Controladores Login OTP (SMS / WhatsApp)
  final _phoneCtrl = TextEditingController(text: '+584121110001');
  final _otpCodeCtrl = TextEditingController();
  final _fullNameCtrl = TextEditingController();

  final List<Map<String, String>> _demoFleetUnits = const [
    {'email': 'chofer1@josepo.com', 'label': 'GRU-001 • Ford F-350 (Caracas Centro)', 'phone': '+584121110001'},
    {'email': 'chofer2@josepo.com', 'label': 'GRU-002 • Chevrolet C-30 (Maracay)', 'phone': '+584121110002'},
    {'email': 'chofer3@josepo.com', 'label': 'GRU-003 • Iveco Plataforma (Valencia)', 'phone': '+584121110003'},
    {'email': 'chofer4@josepo.com', 'label': 'GRU-004 • Super Duty (Puerto Ordaz)', 'phone': '+584121110004'},
    {'email': 'chofer5@josepo.com', 'label': 'GRU-005 • Dodge RAM 4000 (Caracas Oeste)', 'phone': '+584121110005'},
  ];

  void _showSnack(String msg, {bool isError = false}) {
    if (!mounted) return;
    ScaffoldMessenger.of(context).showSnackBar(
      SnackBar(
        content: Text(msg),
        backgroundColor: isError ? AppConstants.dangerRed : AppConstants.primaryEmerald,
      ),
    );
  }

  Future<void> _completeAuthentication(Map<String, dynamic> data) async {
    final token = data['access_token']?.toString() ?? '';
    final user = (data['user'] as Map<String, dynamic>?) ?? {};
    if (token.isEmpty) {
      _showSnack('No se recibió token de acceso.', isError: true);
      return;
    }

    final prefs = await SharedPreferences.getInstance();
    await prefs.setString('josepo_driver_jwt', token);
    await prefs.setString('josepo_driver_name', user['full_name']?.toString() ?? 'Operador Josepo');

    if (!mounted) return;
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(
        builder: (_) => HomeMapScreen(
          token: token,
          initialUser: user,
        ),
      ),
    );
  }

  Future<void> _handlePasswordLogin() async {
    setState(() => _isLoading = true);
    try {
      final data = await ApiService.loginPassword(_emailCtrl.text, _passwordCtrl.text);
      await _completeAuthentication(data);
    } catch (e) {
      _showSnack(e.toString().replaceFirst('Exception: ', ''), isError: true);
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _handleRequestOtp() async {
    setState(() => _isLoading = true);
    try {
      final data = await ApiService.requestOtpCode(_phoneCtrl.text);
      setState(() => _otpSent = true);
      final demoCode = data['demo_otp_code']?.toString();
      if (demoCode != null && demoCode.isNotEmpty) {
        _otpCodeCtrl.text = demoCode;
        _showSnack('Código OTP enviado. [DEMO: $demoCode]');
      } else {
        _showSnack(data['message']?.toString() ?? 'Código enviado por SMS/WhatsApp.');
      }
    } catch (e) {
      _showSnack(e.toString().replaceFirst('Exception: ', ''), isError: true);
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  Future<void> _handleVerifyOtp() async {
    if (_otpCodeCtrl.text.trim().length != 6) {
      _showSnack('Ingresa el código de 6 dígitos.', isError: true);
      return;
    }
    setState(() => _isLoading = true);
    try {
      final data = await ApiService.verifyOtpCode(
        phoneNumber: _phoneCtrl.text,
        code: _otpCodeCtrl.text,
        fullName: _fullNameCtrl.text,
      );
      await _completeAuthentication(data);
    } catch (e) {
      _showSnack(e.toString().replaceFirst('Exception: ', ''), isError: true);
    } finally {
      if (mounted) setState(() => _isLoading = false);
    }
  }

  @override
  void dispose() {
    _emailCtrl.dispose();
    _passwordCtrl.dispose();
    _phoneCtrl.dispose();
    _otpCodeCtrl.dispose();
    _fullNameCtrl.dispose();
    super.dispose();
  }

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppConstants.bgMidnight,
      body: SafeArea(
        child: Center(
          child: SingleChildScrollView(
            padding: const EdgeInsets.all(24),
            child: Container(
              constraints: const BoxConstraints(maxWidth: 420),
              padding: const EdgeInsets.all(24),
              decoration: BoxDecoration(
                color: AppConstants.bgCard,
                borderRadius: BorderRadius.circular(24),
                border: Border.all(color: Colors.white12),
              ),
              child: Column(
                crossAxisAlignment: CrossAxisAlignment.stretch,
                children: [
                  Row(
                    mainAxisAlignment: MainAxisAlignment.center,
                    children: [
                      Container(
                        padding: const EdgeInsets.symmetric(horizontal: 10, vertical: 4),
                        decoration: BoxDecoration(
                          color: AppConstants.primaryEmerald,
                          borderRadius: BorderRadius.circular(8),
                        ),
                        child: const Text(
                          'PRO v2.0',
                          style: TextStyle(fontWeight: FontWeight.w900, fontSize: 12, color: Colors.white),
                        ),
                      ),
                      const SizedBox(width: 10),
                      const Text(
                        'JOSEPO DRIVER',
                        style: TextStyle(fontSize: 22, fontWeight: FontWeight.w900, letterSpacing: 0.5),
                      ),
                    ],
                  ),
                  const SizedBox(height: 6),
                  const Text(
                    'Consola Satelital de Despacho, Pagos Escrow y SLA',
                    textAlign: TextAlign.center,
                    style: TextStyle(color: AppConstants.textMuted, fontSize: 13),
                  ),
                  const SizedBox(height: 20),

                  // Selector de Pestaña: Contraseña vs SOS OTP
                  Container(
                    padding: const EdgeInsets.all(4),
                    decoration: BoxDecoration(
                      color: AppConstants.bgMidnight,
                      borderRadius: BorderRadius.circular(12),
                    ),
                    child: Row(
                      children: [
                        Expanded(
                          child: GestureDetector(
                            onTap: () => setState(() => _activeTab = 'password'),
                            child: Container(
                              padding: const EdgeInsets.symmetric(vertical: 10),
                              decoration: BoxDecoration(
                                color: _activeTab == 'password' ? AppConstants.bgCard : Colors.transparent,
                                borderRadius: BorderRadius.circular(10),
                              ),
                              child: const Text(
                                '🔑 Unidad / Clave',
                                textAlign: TextAlign.center,
                                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
                              ),
                            ),
                          ),
                        ),
                        Expanded(
                          child: GestureDetector(
                            onTap: () => setState(() => _activeTab = 'otp'),
                            child: Container(
                              padding: const EdgeInsets.symmetric(vertical: 10),
                              decoration: BoxDecoration(
                                color: _activeTab == 'otp' ? AppConstants.bgCard : Colors.transparent,
                                borderRadius: BorderRadius.circular(10),
                              ),
                              child: const Text(
                                '⚡ SMS / WhatsApp OTP',
                                textAlign: TextAlign.center,
                                style: TextStyle(fontWeight: FontWeight.bold, fontSize: 13),
                              ),
                            ),
                          ),
                        ),
                      ],
                    ),
                  ),
                  const SizedBox(height: 20),

                  if (_activeTab == 'password') ...[
                    const Text(
                      'Selector Rápido de Unidad de Flota:',
                      style: TextStyle(fontSize: 12, color: AppConstants.textMuted, fontWeight: FontWeight.bold),
                    ),
                    const SizedBox(height: 6),
                    DropdownButtonFormField<String>(
                      value: _selectedFleetUnit,
                      dropdownColor: AppConstants.bgMidnight,
                      decoration: InputDecoration(
                        filled: true,
                        fillColor: AppConstants.bgMidnight,
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                        contentPadding: const EdgeInsets.symmetric(horizontal: 12, vertical: 12),
                      ),
                      items: _demoFleetUnits
                          .map(
                            (u) => DropdownMenuItem<String>(
                              value: u['email'],
                              child: Text(u['label']!, style: const TextStyle(fontSize: 13)),
                            ),
                          )
                          .toList(),
                      onChanged: (val) {
                        if (val == null) return;
                        setState(() {
                          _selectedFleetUnit = val;
                          _emailCtrl.text = val;
                          _passwordCtrl.text = 'ChoferPass2026!';
                        });
                      },
                    ),
                    const SizedBox(height: 14),
                    TextField(
                      controller: _emailCtrl,
                      keyboardType: TextInputType.emailAddress,
                      decoration: InputDecoration(
                        labelText: 'Correo Electrónico del Operador',
                        prefixIcon: const Icon(Icons.email_outlined),
                        filled: true,
                        fillColor: AppConstants.bgMidnight,
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                    const SizedBox(height: 14),
                    TextField(
                      controller: _passwordCtrl,
                      obscureText: true,
                      decoration: InputDecoration(
                        labelText: 'Contraseña',
                        prefixIcon: const Icon(Icons.lock_outline),
                        filled: true,
                        fillColor: AppConstants.bgMidnight,
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                    const SizedBox(height: 20),
                    ElevatedButton.icon(
                      onPressed: _isLoading ? null : _handlePasswordLogin,
                      icon: const Icon(Icons.login, color: Colors.white),
                      label: _isLoading
                          ? const SizedBox(
                              height: 20,
                              width: 20,
                              child: CircularProgressIndicator(strokeWidth: 2, color: Colors.white),
                            )
                          : const Text(
                              'INGRESAR A CONSOLA DE GRÚA',
                              style: TextStyle(fontWeight: FontWeight.w800, color: Colors.white),
                            ),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppConstants.primaryEmerald,
                        padding: const EdgeInsets.symmetric(vertical: 16),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                      ),
                    ),
                  ] else ...[
                    TextField(
                      controller: _phoneCtrl,
                      keyboardType: TextInputType.phone,
                      decoration: InputDecoration(
                        labelText: 'Teléfono Móvil (+58...)',
                        prefixIcon: const Icon(Icons.phone_android),
                        filled: true,
                        fillColor: AppConstants.bgMidnight,
                        border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                    const SizedBox(height: 12),
                    ElevatedButton.icon(
                      onPressed: _isLoading ? null : _handleRequestOtp,
                      icon: const Icon(Icons.sms_outlined, color: Colors.white),
                      label: Text(
                        _otpSent ? 'REENVIAR CÓDIGO OTP (6 DÍGITOS)' : 'ENVIAR CÓDIGO POR SMS / WHATSAPP',
                        style: const TextStyle(fontWeight: FontWeight.bold, color: Colors.white),
                      ),
                      style: ElevatedButton.styleFrom(
                        backgroundColor: AppConstants.secondaryBlue,
                        padding: const EdgeInsets.symmetric(vertical: 14),
                        shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(12)),
                      ),
                    ),
                    if (_otpSent) ...[
                      const SizedBox(height: 16),
                      TextField(
                        controller: _otpCodeCtrl,
                        maxLength: 6,
                        keyboardType: TextInputType.number,
                        textAlign: TextAlign.center,
                        style: const TextStyle(fontSize: 20, letterSpacing: 6, fontWeight: FontWeight.bold),
                        decoration: InputDecoration(
                          labelText: 'Código de 6 dígitos',
                          counterText: '',
                          filled: true,
                          fillColor: AppConstants.bgMidnight,
                          border: OutlineInputBorder(borderRadius: BorderRadius.circular(12)),
                        ),
                      ),
                      const SizedBox(height: 12),
                      ElevatedButton(
                        onPressed: _isLoading ? null : _handleVerifyOtp,
                        style: ElevatedButton.styleFrom(
                          backgroundColor: AppConstants.primaryEmerald,
                          padding: const EdgeInsets.symmetric(vertical: 16),
                          shape: RoundedRectangleBorder(borderRadius: BorderRadius.circular(14)),
                        ),
                        child: const Text(
                          'VALIDAR CÓDIGO Y ENTRAR',
                          style: TextStyle(fontWeight: FontWeight.w800, color: Colors.white),
                        ),
                      ),
                    ],
                  ],
                ],
              ),
            ),
          ),
        ),
      ),
    );
  }
}

