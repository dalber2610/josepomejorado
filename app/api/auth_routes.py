from flask import Blueprint, request, jsonify
from flask_jwt_extended import create_access_token, jwt_required, get_jwt_identity
from app.extensions import db, limiter, get_client_ip
from app.models.user import User, UserRole
from app.utils.rate_limiter import auth_rate_limiter
from app.utils.schema_validator import validate_json_schema

auth_bp = Blueprint('auth_bp', __name__, url_prefix='/api/auth')

EMAIL_REGEX = r'^[\w\.-]+@[\w\.-]+\.\w+$'

REGISTER_SCHEMA = {
    'email': {
        'type': 'str',
        'required': True,
        'pattern': EMAIL_REGEX,
        'required_error': 'Formato de correo electrónico inválido.',
        'pattern_error': 'Formato de correo electrónico inválido.',
    },
    'password': {
        'type': 'str',
        'required': True,
        'min_length': 8,
        'required_error': 'La contraseña debe tener al menos 8 caracteres.',
        'length_error': 'La contraseña debe tener al menos 8 caracteres.',
    },
    'full_name': {
        'type': 'str',
        'required': True,
        'min_length': 2,
        'required_error': 'El nombre completo es obligatorio.',
    },
    'phone_number': {
        'type': 'str',
        'required': True,
        'min_length': 7,
        'required_error': 'El número de teléfono es obligatorio.',
    },
    'role': {
        'type': 'str',
        'required': False,
        'allowed_values': list(UserRole.__members__.keys()),
        'allowed_error': 'Rol no reconocido. Roles válidos: CLIENT, DRIVER.',
    },
}

LOGIN_SCHEMA = {
    'email': {
        'type': 'str',
        'required': True,
        'required_error': 'Correo y contraseña son obligatorios.',
    },
    'password': {
        'type': 'str',
        'required': True,
        'required_error': 'Correo y contraseña son obligatorios.',
    },
}


@auth_bp.route('/register', methods=['POST'])
@limiter.limit("10 per minute")
@validate_json_schema(REGISTER_SCHEMA)
def register():
    data = request.get_json() or {}

    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    full_name = data.get('full_name', '').strip()
    phone_number = data.get('phone_number', '').strip()
    role_str = data.get('role', 'CLIENT').upper()

    # Comprobación de duplicados
    if User.query.filter_by(email=email).first():
        return jsonify({'error': 'Ya existe una cuenta con este correo electrónico.'}), 409

    if User.query.filter_by(phone_number=phone_number).first():
        return jsonify({'error': 'Ya existe una cuenta con este número telefónico.'}), 409

    try:
        user = User(
            email=email,
            full_name=full_name,
            phone_number=phone_number,
            role=UserRole[role_str]
        )
        user.set_password(password)
        db.session.add(user)
        db.session.commit()

        access_token = create_access_token(
            identity=str(user.id),
            additional_claims={'role': user.role.value, 'name': user.full_name}
        )

        return jsonify({
            'message': 'Usuario registrado exitosamente.',
            'user': user.to_dict(),
            'access_token': access_token
        }), 201

    except Exception:
        db.session.rollback()
        return jsonify({'error': 'Error interno al registrar el usuario.'}), 500


@auth_bp.route('/login', methods=['POST'])
@limiter.limit("15 per minute")
@validate_json_schema(LOGIN_SCHEMA)
def login():
    data = request.get_json() or {}

    email = data.get('email', '').strip().lower()
    password = data.get('password', '')
    client_ip = get_client_ip()

    # Protección contra ataques de fuerza bruta en login fallido (máx 5 fallos por IP cada 5 min)
    allowed_ip, retry_after = auth_rate_limiter.is_allowed(
        f"auth_login_fail:{client_ip}",
        max_requests=5,
        window_seconds=300
    )
    if not allowed_ip:
        return jsonify({
            'error': f'Demasiados intentos de inicio de sesión fallidos. Bloqueado por {retry_after} segundos.',
            'retry_after_seconds': retry_after
        }), 429

    user = User.query.filter_by(email=email).first()

    if not user or not user.check_password(password):
        return jsonify({'error': 'Credenciales incorrectas.'}), 401

    # Si las credenciales son válidas, limpiar el contador de fallos de esa IP
    auth_rate_limiter.reset(f"auth_login_fail:{client_ip}")

    if not user.is_active:
        return jsonify({'error': 'La cuenta se encuentra desactivada temporalmente.'}), 403

    access_token = create_access_token(
        identity=str(user.id),
        additional_claims={'role': user.role.value, 'name': user.full_name}
    )

    return jsonify({
        'message': 'Autenticación exitosa.',
        'user': user.to_dict(),
        'access_token': access_token
    }), 200


@auth_bp.route('/me', methods=['GET'])
@jwt_required()
def get_current_user():
    user_id = int(get_jwt_identity())
    user = db.session.get(User, user_id)
    if not user:
        return jsonify({'error': 'Usuario no encontrado.'}), 404

    return jsonify({'user': user.to_dict()}), 200
