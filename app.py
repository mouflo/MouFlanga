#!/usr/bin/env python3
"""
MouFlanga - Lecteur et gestionnaire de mangas CBR
Application web pour organiser et lire vos mangas téléchargés
"""

import os
import json
import logging
from pathlib import Path
from datetime import datetime
from functools import wraps
from flask import Flask, render_template, request, jsonify, send_file, session
from werkzeug.security import check_password_hash, generate_password_hash
import zipfile
from io import BytesIO
from PIL import Image

# Configuration
app = Flask(__name__)
app.secret_key = os.getenv('SECRET_KEY', 'mouflanga-dev-key-change-in-prod')
VERSION = "1.0.0"

# Logging
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)

# Dossiers
MANGA_DIR = Path(os.getenv('MANGA_DIR', '/mnt/data/manga'))
DATA_DIR = Path('./data')
DATA_DIR.mkdir(exist_ok=True)

SETTINGS_FILE = DATA_DIR / 'settings.json'
AUTH_FILE = DATA_DIR / 'auth.json'
PROGRESS_FILE = DATA_DIR / 'progress.json'

def load_json(path, default=None):
    """Charge un fichier JSON"""
    if path.exists():
        try:
            return json.loads(path.read_text())
        except:
            return default or {}
    return default or {}

def save_json(path, data):
    """Sauvegarde un fichier JSON"""
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))

def load_settings():
    """Charge les paramètres"""
    return load_json(SETTINGS_FILE, {
        'manga_dir': str(MANGA_DIR),
        'library_dir': '',
        'auto_import': True
    })

def require_login(f):
    """Décorateur pour vérifier l'authentification"""
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if 'user' not in session:
            return jsonify({'error': 'Non authentifié'}), 401
        return f(*args, **kwargs)
    return decorated_function

# ========== ROUTES AUTHENTIFICATION ==========

@app.route('/login', methods=['GET', 'POST'])
def login():
    """Page de connexion"""
    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username', '')
        password = data.get('password', '')

        auth = load_json(AUTH_FILE, {})
        if username in auth and check_password_hash(auth[username], password):
            session['user'] = username
            return jsonify({'ok': True, 'message': 'Connecté'})

        return jsonify({'ok': False, 'error': 'Identifiants invalides'}), 401

    return render_template('login.html', version=VERSION)

@app.route('/logout')
def logout():
    """Déconnexion"""
    session.clear()
    return jsonify({'ok': True})

@app.route('/setup', methods=['GET', 'POST'])
def setup():
    """Page de configuration initiale"""
    auth = load_json(AUTH_FILE, {})
    if auth:
        return jsonify({'error': 'Déjà configuré'}), 403

    if request.method == 'POST':
        data = request.get_json()
        username = data.get('username', 'admin')
        password = data.get('password', '')

        if len(password) < 6:
            return jsonify({'error': 'Mot de passe trop court'}), 400

        auth[username] = generate_password_hash(password)
        save_json(AUTH_FILE, auth)
        session['user'] = username

        return jsonify({'ok': True, 'message': 'Configuration terminée'})

    return render_template('setup.html', version=VERSION)

# ========== ROUTES MANGA ==========

@app.route('/')
def index():
    """Page d'accueil"""
    auth = load_json(AUTH_FILE, {})
    if 'user' not in session:
        if auth:
            return render_template('login.html', version=VERSION)
        return render_template('setup.html', version=VERSION)

    return render_template('index.html', version=VERSION)

@app.route('/api/manga/list')
@require_login
def manga_list():
    """Liste les mangas disponibles"""
    settings = load_settings()
    manga_dir = Path(settings.get('manga_dir', str(MANGA_DIR)))
    progress = load_json(PROGRESS_FILE, {})

    mangas = []
    if manga_dir.exists():
        for manga_folder in sorted(manga_dir.iterdir()):
            if not manga_folder.is_dir():
                continue

            cbr_files = list(manga_folder.rglob('*.cbr'))
            if not cbr_files:
                continue

            # Lire la couverture depuis le premier CBR
            cover_url = f'/api/manga/{manga_folder.name}/cover'
            chapters = len(cbr_files)
            size_mb = sum(f.stat().st_size for f in cbr_files) / (1024 * 1024)

            manga_id = manga_folder.name
            progress_data = progress.get(manga_id, {})

            mangas.append({
                'id': manga_id,
                'title': manga_folder.name,
                'chapters': chapters,
                'size_mb': round(size_mb, 1),
                'cover': cover_url,
                'progress': progress_data.get('current_chapter', 0),
                'last_read': progress_data.get('last_read', '')
            })

    return jsonify({'mangas': mangas})

