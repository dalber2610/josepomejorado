import os
import sqlite3
from flask import Flask, jsonify, render_template
from sqlalchemy import event
from sqlalchemy.engine import Engine
from app.config import config_by_name, ProductionConfig
from app.extensions import db, migrate, jwt, init_security_extensions
from app.api import register_api_blueprints
import logging


@event.listens_for(Engine, "connect")
def _set_sqlite_concurrency_pragmas(dbapi_connection, connection_record):
    """
    Mitigación de concurrencia en entornos locales/pruebas con SQLite:
    Activa Write-Ahead Logging (WAL) y busy_timeout de 10s.
    En producción se utiliza estrictamente PostgreSQL 16 + PostGIS 3.4 (Fase 7).
    """
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA journal_mode=WAL;")
        cursor.execute("PRAGMA synchronous=NORMAL;")
        cursor.execute("PRAGMA busy_timeout=10000;")
        cursor.execute("PRAGMA foreign_keys=ON;")
        cursor.close()


def create_app(config_name: str = None) -> Flask:
    """Fábrica de aplicaciones Flask (Application Factory Pattern - Fase 7 Hardened)."""
    if config_name is None:
        config_name = os.getenv('FLASK_ENV', 'development')

    app = Flask(__name__, template_folder='templates', static_folder='static')
    config_class = config_by_name.get(config_name, config_by_name['development'])

    if config_class is ProductionConfig:
        ProductionConfig.validate()

    app.config.from_object(config_class)

    # Si es PostgreSQL/PostGIS, remover connect_args exclusivos de SQLite
    db_uri = app.config.get('SQLALCHEMY_DATABASE_URI', '')
    if not db_uri.startswith('sqlite'):
        engine_opts = dict(app.config.get('SQLALCHEMY_ENGINE_OPTIONS', {}))
        engine_opts.pop('connect_args', None)
        app.config['SQLALCHEMY_ENGINE_OPTIONS'] = engine_opts

    # Configuración de Logging profesional
    logging.basicConfig(
        level=logging.INFO if not app.config.get('DEBUG') else logging.DEBUG,
        format='[%(asctime)s] %(levelname)s in %(module)s: %(message)s'
    )

    # Inicializar extensiones de base de datos, JWT y blindaje de seguridad (CORS + Flask-Limiter + Headers)
    db.init_app(app)
    migrate.init_app(app, db)
    jwt.init_app(app)
    init_security_extensions(app)

    # Middleware CSP explícito para permitir Leaflet, Socket.IO, Google Fonts y Tiles de CartoDB / OpenStreetMap
    @app.after_request
    def set_security_headers(response):
        csp = (
            "default-src 'self'; "
            "script-src 'self' 'unsafe-inline' 'unsafe-eval' https://unpkg.com https://cdn.socket.io; "
            "style-src 'self' 'unsafe-inline' https://unpkg.com https://fonts.googleapis.com; "
            "font-src 'self' https://fonts.gstatic.com data:; "
            "img-src 'self' data: blob: https://*.basemaps.cartocdn.com https://*.tile.openstreetmap.org https://tile.openstreetmap.org https://unpkg.com; "
            "connect-src 'self' ws: wss: http: https:;"
        )
        response.headers['Content-Security-Policy'] = csp
        return response

    # Importar sockets
    from app import sockets  # noqa: F401

    # Registrar rutas API
    register_api_blueprints(app)

    # Iniciar Cronjob de Automatización Cambiaria BCV si está habilitado (Fase 7)
    if app.config.get('CURRENCY_CRON_ENABLED', False):
        from app.services.currency_service import CurrencyService
        CurrencyService.start_exchange_rate_cron(
            app,
            interval_minutes=app.config.get('CURRENCY_CRON_INTERVAL_MINUTES', 30)
        )

    # Manejo de Errores Globales Seguro (Sin filtrar excepciones internas)
    @app.errorhandler(400)
    def handle_bad_request(e):
        return jsonify({'error': 'Petición inválida o parámetros incorrectos.'}), 400

    @app.errorhandler(401)
    def handle_unauthorized(e):
        return jsonify({'error': 'No autorizado. Token requerido o vencido.'}), 401

    @app.errorhandler(403)
    def handle_forbidden(e):
        return jsonify({'error': 'Acceso prohibido para este recurso.'}), 403

    @app.errorhandler(404)
    def handle_not_found(e):
        return jsonify({'error': 'Recurso o endpoint no encontrado.'}), 404

    @app.errorhandler(429)
    def handle_rate_limit(e):
        return jsonify({
            'error': 'Demasiadas solicitudes. Por favor espere antes de reintentar.',
            'retry_after_seconds': 60
        }), 429

    @app.errorhandler(500)
    def handle_server_error(e):
        app.logger.error(f"Error 500 no controlado: {e}")
        return jsonify({'error': 'Error interno del servidor. Por favor intente más tarde.'}), 500

    # Endpoint de Verificación de Salud (Health Check)
    @app.route('/health')
    def health_check():
        from app.services.currency_service import CurrencyService
        return jsonify({
            'status': 'healthy',
            'environment': config_name,
            'version': '7.0.0-production-hardened',
            'postgis_configured': bool(app.config.get('POSTGIS_ENABLED', True)),
            'currency_cron': CurrencyService.get_cron_status()
        }), 200

    # Aplicaciones Web Móviles y Consolas (Frontends de Fases 1 a 7)
    @app.route('/driver')
    def driver_console():
        return render_template('driver.html')

    @app.route('/client')
    def client_console():
        return render_template('client.html')

    @app.route('/admin')
    def admin_dashboard():
        return render_template('admin.html')

    # Ruta raíz informativa
    @app.route('/')
    def root():
        return jsonify({
            'service': 'Josepo API - Sistema de Grúas y Asistencia Vial',
            'version': '7.0.0-production-hardened',
            'status': 'operational',
            'frontends': {
                'driver_app': '/driver',
                'client_app': '/client',
                'admin_operations_hub': '/admin'
            },
            'endpoints': {
                'auth': '/api/auth',
                'auth_otp': '/api/auth/otp',
                'payments': '/api/payments',
                'contracts': '/api/contracts',
                'gamification_sos': '/api/gamification',
                'admin': '/api/admin',
                'driver': '/api/driver',
                'geo': '/api/geo',
                'tows': '/api/tows',
                'traffic': '/api/traffic',
                'currency': '/api/currency',
                'health': '/health'
            }
        }), 200

    return app
