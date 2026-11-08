import os
from datetime import timedelta
from dotenv import load_dotenv

# Cargar variables desde el archivo .env
load_dotenv()


def _parse_cors_origins() -> list[str]:
    raw = os.getenv(
        'CORS_ALLOWED_ORIGINS',
        'http://localhost:5000,http://127.0.0.1:5000,https://josepo.ve,https://app.josepo.ve,https://admin.josepo.ve'
    )
    return [origin.strip() for origin in raw.split(',') if origin.strip()]


def _can_connect_postgres(uri: str) -> bool:
    """
    Verifica si el driver PostgreSQL (psycopg2 / psycopg) está instalado y si el contenedor
    PostGIS acepta la conexión con las credenciales configuradas.
    """
    try:
        import psycopg2  # noqa: F401
        conn = psycopg2.connect(uri, connect_timeout=1)
        conn.close()
        return True
    except Exception:
        return False


class BaseConfig:
    """Configuración base compartida (Blindaje Fase 7 - PostgreSQL + PostGIS)."""
    # Claves secretas
    SECRET_KEY = os.getenv('SECRET_KEY', 'insecure-dev-key-change-in-production-12345678')
    JWT_SECRET_KEY = os.getenv('JWT_SECRET_KEY', 'insecure-jwt-key-change-in-production-12345678')
    WEBHOOK_SECRET = os.getenv('WEBHOOK_SECRET', 'dev-webhook-hmac-secret-key-2026')
    JWT_ACCESS_TOKEN_EXPIRES = timedelta(hours=8)

    # Base de datos primaria: PostgreSQL 16 + PostGIS 3.4 (Reemplazo de josepo_dev.db)
    POSTGRES_DATABASE_URI = os.getenv(
        'POSTGRES_DATABASE_URI',
        'postgresql://josepo_user:josepo_secure_password_2026@localhost:5432/josepo_db'
    )
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', POSTGRES_DATABASE_URI)
    POSTGIS_ENABLED = True
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
    }

    # Redis / Broker & Flask-Limiter (Fase 7)
    REDIS_URL = os.getenv('REDIS_URL', 'redis://localhost:6379/0')
    RATELIMIT_ENABLED = True
    RATELIMIT_STORAGE_URI = os.getenv('RATELIMIT_STORAGE_URI', 'memory://')
    RATELIMIT_DEFAULT = "200 per day;60 per minute"
    RATELIMIT_HEADERS_ENABLED = True

    # Cabeceras CORS Restrictivas (Fase 7 - Sin comodín '*' abierto)
    CORS_ALLOWED_ORIGINS = _parse_cors_origins()

    # MapQuest / Proveedores externos (Exclusivo de servidor)
    MAPQUEST_API_KEY = os.getenv('MAPQUEST_API_KEY', '')

    # Seguridad de Telemetría y Anti-Spoofing GPS (Hallazgos B y E)
    MAX_SPEED_KMH_ANTI_SPOOF = float(os.getenv('MAX_SPEED_KMH_ANTI_SPOOF', '180.0'))
    TELEMETRY_DB_WRITE_INTERVAL_SEC = int(os.getenv('TELEMETRY_DB_WRITE_INTERVAL_SEC', '10'))

    # Moneda, Finanzas & Automatización Cambiaria BCV (Fase 7)
    BCV_API_URL = os.getenv('BCV_API_URL', 'https://ve.dolarapi.com/v1/dolares/oficial')
    BCV_SECONDARY_API_URL = os.getenv('BCV_SECONDARY_API_URL', 'https://pydolarvenezuela-api.vercel.app/api/v1/dollar?page=bcv')
    CURRENCY_CRON_ENABLED = os.getenv('CURRENCY_CRON_ENABLED', 'true').lower() == 'true'
    CURRENCY_CRON_INTERVAL_MINUTES = int(os.getenv('CURRENCY_CRON_INTERVAL_MINUTES', '30'))
    BASE_RATE_VES_CENTS = int(os.getenv('BASE_RATE_VES_CENTS', '50000'))      # 500.00 VES
    RATE_PER_KM_VES_CENTS = int(os.getenv('RATE_PER_KM_VES_CENTS', '15000'))  # 150.00 VES/km


class DevelopmentConfig(BaseConfig):
    """
    Configuración para desarrollo:
    Conecta a PostgreSQL + PostGIS cuando el contenedor/instancia está disponible,
    con contingencia automática local si se ejecuta fuera de Docker en Windows.
    """
    DEBUG = True
    TESTING = False
    SQLALCHEMY_DATABASE_URI = (
        os.getenv('DATABASE_URL')
        if os.getenv('DATABASE_URL')
        else (
            BaseConfig.POSTGRES_DATABASE_URI
            if _can_connect_postgres(BaseConfig.POSTGRES_DATABASE_URI)
            else 'sqlite:///josepo_local_fallback.db'
        )
    )
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'connect_args': {'timeout': 15, 'check_same_thread': False}
    }


class ProductionConfig(BaseConfig):
    """Configuración estricta de alta concurrencia para producción (PostgreSQL + PostGIS obligatorio)."""
    DEBUG = False
    TESTING = False
    SQLALCHEMY_DATABASE_URI = os.getenv('DATABASE_URL', BaseConfig.POSTGRES_DATABASE_URI)
    RATELIMIT_STORAGE_URI = os.getenv('RATELIMIT_STORAGE_URI', 'memory://')
    SQLALCHEMY_ENGINE_OPTIONS = {
        'pool_pre_ping': True,
        'pool_recycle': 300,
        'pool_size': int(os.getenv('DB_POOL_SIZE', '20')),
        'max_overflow': int(os.getenv('DB_MAX_OVERFLOW', '40')),
        'pool_timeout': 30,
    }

    @classmethod
    def validate(cls):
        # Validación de seguridad: en producción no se permiten claves por defecto ni SQLite
        if 'insecure' in cls.SECRET_KEY or len(cls.SECRET_KEY) < 32:
            raise ValueError("[SEGURIDAD CRÍTICA] SECRET_KEY no configurada o demasiado débil en producción.")
        if 'insecure' in cls.JWT_SECRET_KEY or len(cls.JWT_SECRET_KEY) < 32:
            raise ValueError("[SEGURIDAD CRÍTICA] JWT_SECRET_KEY no configurada o demasiado débil en producción.")
        if cls.SQLALCHEMY_DATABASE_URI.startswith('sqlite'):
            raise ValueError(
                "[ARQUITECTURA CRÍTICA - HALLAZGO B / FASE 7] SQLite no está permitido en producción por bloqueo de concurrencia. "
                "Configure DATABASE_URL con PostgreSQL + PostGIS (postgresql://...)."
            )


class TestingConfig(BaseConfig):
    """Configuración para ejecución de pruebas automatizadas."""
    TESTING = True
    DEBUG = True
    SQLALCHEMY_DATABASE_URI = 'sqlite:///:memory:'
    CURRENCY_CRON_ENABLED = False
    RATELIMIT_STORAGE_URI = 'memory://'


config_by_name = {
    'development': DevelopmentConfig,
    'production': ProductionConfig,
    'testing': TestingConfig
}