@app.route('/api/manga/<manga_id>/chapters')
@require_login
def manga_chapters(manga_id):
    """Liste les chapitres d'un manga"""
    settings = load_settings()
    manga_dir = Path(settings.get('manga_dir', str(MANGA_DIR)))
    manga_path = manga_dir / manga_id

    if not manga_path.exists():
        return jsonify({'error': 'Manga non trouvé'}), 404

    chapters = []
    for cbr in sorted(manga_path.rglob('*.cbr')):
        chapters.append({
            'name': cbr.stem,
            'path': str(cbr.relative_to(manga_dir)),
            'size_mb': round(cbr.stat().st_size / (1024 * 1024), 1)
        })

    return jsonify({'chapters': chapters})

@app.route('/api/manga/<manga_id>/cover')
def manga_cover(manga_id):
    """Obtient la couverture d'un manga"""
    settings = load_settings()
    manga_dir = Path(settings.get('manga_dir', str(MANGA_DIR)))
    manga_path = manga_dir / manga_id

    cbr_files = list(manga_path.glob('**/*.cbr'))
    if not cbr_files:
        return jsonify({'error': 'Pas de couverture'}), 404

    try:
        with zipfile.ZipFile(cbr_files[0], 'r') as cbr:
            images = [f for f in cbr.namelist() if f.lower().endswith(('.jpg', '.png'))]
            if images:
                with cbr.open(images[0]) as img_file:
                    img = Image.open(img_file)
                    img.thumbnail((200, 300))
                    output = BytesIO()
                    img.save(output, format='JPEG', quality=85)
                    output.seek(0)
                    return send_file(output, mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"Erreur couverture: {e}")

    return jsonify({'error': 'Erreur lecture couverture'}), 500

@app.route('/api/chapter/pages/<path:cbr_path>')
@require_login
def chapter_pages(cbr_path):
    """Liste les pages d'un chapitre"""
    settings = load_settings()
    manga_dir = Path(settings.get('manga_dir', str(MANGA_DIR)))
    full_path = manga_dir / cbr_path

    if not full_path.exists():
        return jsonify({'error': 'Chapitre non trouvé'}), 404

    try:
        with zipfile.ZipFile(full_path, 'r') as cbr:
            pages = sorted([f for f in cbr.namelist() if f.lower().endswith(('.jpg', '.png'))])
            return jsonify({'pages': pages, 'count': len(pages)})
    except Exception as e:
        logger.error(f"Erreur pages: {e}")
        return jsonify({'error': str(e)}), 500

@app.route('/api/chapter/page/<path:cbr_path>')
@require_login
def chapter_page(cbr_path):
    """Obtient une page d'un chapitre"""
    page_num = request.args.get('page', '0')
    settings = load_settings()
    manga_dir = Path(settings.get('manga_dir', str(MANGA_DIR)))
    full_path = manga_dir / cbr_path

    if not full_path.exists():
        return jsonify({'error': 'Chapitre non trouvé'}), 404

    try:
        with zipfile.ZipFile(full_path, 'r') as cbr:
            pages = sorted([f for f in cbr.namelist() if f.lower().endswith(('.jpg', '.png'))])
            if int(page_num) >= len(pages):
                return jsonify({'error': 'Page non trouvée'}), 404

            with cbr.open(pages[int(page_num)]) as page_file:
                return send_file(BytesIO(page_file.read()), mimetype='image/jpeg')
    except Exception as e:
        logger.error(f"Erreur page: {e}")
        return jsonify({'error': str(e)}), 500

# ========== ROUTES RÉGLAGES ==========

@app.route('/reglages')
@require_login
def reglages():
    """Page Réglages"""
    settings = load_settings()
    return render_template('reglages.html', version=VERSION, settings=settings)

@app.route('/api/settings/get')
@require_login
def get_settings():
    """Obtient les paramètres"""
    return jsonify(load_settings())

@app.route('/api/settings/save', methods=['POST'])
@require_login
def save_settings():
    """Sauvegarde les paramètres"""
    data = request.get_json()
    settings = load_settings()
    settings.update(data)
    save_json(SETTINGS_FILE, settings)
    return jsonify({'ok': True})

# ========== ROUTES API ==========

@app.route('/api/health')
def health():
    """Vérification de santé"""
    return jsonify({'status': 'ok', 'version': VERSION})

@app.errorhandler(404)
def not_found(e):
    return jsonify({'error': 'Non trouvé'}), 404

@app.errorhandler(500)
def server_error(e):
    logger.error(str(e))
    return jsonify({'error': 'Erreur serveur'}), 500

if __name__ == '__main__':
    port = int(os.getenv('FLASK_PORT', 5002))
    app.run(
        host='0.0.0.0',
        port=port,
        debug=os.getenv('FLASK_DEBUG', False)
    )
