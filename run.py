import os
from app import create_app
from app.extensions import socketio

env = os.getenv('FLASK_ENV', 'development')
app = create_app(env)

if __name__ == '__main__':
    port = int(os.getenv('PORT', 5000))
    host = os.getenv('HOST', '0.0.0.0')
    is_debug = app.config.get('DEBUG', False)
    
    print(f"[*] Iniciando servidor Josepo Mejorado...")
    print(f"[*] Entorno: {env}")
    print(f"[*] Escuchando en: http://{host}:{port}")
    print(f"[*] WebSockets: Activo")
    
    socketio.run(
        app,
        host=host,
        port=port,
        debug=is_debug,
        use_reloader=is_debug,
        allow_unsafe_werkzeug=True
    )
