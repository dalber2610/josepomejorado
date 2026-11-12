import unittest
import os
import sys
from decimal import Decimal

# Asegurar que el directorio raíz del proyecto esté en el path
sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.config import BaseConfig, ProductionConfig
from app.extensions import db, limiter, DEFAULT_ALLOWED_ORIGINS
from app.models import User, UserRole, ExchangeRateLog
from app.services.currency_service import CurrencyService
from app.utils.rate_limiter import otp_rate_limiter, auth_rate_limiter


class TestPhase7ProductionHardening(unittest.TestCase):
    """
    Pruebas automatizadas para la Fase 7 (Blindaje y Paso a Producción):
    1. Migración a PostgreSQL + PostGIS en docker-compose.yml, init_postgis.sql y app/config.py.
    2. Protección de Endpoints: Flask-Limiter en auth_routes.py y otp_routes.py, CORS restrictivo y validación de esquemas.
    3. Automatización Cambiaria: Cronjob de actualización automática de tasa BCV en currency_service.py.
    """

    def setUp(self):
        self.app = create_app('testing')
        self.client = self.app.test_client()
        self.app_context = self.app.app_context()
        self.app_context.push()
        db.create_all()
        otp_rate_limiter.reset()
        auth_rate_limiter.reset()
        limiter.reset()

        self.user = User(
            email='hardened@josepo.com',
            phone_number='+584145556677',
            full_name='Usuario Blindado',
            role=UserRole.CLIENT
        )
        self.user.set_password('SecurePass2026!')
        db.session.add(self.user)
        db.session.commit()

    def tearDown(self):
        CurrencyService.stop_exchange_rate_cron()
        otp_rate_limiter.reset()
        auth_rate_limiter.reset()
        limiter.reset()
        db.session.remove()
        db.drop_all()
        self.app_context.pop()

    def test_01_postgresql_postgis_configuration_and_docker_compose(self):
        """Verifica que PostgreSQL + PostGIS reemplace a josepo_dev.db en config.py y docker-compose.yml."""
        project_root = os.path.abspath(os.path.join(os.path.dirname(__file__), '..'))
        compose_path = os.path.join(project_root, 'docker-compose.yml')
        postgis_sql_path = os.path.join(project_root, 'scripts', 'init_postgis.sql')
        config_path = os.path.join(project_root, 'app', 'config.py')

        self.assertTrue(os.path.isfile(compose_path))
        self.assertTrue(os.path.isfile(postgis_sql_path))

        with open(compose_path, 'r', encoding='utf-8') as f:
            compose_content = f.read()
        self.assertIn('postgis/postgis:16-3.4', compose_content)
        self.assertIn('init_postgis.sql', compose_content)
        self.assertIn('josepo_cron_fx', compose_content)

        with open(postgis_sql_path, 'r', encoding='utf-8') as f:
            sql_content = f.read()
        self.assertIn('CREATE EXTENSION IF NOT EXISTS postgis;', sql_content)

        with open(config_path, 'r', encoding='utf-8') as f:
            config_content = f.read()
        self.assertNotIn("sqlite:///josepo_dev.db", config_content)
        self.assertTrue(BaseConfig.POSTGRES_DATABASE_URI.startswith('postgresql://'))
        self.assertTrue(ProductionConfig.SQLALCHEMY_DATABASE_URI.startswith('postgresql://'))

    def test_02_rate_limiting_in_auth_and_otp_routes(self):
        """Verifica que Flask-Limiter y Rate Limiter bloqueen fuerza bruta en /api/auth/login y /api/auth/otp/send."""
        # 1. Fuerza bruta en /api/auth/login -> Bloqueo tras 5 intentos fallidos con HTTP 429
        for _ in range(5):
            r = self.client.post('/api/auth/login', json={
                'email': 'hardened@josepo.com',
                'password': 'WrongPassword!'
            })
            self.assertEqual(r.status_code, 401)

        r_blocked_login = self.client.post('/api/auth/login', json={
            'email': 'hardened@josepo.com',
            'password': 'WrongPassword!'
        })
        self.assertEqual(r_blocked_login.status_code, 429)
        self.assertIn('retry_after_seconds', r_blocked_login.get_json())

        # 2. Ráfaga en /api/auth/otp/send -> Bloqueo en la 6ta petición con HTTP 429
        for i in range(5):
            r_otp = self.client.post('/api/auth/otp/send', json={
                'phone_number': f'+58414900110{i}'
            })
            self.assertEqual(r_otp.status_code, 200)

        r_blocked_otp = self.client.post('/api/auth/otp/send', json={
            'phone_number': '+584149001199'
        })
        self.assertEqual(r_blocked_otp.status_code, 429)

    def test_03_restrictive_cors_and_schema_validation(self):
        """Verifica que extensions.py aplique CORS restrictivo y que el validador de esquemas rechace payloads maliciosos."""
        # 1. Origen autorizado recibe cabecera CORS
        res_ok = self.client.get('/api/currency/rate', headers={'Origin': 'https://josepo.ve'})
        self.assertEqual(res_ok.headers.get('Access-Control-Allow-Origin'), 'https://josepo.ve')
        self.assertEqual(res_ok.headers.get('Strict-Transport-Security'), 'max-age=31536000; includeSubDomains')

        # 2. Origen no autorizado NO recibe permiso CORS
        res_unauth = self.client.get('/api/currency/rate', headers={'Origin': 'https://malicious-phishing.org'})
        self.assertIsNone(res_unauth.headers.get('Access-Control-Allow-Origin'))

        # 3. Validación de esquema bloquea tipos incorrectos y payloads XSS
        res_bad_type = self.client.post('/api/auth/otp/send', json={'phone_number': 123456789})
        self.assertEqual(res_bad_type.status_code, 400)

        res_xss = self.client.post('/api/auth/register', json={
            'email': 'nuevo@josepo.com',
            'password': 'ValidPassword123!',
            'full_name': '<script>fetch("https://steal.cookie")</script>',
            'phone_number': '+584142223344'
        })
        self.assertEqual(res_xss.status_code, 400)
        self.assertIn('seguridad', res_xss.get_json()['error'].lower())

    def test_04_currency_automation_cronjob_and_sync_endpoint(self):
        """Verifica la actualización automática de tasa BCV mediante el cronjob y los endpoints de sincronización."""
        # 1. Sincronizar tasa inicial (42.5000 VES/USD)
        res_sync1 = self.client.post('/api/currency/sync', json={
            'custom_rate': '42.5000',
            'source': 'BCV_CRON_TICK_1'
        })
        self.assertEqual(res_sync1.status_code, 200)
        data1 = res_sync1.get_json()['sync']
        self.assertEqual(data1['rate_decimal'], '42.5000')

        # 2. Sincronizar nueva tasa (44.6250 VES/USD -> +5.0% de variación)
        res_sync2 = self.client.post('/api/currency/sync', json={
            'custom_rate': '44.6250',
            'source': 'BCV_CRON_TICK_2'
        })
        self.assertEqual(res_sync2.status_code, 200)
        data2 = res_sync2.get_json()['sync']
        self.assertEqual(data2['rate_decimal'], '44.6250')
        self.assertAlmostEqual(data2['variation_pct'], 5.0, places=1)

        # 3. Verificar estado del cronjob y bitácora en /api/currency/cron-status
        res_status = self.client.get('/api/currency/cron-status')
        self.assertEqual(res_status.status_code, 200)
        status_json = res_status.get_json()
        self.assertGreaterEqual(status_json['cron']['executions_count'], 2)
        self.assertGreaterEqual(len(status_json['recent_logs']), 2)

    def test_05_admin_endpoints_rbac_protection(self):
        """Verifica que /api/admin/* exija JWT con rol ADMIN (Prevención de Broken Access Control - Detalle #1)."""
        # 1. Sin token -> 401 Unauthorized
        res_unauth = self.client.get('/api/admin/kpis')
        self.assertEqual(res_unauth.status_code, 401)

        # 2. Con token de CLIENT -> 403 Forbidden
        res_client_login = self.client.post('/api/auth/login', json={
            'email': 'hardened@josepo.com',
            'password': 'SecurePass2026!'
        })
        client_token = res_client_login.get_json()['access_token']
        res_forbidden = self.client.get('/api/admin/kpis', headers={'Authorization': f'Bearer {client_token}'})
        self.assertEqual(res_forbidden.status_code, 403)

        # 3. Con token de ADMIN -> 200 OK
        admin_user = User(
            email='admin_test@josepo.com',
            phone_number='+584120009999',
            full_name='Admin Test',
            role=UserRole.ADMIN
        )
        admin_user.set_password('AdminPass2026!')
        db.session.add(admin_user)
        db.session.commit()

        res_admin_login = self.client.post('/api/auth/login', json={
            'email': 'admin_test@josepo.com',
            'password': 'AdminPass2026!'
        })
        admin_token = res_admin_login.get_json()['access_token']
        res_admin_ok = self.client.get('/api/admin/kpis', headers={'Authorization': f'Bearer {admin_token}'})
        self.assertEqual(res_admin_ok.status_code, 200)
        self.assertEqual(res_admin_ok.get_json()['status'], 'success')

    def test_06_exact_route_polyline_and_decreasing_eta(self):
        """Verifica que el cálculo de ruta genere la polilínea exacta y que el ETA disminuya conforme la grúa se acerca."""
        from app.services.geo_service import GeoService

        # 1. Calcular ruta entre Chacaíto y Plaza Venezuela (Caracas)
        route_res = self.client.post('/api/geo/route', json={
            'origin': {'lat': 10.4880, 'lng': -66.8792},
            'destination': {'lat': 10.5000, 'lng': -66.9167}
        })
        self.assertEqual(route_res.status_code, 200)
        route_data = route_res.get_json()
        self.assertIn('latlngs', route_data)
        self.assertGreaterEqual(len(route_data['latlngs']), 2)
        self.assertIn('total_seconds', route_data)
        self.assertIn('eta_formatted', route_data)
        self.assertGreater(route_data['total_seconds'], 0)

        # 2. Verificar que el ETA disminuya progresivamente a medida que la distancia decrece
        eta_far = GeoService.calculate_eta(4.5)      # A 4.5 km
        eta_mid = GeoService.calculate_eta(2.0)      # A 2.0 km
        eta_near = GeoService.calculate_eta(0.4)     # A 400 metros
        eta_arrived = GeoService.calculate_eta(0.01) # En el sitio (< 30m)

        self.assertGreater(eta_far['total_seconds'], eta_mid['total_seconds'])
        self.assertGreater(eta_mid['total_seconds'], eta_near['total_seconds'])
        self.assertGreater(eta_near['total_seconds'], eta_arrived['total_seconds'])
        self.assertEqual(eta_arrived['total_seconds'], 0)
        self.assertTrue(eta_arrived['arrived'])
        self.assertIn('En el sitio', eta_arrived['eta_formatted'])


if __name__ == '__main__':
    unittest.main()

