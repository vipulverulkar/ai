"""Flask application factory (MVC: assembles Model + Controller layers)."""
from flask import Flask, g, jsonify, request
from flask_cors import CORS

from app.audit import init_audit
from app.config import Config
from app.models import db
from app.routes import register_blueprints
from app.seed import seed_all


def create_app():
    app = Flask(__name__)
    app.config.from_object(Config)
    CORS(app, origins=app.config['CORS_ORIGINS'])

    db.init_app(app)
    register_blueprints(app)
    init_audit()

    if app.config['API_KEY'] == 'dev-key':
        print('WARNING: using default dev API key. Set API_KEY env var in production.')

    @app.before_request
    def _api_guard():
        from app.rbac import current_role
        g.actor = request.headers.get('X-User', 'system')
        g.role = current_role()
        if not request.path.startswith('/api/') or request.path == '/api/health':
            return None
        if request.headers.get('X-API-Key') != app.config['API_KEY']:
            return jsonify({'error': 'Unauthorized'}), 401
        return None

    with app.app_context():
        db.create_all()
        seed_all()

    return app
