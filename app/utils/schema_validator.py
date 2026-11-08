import re
from functools import wraps
from flask import request, jsonify

XSS_DANGEROUS_PATTERN = re.compile(r'(<\s*script\b|javascript\s*:|on\w+\s*=)', re.IGNORECASE)


class SchemaValidator:
    """
    Validador declarativo de esquemas JSON de entrada para endpoints REST (Blindaje Fase 7).
    Previene inyecciones XSS, tipos de datos inválidos y payloads malformados.
    """

    @staticmethod
    def validate(data: dict, schema: dict) -> tuple[bool, str | None]:
        if not isinstance(data, dict):
            return False, "El cuerpo de la petición debe ser un objeto JSON válido."

        for field_name, rules in schema.items():
            is_required = rules.get('required', False)
            val = data.get(field_name)

            # Verificar presencia de campos obligatorios
            if val is None or (isinstance(val, str) and val.strip() == ''):
                if is_required:
                    return False, rules.get('required_error', f"El campo '{field_name}' es obligatorio.")
                continue

            expected_type = rules.get('type', 'str')

            # Validación de tipo
            if expected_type == 'str':
                if not isinstance(val, str):
                    return False, rules.get('type_error', f"El campo '{field_name}' debe ser una cadena de texto.")
                val_clean = val.strip()

                # Prevención de payloads XSS en campos de texto
                if XSS_DANGEROUS_PATTERN.search(val_clean):
                    return False, f"El campo '{field_name}' contiene caracteres o etiquetas no permitidas por seguridad."

                min_len = rules.get('min_length')
                max_len = rules.get('max_length', 500)
                if min_len is not None and len(val_clean) < min_len:
                    return False, rules.get('length_error', f"El campo '{field_name}' debe tener al menos {min_len} caracteres.")
                if max_len is not None and len(val_clean) > max_len:
                    return False, rules.get('length_error', f"El campo '{field_name}' excede la longitud máxima ({max_len}).")

                pattern = rules.get('pattern')
                if pattern and not re.match(pattern, val_clean):
                    return False, rules.get('pattern_error', f"Formato inválido para el campo '{field_name}'.")

                allowed = rules.get('allowed_values')
                if allowed is not None:
                    check_val = val_clean.upper() if rules.get('case_insensitive', True) else val_clean
                    if check_val not in allowed:
                        return False, rules.get('allowed_error', f"Valor no permitido en '{field_name}'.")

            elif expected_type == 'int':
                if isinstance(val, bool) or not isinstance(val, int):
                    return False, rules.get('type_error', f"El campo '{field_name}' debe ser un número entero.")
                if 'min_value' in rules and val < rules['min_value']:
                    return False, f"El campo '{field_name}' debe ser mayor o igual a {rules['min_value']}."
                if 'max_value' in rules and val > rules['max_value']:
                    return False, f"El campo '{field_name}' excede el valor máximo permitido ({rules['max_value']})."

            elif expected_type in ('float', 'number'):
                if isinstance(val, bool) or not isinstance(val, (int, float)):
                    return False, rules.get('type_error', f"El campo '{field_name}' debe ser numérico.")
                if 'min_value' in rules and float(val) < rules['min_value']:
                    return False, f"El campo '{field_name}' debe ser mayor o igual a {rules['min_value']}."
                if 'max_value' in rules and float(val) > rules['max_value']:
                    return False, f"El campo '{field_name}' excede el valor máximo permitido ({rules['max_value']})."

            elif expected_type == 'bool':
                if not isinstance(val, bool):
                    return False, rules.get('type_error', f"El campo '{field_name}' debe ser booleano.")

        return True, None


def validate_json_schema(schema: dict):
    """Decorador Flask para validar el esquema JSON antes de ejecutar el controlador."""
    def decorator(fn):
        @wraps(fn)
        def wrapper(*args, **kwargs):
            data = request.get_json(silent=True)
            if data is None:
                return jsonify({'error': 'Se requiere un cuerpo JSON válido en la petición.'}), 400

            is_valid, error_msg = SchemaValidator.validate(data, schema)
            if not is_valid:
                return jsonify({'error': error_msg}), 400

            return fn(*args, **kwargs)
        return wrapper
    return decorator

