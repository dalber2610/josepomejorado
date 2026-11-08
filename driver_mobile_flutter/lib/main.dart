import 'package:flutter/material.dart';
import 'package:shared_preferences/shared_preferences.dart';
import 'core/constants.dart';
import 'core/api_service.dart';
import 'core/background_location_service.dart';
import 'screens/login_screen.dart';
import 'screens/home_map_screen.dart';

Future<void> main() async {
  WidgetsFlutterBinding.ensureInitialized();
  // Inicializar servicio de GPS en segundo plano (Fase 6)
  try {
    await BackgroundLocationService.initialize();
  } catch (_) {}

  runApp(const JosepoDriverApp());
}

class JosepoDriverApp extends StatelessWidget {
  const JosepoDriverApp({super.key});

  @override
  Widget build(BuildContext context) {
    return MaterialApp(
      title: 'Josepo Driver Pro',
      debugShowCheckedModeBanner: false,
      theme: ThemeData(
        brightness: Brightness.dark,
        scaffoldBackgroundColor: AppConstants.bgMidnight,
        fontFamily: 'Roboto',
        colorScheme: const ColorScheme.dark(
          primary: AppConstants.primaryEmerald,
          secondary: AppConstants.secondaryBlue,
          surface: AppConstants.bgCard,
        ),
      ),
      home: const _SessionBootstrapPage(),
    );
  }
}

class _SessionBootstrapPage extends StatefulWidget {
  const _SessionBootstrapPage();

  @override
  State<_SessionBootstrapPage> createState() => _SessionBootstrapPageState();
}

class _SessionBootstrapPageState extends State<_SessionBootstrapPage> {
  @override
  void initState() {
    super.initState();
    _restoreSession();
  }

  Future<void> _restoreSession() async {
    final prefs = await SharedPreferences.getInstance();
    final savedToken = prefs.getString('josepo_driver_jwt');

    if (savedToken != null && savedToken.isNotEmpty) {
      try {
        final me = await ApiService.getMe(savedToken);
        final user = (me['user'] as Map<String, dynamic>?) ?? {};
        if (!mounted) return;
        Navigator.pushReplacement(
          context,
          MaterialPageRoute(
            builder: (_) => HomeMapScreen(token: savedToken, initialUser: user),
          ),
        );
        return;
      } catch (_) {
        await prefs.remove('josepo_driver_jwt');
      }
    }

    if (!mounted) return;
    Navigator.pushReplacement(
      context,
      MaterialPageRoute(builder: (_) => const LoginScreen()),
    );
  }

  @override
  Widget build(BuildContext context) {
    return const Scaffold(
      backgroundColor: AppConstants.bgMidnight,
      body: Center(
        child: CircularProgressIndicator(color: AppConstants.primaryEmerald),
      ),
    );
  }
}
