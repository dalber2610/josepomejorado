from decimal import Decimal, ROUND_HALF_UP
from datetime import datetime, timedelta, timezone
import threading
import requests
import logging
from flask import current_app
from app.extensions import db
from app.models.exchange_rate import ExchangeRateLog

logger = logging.getLogger(__name__)


class CurrencyService:
    """
    Manejo de tasas de cambio y cálculos financieros de alta precisión (Decimal + Centavos).
    Incluye motor de sincronización automática por Cronjob (Fase 7).
    """

    # Tasa de contingencia en caso de caída extrema de servicios externos
    DEFAULT_FALLBACK_RATE = Decimal('40.0000')

    # Estado del Cronjob de Automatización Cambiaria (Fase 7)
    _cron_lock = threading.Lock()
    _cron_stop_event = threading.Event()
    _cron_thread: threading.Thread | None = None
    _cron_state = {
        'is_running': False,
        'interval_minutes': 30,
        'last_run_at': None,
        'last_rate': None,
        'last_source': None,
        'executions_count': 0,
    }

    @classmethod
    def _fetch_external_bcv_rate(cls) -> tuple[Decimal | None, str]:
        """Consulta el proveedor primario y secundario de tasa oficial BCV."""
        primary_url = current_app.config.get('BCV_API_URL')
        secondary_url = current_app.config.get(
            'BCV_SECONDARY_API_URL',
            'https://ve.dolarapi.com/v1/dolares/oficial'
        )

        for url, provider_tag in [(primary_url, 'BCV_PRIMARY_API'), (secondary_url, 'BCV_SECONDARY_API')]:
            if not url:
                continue
            try:
                response = requests.get(url, timeout=4)
                if response.status_code == 200:
                    data = response.json()
                    val = None
                    if isinstance(data, dict):
                        val = (
                            data.get('price')
                            or data.get('promedio')
                            or data.get('rate')
                            or (data.get('monitors', {}).get('bcv', {}).get('price') if isinstance(data.get('monitors'), dict) else None)
                        )
                    if val is not None:
                        rate_dec = Decimal(str(val)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
                        if rate_dec > Decimal('0'):
                            return rate_dec, provider_tag
            except Exception as e:
                logger.warning(f"No se pudo consultar proveedor cambiario ({url}): {e}")

        return None, 'FALLBACK'

    @classmethod
    def sync_official_bcv_rate(
        cls,
        force: bool = True,
        custom_rate: Decimal | str | float | None = None,
        source_tag: str = 'BCV_CRON'
    ) -> dict:
        """
        Ejecuta una sincronización de la tasa oficial BCV (invocable desde Cronjob o API).
        Persiste el registro en ExchangeRateLog y actualiza las métricas del planificador.
        """
        previous_entry = ExchangeRateLog.query.order_by(ExchangeRateLog.fetched_at.desc()).first()
        previous_rate = Decimal(str(previous_entry.rate)) if previous_entry else None

        if custom_rate is not None:
            new_rate = Decimal(str(custom_rate)).quantize(Decimal('0.0001'), rounding=ROUND_HALF_UP)
            effective_source = source_tag
        else:
            fetched_rate, provider_source = cls._fetch_external_bcv_rate()
            if fetched_rate is not None:
                new_rate = fetched_rate
                effective_source = f"{source_tag}:{provider_source}"
            elif previous_rate is not None:
                new_rate = previous_rate
                effective_source = f"{source_tag}:CACHED_DB"
            else:
                new_rate = cls.DEFAULT_FALLBACK_RATE
                effective_source = f"{source_tag}:DEFAULT_FALLBACK"

        variation_pct = Decimal('0.0000')
        if previous_rate and previous_rate > Decimal('0'):
            variation_pct = (((new_rate - previous_rate) / previous_rate) * Decimal('100')).quantize(
                Decimal('0.01'), rounding=ROUND_HALF_UP
            )

        now_utc = datetime.now(timezone.utc)
        try:
            log_entry = ExchangeRateLog(
                rate=new_rate,
                source=effective_source[:50],
                fetched_at=now_utc
            )
            db.session.add(log_entry)
            db.session.commit()
        except Exception as e:
            db.session.rollback()
            logger.error(f"Error persistiendo sincronización cambiaria BCV: {e}")

        with cls._cron_lock:
            cls._cron_state['last_run_at'] = now_utc.isoformat()
            cls._cron_state['last_rate'] = float(new_rate)
            cls._cron_state['last_source'] = effective_source
            cls._cron_state['executions_count'] += 1

        return {
            'rate': float(new_rate),
            'rate_decimal': str(new_rate),
            'previous_rate': float(previous_rate) if previous_rate else None,
            'variation_pct': float(variation_pct),
            'source': effective_source,
            'synced_at': now_utc.isoformat(),
            'executions_count': cls._cron_state['executions_count'],
        }

    @classmethod
    def run_cron_tick(cls, app) -> dict:
        """Ejecuta un ciclo atómico del cronjob dentro del contexto de la aplicación."""
        with app.app_context():
            return cls.sync_official_bcv_rate(force=True, source_tag='BCV_CRON_AUTO')

    @classmethod
    def start_exchange_rate_cron(cls, app, interval_minutes: int = 30) -> dict:
        """
        Inicia el demonio Cronjob en segundo plano que actualiza la tasa oficial BCV
        automáticamente cada `interval_minutes` minutos (Fase 7).
        """
        with cls._cron_lock:
            cls._cron_state['interval_minutes'] = max(1, int(interval_minutes))
            if cls._cron_thread and cls._cron_thread.is_alive():
                cls._cron_state['is_running'] = True
                return dict(cls._cron_state)

            cls._cron_stop_event.clear()
            cls._cron_state['is_running'] = True

            def _cron_worker():
                interval_sec = max(60, int(interval_minutes) * 60)
                while not cls._cron_stop_event.is_set():
                    try:
                        with app.app_context():
                            cls.sync_official_bcv_rate(force=True, source_tag='BCV_CRON_AUTO')
                    except Exception as exc:
                        logger.warning(f"Error en ciclo del cronjob cambiario BCV: {exc}")
                    if cls._cron_stop_event.wait(timeout=interval_sec):
                        break

            cls._cron_thread = threading.Thread(
                target=_cron_worker,
                name="josepo-bcv-cron-worker",
                daemon=True
            )
            cls._cron_thread.start()
            return dict(cls._cron_state)

    @classmethod
    def stop_exchange_rate_cron(cls) -> dict:
        """Detiene de forma segura el hilo del cronjob cambiario."""
        with cls._cron_lock:
            cls._cron_stop_event.set()
            cls._cron_state['is_running'] = False
            return dict(cls._cron_state)

    @classmethod
    def get_cron_status(cls) -> dict:
        """Retorna el estado actual y métricas del cronjob de automatización cambiaria."""
        with cls._cron_lock:
            return dict(cls._cron_state)

    @classmethod
    def get_current_bcv_rate(cls) -> Decimal:
        """
        Obtiene la tasa oficial BCV vigente.
        Revisa primero la caché en base de datos; si expiró (>60 min), sincroniza automáticamente.
        """
        one_hour_ago = datetime.now(timezone.utc) - timedelta(minutes=60)

        latest_log = ExchangeRateLog.query.filter(
            ExchangeRateLog.fetched_at >= one_hour_ago
        ).order_by(ExchangeRateLog.fetched_at.desc()).first()

        if latest_log:
            return Decimal(str(latest_log.rate))

        sync_result = cls.sync_official_bcv_rate(force=True, source_tag='BCV_CACHE_REFRESH')
        return Decimal(sync_result['rate_decimal'])

    @classmethod
    def calculate_cost(cls, total_distance_km: float) -> dict:
        """
        Calcula el costo del servicio en base a la distancia total.
        Todos los cálculos monetarios se realizan en centavos enteros (VES y USD)
        usando Decimal para garantizar precisión estricta sin coma flotante.
        """
        base_rate_cents = current_app.config.get('BASE_RATE_VES_CENTS', 50000)      # 500.00 VES
        rate_per_km_cents = current_app.config.get('RATE_PER_KM_VES_CENTS', 15000)  # 150.00 VES/km

        dist_decimal = Decimal(str(round(total_distance_km, 2)))
        distance_cost_cents = int((dist_decimal * Decimal(rate_per_km_cents)).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

        total_ves_cents = base_rate_cents + distance_cost_cents
        rate = cls.get_current_bcv_rate()

        # Conversión a centavos de USD: (total_ves_cents / rate)
        total_usd_cents = int((Decimal(total_ves_cents) / rate).quantize(Decimal('1'), rounding=ROUND_HALF_UP))

        return {
            'cost_ves_cents': total_ves_cents,
            'cost_usd_cents': total_usd_cents,
            'cost_ves': round(total_ves_cents / 100.0, 2),
            'cost_usd': round(total_usd_cents / 100.0, 2),
            'exchange_rate': float(rate),
            'base_rate_ves': round(base_rate_cents / 100.0, 2),
            'rate_per_km_ves': round(rate_per_km_cents / 100.0, 2)
        }
