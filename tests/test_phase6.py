import unittest
import os
import sys
from pathlib import Path

# Asegurar que el directorio raíz del proyecto esté en el path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.models import User, UserRole, TowTruck


class TestPhase6FlutterMobileCompleteness(unittest.TestCase):
    """
    Suite de verificación de la Fase 6:
    1. Arquitectura modular de pantallas en Flutter (`login_screen.dart`, `home_map_screen.dart`,
       `wallet_screen.dart`, `profile_screen.dart`).
    2. Configuración nativa de GPS en Segundo Plano (`AndroidManifest.xml`, `Info.plist`,
       `pubspec.yaml`, `background_location_service.dart`, `socket_service.dart`).
    3. Integración completa de los endpoints REST consumidos por `ApiService` en Flutter.
    """

    def setUp(self):
        self.project_root = Path(__file__).resolve().parent.parent
        self.flutter_root = self.project_root / 'driver_mobile_flutter'

        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()

        self.driver = User(
            email='flutter_driver@josepo.com',
            phone_number='+584125550001',
            full_name='Chofer Flutter Nativo',
            role=UserRole.DRIVER
        )
        self.driver.set_password('Flutter2026!')
        db.session.add(self.driver)
        db.session.commit()

        self.truck = TowTruck(
            license_plate='FLT-006',
            brand_model='Ford F-350 Super Duty',
            driver_id=self.driver.id,
            current_lat=10.5000,
            current_lng=-66.9167,
            is_available=True,
            is_active=True
        )
        db.session.add(self.truck)
        db.session.commit()

    def tearDown(self):
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_flutter_screens_and_background_gps_files_exist(self):
        """Verifica la existencia y estructura de todos los archivos de la Fase 6 en Flutter."""
        required_files = [
            self.flutter_root / 'pubspec.yaml',
            self.flutter_root / 'android' / 'app' / 'src' / 'main' / 'AndroidManifest.xml',
            self.flutter_root / 'ios' / 'Runner' / 'Info.plist',
            self.flutter_root / 'lib' / 'main.dart',
            self.flutter_root / 'lib' / 'core' / 'constants.dart',
            self.flutter_root / 'lib' / 'core' / 'api_service.dart',
            self.flutter_root / 'lib' / 'core' / 'background_location_service.dart',
            self.flutter_root / 'lib' / 'core' / 'socket_service.dart',
            self.flutter_root / 'lib' / 'screens' / 'login_screen.dart',
            self.flutter_root / 'lib' / 'screens' / 'home_map_screen.dart',
            self.flutter_root / 'lib' / 'screens' / 'wallet_screen.dart',
            self.flutter_root / 'lib' / 'screens' / 'profile_screen.dart',
        ]
        for file_path in required_files:
            self.assertTrue(file_path.exists(), f"Archivo requerido no encontrado: {file_path}")

        # Verificar dependencias clave en pubspec.yaml
        pubspec_text = (self.flutter_root / 'pubspec.yaml').read_text(encoding='utf-8')
        self.assertIn('geolocator:', pubspec_text)
        self.assertIn('flutter_background_service:', pubspec_text)
        self.assertIn('flutter_map:', pubspec_text)

        # Verificar permisos de segundo plano en AndroidManifest.xml e Info.plist
        manifest_text = (
            self.flutter_root / 'android' / 'app' / 'src' / 'main' / 'AndroidManifest.xml'
        ).read_text(encoding='utf-8')
        self.assertIn('ACCESS_BACKGROUND_LOCATION', manifest_text)
        self.assertIn('FOREGROUND_SERVICE_LOCATION', manifest_text)

        plist_text = (self.flutter_root / 'ios' / 'Runner' / 'Info.plist').read_text(encoding='utf-8')
        self.assertIn('NSLocationAlwaysAndWhenInUseUsageDescription', plist_text)
        self.assertIn('UIBackgroundModes', plist_text)

    def test_flutter_driver_end_to_end_api_flow(self):
        """Verifica el flujo completo que ejecuta la app Flutter desde login hasta cobro Escrow y puntos."""
        # 1. Login desde LoginScreen
        res_login = self.client.post(
            '/api/auth/login',
            json={'email': 'flutter_driver@josepo.com', 'password': 'Flutter2026!'}
        )
        self.assertEqual(res_login.status_code, 200)
        token = res_login.get_json()['access_token']
        headers = {'Authorization': f'Bearer {token}'}

        # 2. Consultar unidad en HomeMapScreen / ProfileScreen
        res_truck = self.client.get('/api/driver/my-truck', headers=headers)
        self.assertEqual(res_truck.status_code, 200)
        self.assertEqual(res_truck.get_json()['truck']['license_plate'], 'FLT-006')

        # 3. Simular pedido SOS y aceptarlo en HomeMapScreen
        res_sim = self.client.post('/api/driver/simulate-request', headers=headers)
        self.assertEqual(res_sim.status_code, 201)
        req_id = res_sim.get_json()['request']['id']

        res_accept = self.client.post(
            '/api/driver/respond-offer',
            headers=headers,
            json={'request_id': req_id, 'accepted': True}
        )
        self.assertEqual(res_accept.status_code, 200)

        # 4. Transmitir telemetría en segundo plano (BackgroundLocationService -> /api/driver/telemetry)
        res_tel = self.client.post(
            '/api/driver/telemetry',
            headers=headers,
            json={'lat': 10.5005, 'lng': -66.9165, 'is_mocked': False}
        )
        self.assertEqual(res_tel.status_code, 200)

        # 5. Finalizar servicio y verificar acreditación de +50 puntos en ProfileScreen
        res_complete = self.client.post(
            '/api/driver/update-trip-status',
            headers=headers,
            json={'request_id': req_id, 'status': 'COMPLETED'}
        )
        self.assertEqual(res_complete.status_code, 200)

        res_gam = self.client.get('/api/gamification/profile', headers=headers)
        self.assertEqual(res_gam.status_code, 200)
        self.assertEqual(res_gam.get_json()['points_balance'], 50)


if __name__ == '__main__':
    unittest.main()

