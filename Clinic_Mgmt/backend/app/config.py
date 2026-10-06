"""Application configuration (MVC: config layer).

Paths are anchored to the backend/ directory so the SQLite file stays
at backend/clinic.db no matter where this module is imported from.
"""
import os

BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


class Config:
    SQLALCHEMY_DATABASE_URI = f'sqlite:///{os.path.join(BACKEND_DIR, "clinic.db")}'
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    ADMIN_USERNAME = os.environ.get('ADMIN_USERNAME', 'admin')
    ADMIN_PASSWORD = os.environ.get('ADMIN_PASSWORD', 'admin123')
    # Shared secret the Node.js frontend sends as X-API-Key. Direct API
    # access without it is rejected. Set a strong value in production.
    API_KEY = os.environ.get('API_KEY', 'dev-key')
    CORS_ORIGINS = os.environ.get('CORS_ORIGINS', 'http://localhost:3000').split(',')
