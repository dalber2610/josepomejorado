import logging
from app.extensions import db, socketio
from app.models.user import User
from app.models.tow_request import TowRequest, TowRequestStatus
from app.models.reward import FamilySosAlert
from app.services.otp_service import OtpService

logger = logging.getLogger(__name__)


class NotificationService:
    """
    Servicio de Notificaciones Críticas y Botón SOS Familiar (Fase 5).
    Conecta con `OtpService` para despachar alertas SMS/WhatsApp a familiares
    con coordenadas satelitales y enlace de rastreo en vivo.
    """

    @classmethod
    def trigger_family_sos_alert(
        cls,
        user_id: int,
        lat: float,
        lng: float,
        contact_name: str = None,
        contact_phone: str = None,
        custom_message: str = None,
        request_id: str = None,
        triggered_via: str = 'BUTTON',
        base_url: str = 'http://localhost:5000'
    ) -> dict:
        """
        Registra y envía una Alerta SOS Familiar vía SMS/WhatsApp con enlace de rastreo en vivo.
        Si el usuario no pasa contact_phone en la llamada, usa el contacto guardado en su perfil.
        """
        user = User.query.filter_by(id=user_id).with_for_update().first()
        if not user:
            raise ValueError("Usuario no encontrado.")

        final_name = (contact_name or user.emergency_contact_name or "Familiar de Emergencia").strip()
        final_phone = (contact_phone or user.emergency_contact_phone or "").strip().replace(" ", "").replace("-", "")

        if not final_phone or len(final_phone) < 10:
            raise ValueError(
                "Debes indicar un número telefónico válido de tu contacto familiar (ej. +584141234567)."
            )

        # Guardar el contacto en el perfil del usuario para futuras emergencias con un solo toque/voz
        user.emergency_contact_name = final_name
        user.emergency_contact_phone = final_phone

        # Verificar si tiene una solicitud de grúa activa en curso
        active_req = None
        if request_id:
            active_req = db.session.get(TowRequest, request_id)
        else:
            active_req = TowRequest.query.filter(
                TowRequest.client_id == user.id,
                TowRequest.status.in_([
                    TowRequestStatus.PENDING,
                    TowRequestStatus.OFFERED,
                    TowRequestStatus.ASSIGNED,
                    TowRequestStatus.IN_TRANSIT_TO_USER,
                    TowRequestStatus.ARRIVED_AT_USER,
                    TowRequestStatus.IN_TRANSIT_TO_DEST
                ])
            ).order_by(TowRequest.created_at.desc()).first()

        alert = FamilySosAlert(
            user_id=user.id,
            request_id=active_req.id if active_req else None,
            contact_name=final_name,
            contact_phone=final_phone,
            lat=float(lat),
            lng=float(lng),
            custom_message=(custom_message or "Sufrí un percance vial y solicité asistencia en Josepo.").strip(),
            triggered_via=triggered_via.upper() if triggered_via else 'BUTTON'
        )
        db.session.add(alert)
        db.session.commit()

        clean_base = base_url.rstrip('/')
        live_tracking_link = f"{clean_base}/api/gamification/sos/track/{alert.tracking_token}"
        maps_link = f"https://www.google.com/maps?q={alert.lat},{alert.lng}"

        tow_status_info = (
            f"Grúa en gestión ({active_req.status.value})"
            if active_req else "Ubicación GPS compartida en vivo"
        )

        sms_body = (
            f"🚨 [ALERTA SOS FAMILIAR JOSEPO] {user.full_name} ({user.phone_number}) "
            f"ha activado el botón de emergencia vial para {final_name}. "
            f"Nota: \"{alert.custom_message}\". Estado: {tow_status_info}. "
            f"📍 Mapa GPS: {maps_link} | 🛰️ Rastreo en vivo: {live_tracking_link}"
        )

        delivery_info = OtpService.send_custom_alert_message(
            phone=final_phone,
            text_message=sms_body,
            category=f"SOS_FAMILIAR_{alert.triggered_via}"
        )

        payload = alert.to_dict()
        payload['live_tracking_link'] = live_tracking_link
        payload['sms_preview'] = sms_body
        payload['delivery'] = delivery_info

        # Emitir evento en tiempo real al cliente y al Centro de Control
        socketio.emit('family_sos_dispatched', payload, room=f"user_{user.id}")
        socketio.emit('admin_family_sos_alert', payload)

        return payload

    @classmethod
    def get_live_tracking_snapshot(cls, tracking_token: str) -> dict:
        """
        Retorna el estado en tiempo real para el familiar que abre el enlace de rastreo.
        """
        alert = FamilySosAlert.query.filter_by(tracking_token=tracking_token).first()
        if not alert:
            raise ValueError("Enlace de rastreo SOS no encontrado o inválido.")

        tow_info = None
        if alert.tow_request:
            req = alert.tow_request
            tow_info = {
                'request_id': req.id,
                'status': req.status.value,
                'truck_plate': req.assigned_truck.license_plate if req.assigned_truck else None,
                'driver_name': (
                    req.assigned_truck.driver.full_name
                    if req.assigned_truck and req.assigned_truck.driver else None
                ),
                'truck_position': (
                    {
                        'lat': req.assigned_truck.current_lat,
                        'lng': req.assigned_truck.current_lng
                    }
                    if req.assigned_truck else None
                ),
                'destination_address': req.dest_address
            }

        data = alert.to_dict()
        data['live_tow_service'] = tow_info
        return data
