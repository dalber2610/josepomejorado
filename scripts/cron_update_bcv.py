#!/usr/bin/env python
"""
Script Cronjob de Automatización Cambiaria BCV (Fase 7).
Puede ejecutarse:
  1. Como tarea programada puntual (crontab / Windows Task Scheduler):
     python scripts/cron_update_bcv.py
  2. Como demonio continuo en contenedor Docker (josepo_cron_fx):
     python scripts/cron_update_bcv.py --daemon --interval 1800
"""
import argparse
import os
import sys
import time
import logging

sys.path.insert(0, os.path.abspath(os.path.join(os.path.dirname(__file__), '..')))

from app import create_app
from app.extensions import db
from app.services.currency_service import CurrencyService

logging.basicConfig(
    level=logging.INFO,
    format='[%(asctime)s] [CRON-BCV] %(levelname)s: %(message)s'
)
logger = logging.getLogger('cron_bcv')


def execute_single_sync(app) -> dict:
    with app.app_context():
        db.create_all()
        result = CurrencyService.sync_official_bcv_rate(force=True, source_tag='BCV_CRON_CLI')
        logger.info(
            f"Tasa BCV actualizada: {result['rate_decimal']} VES/USD "
            f"(Variación: {result['variation_pct']}%, Fuente: {result['source']})"
        )
        return result


def main():
    parser = argparse.ArgumentParser(description='Cronjob de actualización automática de tasa BCV')
    parser.add_argument('--daemon', action='store_true', help='Ejecutar en bucle continuo')
    parser.add_argument('--interval', type=int, default=1800, help='Intervalo en segundos para modo daemon (default: 1800s = 30m)')
    args = parser.parse_args()

    env = os.getenv('FLASK_ENV', 'development')
    app = create_app(env)

    if not args.daemon:
        execute_single_sync(app)
        return

    logger.info(f"Iniciando demonio Cronjob BCV cada {args.interval} segundos...")
    while True:
        try:
            execute_single_sync(app)
        except Exception as exc:
            logger.error(f"Error en ejecución de cronjob cambiario: {exc}")
        time.sleep(max(30, args.interval))


if __name__ == '__main__':
    main()

