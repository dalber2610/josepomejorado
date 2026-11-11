from flask import request
from flask_sqlalchemy import SQLAlchemy
from flask_migrate import Migrate
from flask_jwt_extended import JWTManager
from flask_cors import CORS
from flask_socketio import SocketIO
from flask_limiter import Limiter
from flask_limiter.util import get_remote_address

# Lista blanca estricta de orígenes permitidos por defecto (Fase 7 - Sin comodín '*')
DEFAULT_ALLOWED_ORIGINS = [
    'http://localhost:5000',
    'http://127.0.0.1:5000',
    'http://0.0.0.0:5000',
    'https://josepo.ve',
    'https://app.josepo.ve',
    'https://admin.josepo.ve',
]


def get_client_ip() -> str:
    """Obtiene la IP real del cliente respetando proxys inversos (Nginx/Cloudflare)."""
    forwarded = request.headers.get('X-Forwarded-For', '')
    if forwarded:
        return forwarded.split(',')[0].strip()
    return get_remote_address() or '127.0.0.1'


# Instancias compartidas de extensiones
db = SQLAlchemy()
migrate = Migrate()
jwt = JWTManager()
cors = CORS()
limiter = Limiter(
    key_func=get_client_ip,
    default_limits=["500 per day", "120 per minute"],
    storage_uri="memory://",
    headers_enabled=True,
)
socketio = SocketIO(cors_allowed_origins=DEFAULT_ALLOWED_ORIGINS)


def init_security_extensions(app):
    """
    Inicializa Flask-Limiter, CORS restrictivo y cabeceras HTTP de blindaje (Fase 7).
    """
    allowed_origins = app.config.get('CORS_ALLOWED_ORIGINS', DEFAULT_ALLOWED_ORIGINS)

    # 1. Configurar CORS restrictivo solo hacia dominios autorizados
    cors.init_app(
        app,
        resources={
            r"/api/*": {
                "origins": allowed_origins,
                "methods": ["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
                "allow_headers": [
                    "Content-Type",
                    "Authorization",
                    "X-Webhook-Signature",
                    "X-Idempotency-Key",
                ],
                "expose_headers": [
                    "X-RateLimit-Limit",
                    "X-RateLimit-Remaining",
                    "X-RateLimit-Reset",
                    "Retry-After",
                ],
                "supports_credentials": True,
                "max_age": 600,
            }
        },
    )

    # 2. Inicializar Flask-Limiter para protección contra fuerza bruta y DDoS
    limiter.init_app(app)

    # 3. Inicializar SocketIO con lista blanca de orígenes
    socketio.init_app(app, cors_allowed_origins=allowed_origins)

    # 4. Inyectar cabeceras de seguridad HTTP en cada respuesta (Hardening OWASP + Permiso de Tiles de Mapa)
    @app.after_request
    def apply_security_headers(response):
        response.headers['X-Content-Type-Options'] = 'nosniff'
        response.headers['X-Frame-Options'] = 'SAMEORIGIN'
        response.headers['X-XSS-Protection'] = '1; mode=block'
        response.headers['Referrer-Policy'] = 'strict-origin-when-cross-origin'
        response.headers['Strict-Transport-Security'] = 'max-age=31536000; includeSubDomains'
        response.headers['Content-Security-Policy'] = (
            "default-src 'self' http: https: data: blob: 'unsafe-inline' 'unsafe-eval'; "
            "img-src 'self' data: blob: https://*.basemaps.cartocdn.com https://tile.openstreetmap.org https://*.tile.openstreetmap.org http: https:; "
            "connect-src 'self' ws: wss: http: https:;"
        )
        return response
