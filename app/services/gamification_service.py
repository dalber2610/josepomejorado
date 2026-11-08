import logging
from app.extensions import db, socketio
from app.models.user import User
from app.models.traffic_report import TrafficReport
from app.models.reward import (
    PartnerReward,
    RewardCategory,
    PointTransaction,
    RewardRedemption,
    RedemptionStatus
)

logger = logging.getLogger(__name__)


class GamificationService:
    """
    Motor de Gamificación, Reputación Vial, Validación Cruzada de Tráfico
    y Catálogo de Talleres/Comercios Aliados (Fase 5).
    """

    # Tabla oficial de puntos
    POINTS_CREATE_REPORT = 25
    POINTS_CONFIRM_REPORT_VALIDATOR = 10
    POINTS_CONFIRM_REPORT_AUTHOR = 15
    POINTS_REPORT_VERIFIED_BONUS = 20
    POINTS_COMPLETE_TOW = 50

    DEFAULT_PARTNER_CATALOG = [
        {
            'partner_name': 'Taller Mecánico AutoMaster Pro',
            'category': RewardCategory.MECANICA,
            'title': 'Diagnóstico Computarizado OBD-II Gratis + 20% en Mano de Obra',
            'description': 'Escaneo electrónico completo y descuento preferencial en reparaciones mecánicas.',
            'points_cost': 50,
            'discount_percentage': 20,
            'city_location': 'Caracas / Valencia / Maracay',
            'stock': 150
        },
        {
            'partner_name': 'Baterías Duncan Express 24h',
            'category': RewardCategory.BATERIAS,
            'title': '15% de Descuento en Baterías + Revisión de Alternador Gratis',
            'description': 'Chequeo del sistema eléctrico sin costo y descuento directo al entregar batería usada.',
            'points_cost': 80,
            'discount_percentage': 15,
            'city_location': 'Red Nacional (45 Sucursales)',
            'stock': 100
        },
        {
            'partner_name': 'Cauchos & Alineación El Rosal',
            'category': RewardCategory.CAUCHOS,
            'title': 'Alineación y Balanceo 3D al 50% de Descuento',
            'description': 'Servicio completo de tren delantero, rotación de neumáticos y calibración con nitrógeno.',
            'points_cost': 100,
            'discount_percentage': 50,
            'city_location': 'Caracas / Barquisimeto / Puerto Ordaz',
            'stock': 80
        },
        {
            'partner_name': 'Centro de Lubricantes Venoco & Inca',
            'category': RewardCategory.LUBRICANTES,
            'title': '25% de Descuento en Cambio de Aceite Sintético + Filtro',
            'description': 'Incluye revisión de 15 puntos de seguridad vial y reposición de fluidos.',
            'points_cost': 120,
            'discount_percentage': 25,
            'city_location': 'Red Aliada Nacional',
            'stock': 90
        },
        {
            'partner_name': 'JOSEPO Club Guardián Vial',
            'category': RewardCategory.DESCUENTO_GRUA,
            'title': 'Bono de 30% de Descuento en tu Próximo Remolque SOS',
            'description': 'Cupón aplicable directamente a la tarifa base de cualquier servicio de grúa en la app.',
            'points_cost': 200,
            'discount_percentage': 30,
            'city_location': 'Cobertura Nacional Josepo',
            'stock': 200
        }
    ]

    @classmethod
    def ensure_default_catalog(cls):
        """Inicializa el catálogo de talleres y comercios aliados si está vacío."""
        if PartnerReward.query.count() == 0:
            for item in cls.DEFAULT_PARTNER_CATALOG:
                reward = PartnerReward(**item)
                db.session.add(reward)
            db.session.commit()
            logger.info("🎁 Catálogo de Talleres y Comercios Aliados inicializado.")

    @classmethod
    def award_points(
        cls,
        user_id: int,
        points: int,
        reason_code: str,
        description: str,
        reference_id: str = None,
        auto_commit: bool = True
    ) -> dict:
        """
        Acredita puntos a un usuario bajo bloqueo de fila atómico (`with_for_update`),
        actualiza su nivel de reputación vial y registra la transacción.
        """
        if points <= 0:
            raise ValueError("La cantidad de puntos a otorgar debe ser positiva.")

        user = User.query.filter_by(id=user_id).with_for_update().first()
        if not user:
            raise ValueError("Usuario no encontrado para acreditar puntos.")

        previous_level = user.reputation_level or 'BRONCE'
        user.points_balance = int(user.points_balance or 0) + int(points)
        user.lifetime_points = int(user.lifetime_points or 0) + int(points)
        new_level = user.recalculate_reputation_level()

        tx = PointTransaction(
            user_id=user.id,
            points_delta=int(points),
            reason_code=reason_code,
            description=description,
            reference_id=str(reference_id) if reference_id is not None else None
        )
        db.session.add(tx)

        if auto_commit:
            db.session.commit()

        payload = {
            'user_id': user.id,
            'points_added': int(points),
            'points_balance': user.points_balance,
            'lifetime_points': user.lifetime_points,
            'reputation_level': new_level,
            'level_up': previous_level != new_level,
            'reason_code': reason_code,
            'description': description
        }

        socketio.emit('points_updated', payload, room=f"user_{user.id}")
        return payload

    @classmethod
    def confirm_traffic_report(cls, report_id: int, validator_user_id: int) -> dict:
        """
        Validación Cruzada de Tráfico (Fase 5):
        - Impide que el autor se auto-confirme su propio reporte.
        - Impide que un mismo usuario confirme dos veces el mismo reporte.
        - Otorga +10 puntos al validador por ayudar a la comunidad.
        - Otorga +15 puntos al autor del reporte por cada confirmación recibida.
        - Al alcanzar 2 confirmaciones, marca `is_verified = True` y otorga un bono adicional
          de +20 puntos al autor original.
        """
        report = TrafficReport.query.filter_by(id=report_id).with_for_update().first()
        if not report:
            raise ValueError("Reporte de tráfico no encontrado.")

        if int(report.author_id) == int(validator_user_id):
            raise ValueError("No puedes confirmar tu propio reporte vial. Otro conductor debe validarlo.")

        confirmed_ids = [int(uid) for uid in (report.confirmed_by_user_ids or [])]
        if int(validator_user_id) in confirmed_ids:
            raise ValueError("Ya has confirmado este reporte vial anteriormente.")

        confirmed_ids.append(int(validator_user_id))
        report.confirmed_by_user_ids = list(confirmed_ids)
        report.confirmations_count = len(confirmed_ids)

        newly_verified = False
        if report.confirmations_count >= TrafficReport.VERIFICATION_THRESHOLD and not report.is_verified:
            report.is_verified = True
            newly_verified = True

        # 1. Premiar al usuario validador (+10 pts)
        validator_award = cls.award_points(
            user_id=validator_user_id,
            points=cls.POINTS_CONFIRM_REPORT_VALIDATOR,
            reason_code='TRAFFIC_REPORT_CONFIRMED_VALIDATOR',
            description=f"Confirmación comunitaria del reporte vial #{report.id} ({report.report_type.value})",
            reference_id=str(report.id),
            auto_commit=False
        )

        # 2. Premiar al autor del reporte (+15 pts + +20 pts bono si acaba de verificarse)
        author_points = cls.POINTS_CONFIRM_REPORT_AUTHOR + (
            cls.POINTS_REPORT_VERIFIED_BONUS if newly_verified else 0
        )
        author_desc = (
            f"¡Tu reporte #{report.id} fue verificado por la comunidad!"
            if newly_verified
            else f"Otro conductor confirmó tu reporte vial #{report.id}."
        )
        author_award = cls.award_points(
            user_id=report.author_id,
            points=author_points,
            reason_code='TRAFFIC_REPORT_CONFIRMED_AUTHOR',
            description=author_desc,
            reference_id=str(report.id),
            auto_commit=False
        )

        db.session.commit()

        report_dict = report.to_dict()
        socketio.emit('traffic_report_confirmed', {
            'report': report_dict,
            'newly_verified': newly_verified,
            'validator_user_id': validator_user_id
        })

        return {
            'message': (
                f"¡Gracias por validar! Ganaste +{cls.POINTS_CONFIRM_REPORT_VALIDATOR} puntos "
                f"y el autor recibió +{author_points} puntos."
            ),
            'report': report_dict,
            'newly_verified': newly_verified,
            'validator_points': validator_award,
            'author_points': author_award
        }

    @classmethod
    def redeem_reward(cls, user_id: int, reward_id: int) -> dict:
        """
        Canjea puntos del usuario por un cupón digital en un Taller o Comercio Aliado.
        Usa bloqueo transaccional `with_for_update()` para evitar saldos negativos o sobreventa.
        """
        cls.ensure_default_catalog()

        user = User.query.filter_by(id=user_id).with_for_update().first()
        if not user:
            raise ValueError("Usuario no encontrado.")

        reward = PartnerReward.query.filter_by(id=reward_id, is_active=True).with_for_update().first()
        if not reward:
            raise ValueError("La recompensa seleccionada no existe o ya no está disponible.")

        if reward.stock <= 0:
            raise ValueError("Este beneficio ha agotado sus cupos disponibles en el comercio aliado.")

        current_balance = int(user.points_balance or 0)
        cost = int(reward.points_cost)
        if current_balance < cost:
            needed = cost - current_balance
            raise ValueError(
                f"Puntos insuficientes. Tienes {current_balance} pts y necesitas {cost} pts (te faltan {needed} pts)."
            )

        # Descontar puntos y stock atómicamente
        user.points_balance = current_balance - cost
        reward.stock = int(reward.stock) - 1

        coupon_code = RewardRedemption.generate_coupon_code()
        while RewardRedemption.query.filter_by(coupon_code=coupon_code).first() is not None:
            coupon_code = RewardRedemption.generate_coupon_code()

        redemption = RewardRedemption(
            user_id=user.id,
            reward_id=reward.id,
            points_spent=cost,
            coupon_code=coupon_code,
            status=RedemptionStatus.ACTIVE
        )
        db.session.add(redemption)

        tx = PointTransaction(
            user_id=user.id,
            points_delta=-cost,
            reason_code='REWARD_REDEEMED',
            description=f"Canje en {reward.partner_name}: {reward.title} (Cupón {coupon_code})",
            reference_id=redemption.id
        )
        db.session.add(tx)
        db.session.commit()

        socketio.emit('points_updated', {
            'user_id': user.id,
            'points_added': -cost,
            'points_balance': user.points_balance,
            'lifetime_points': user.lifetime_points,
            'reputation_level': user.reputation_level,
            'reason_code': 'REWARD_REDEEMED'
        }, room=f"user_{user.id}")

        return {
            'message': f"¡Canje exitoso en {reward.partner_name}! Presenta tu código {coupon_code}.",
            'redemption': redemption.to_dict(),
            'points_balance': user.points_balance
        }

    @classmethod
    def get_user_gamification_profile(cls, user_id: int) -> dict:
        """Retorna el resumen completo de puntos, nivel, historial y cupones activos del usuario."""
        cls.ensure_default_catalog()
        user = db.session.get(User, user_id)
        if not user:
            raise ValueError("Usuario no encontrado.")

        recent_txs = (
            PointTransaction.query
            .filter_by(user_id=user.id)
            .order_by(PointTransaction.created_at.desc())
            .limit(15)
            .all()
        )
        redemptions = (
            RewardRedemption.query
            .filter_by(user_id=user.id)
            .order_by(RewardRedemption.created_at.desc())
            .limit(10)
            .all()
        )

        return {
            'user': user.to_dict(),
            'points_balance': int(user.points_balance or 0),
            'lifetime_points': int(user.lifetime_points or 0),
            'reputation_level': user.reputation_level or 'BRONCE',
            'next_level_info': user.get_next_level_info(),
            'recent_transactions': [t.to_dict() for t in recent_txs],
            'redemptions': [r.to_dict() for r in redemptions]
        }

    @classmethod
    def get_leaderboard(cls, limit: int = 10) -> list:
        """Retorna el ranking de usuarios/conductores con mayor reputación vial."""
        top_users = (
            User.query
            .filter(User.is_active.is_(True))
            .order_by(User.lifetime_points.desc(), User.points_balance.desc())
            .limit(limit)
            .all()
        )
        return [
            {
                'rank': idx + 1,
                'user_id': u.id,
                'full_name': u.full_name,
                'role': u.role.value if hasattr(u.role, 'value') else u.role,
                'reputation_level': u.reputation_level or 'BRONCE',
                'lifetime_points': int(u.lifetime_points or 0),
                'points_balance': int(u.points_balance or 0)
            }
            for idx, u in enumerate(top_users)
        ]

