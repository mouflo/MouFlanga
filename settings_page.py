"""
Page « ⚙️ Réglages » de MouFlanga (même style que les autres applis) : dossier des mangas.
- Le dossier est enregistré dans data/secrets.env (jamais sur GitHub) et lu au démarrage :
  l'appli redémarre toute seule (systemd) après l'enregistrement.
"""
import logging
import os
import threading
import time
from pathlib import Path

from flask import jsonify, render_template, request

from secrets_store import write_secret

logger = logging.getLogger(__name__)
_BAD_CHARS = set('"$`\\\n\r')     # interdits : ils casseraient le fichier data/secrets.env


def init_app(app, base_dir, version_fn, get_dirs):
    """get_dirs() -> {"manga": dossier des mangas}"""
    base_dir = Path(base_dir)
    secrets = base_dir / "data" / "secrets.env"
    import fs_browser
    fs_browser.init_app(app)

    @app.route("/reglages")
    def settings_page():
        return render_template("reglages.html", version=version_fn())

    @app.route("/api/settings/paths")
    def paths_state():
        manga = get_dirs()["manga"]
        return jsonify({"manga": manga, "manga_ok": Path(manga).is_dir()})

    @app.route("/api/settings/paths", methods=["POST"])
    def paths_save():
        body = request.get_json(silent=True) or {}
        manga = str(body.get("manga", "")).strip().rstrip("/")
        if not manga.startswith("/") or _BAD_CHARS & set(manga):
            return jsonify({"ok": False, "error": f"Chemin invalide : « {manga} » (chemin complet commençant par /, sans guillemets ni $)."}), 400
        if not Path(manga).is_dir():
            return jsonify({"ok": False, "error": f"Dossier introuvable sur le serveur : « {manga} » (le partage est-il monté ?). Rien n'a été enregistré."}), 400
        write_secret(secrets, "MANGA_DIR", manga)
        logger.info("Dossier des mangas mis à jour depuis la page web : %s", manga)
        threading.Thread(target=lambda: (time.sleep(1.5), os._exit(0)), daemon=True).start()   # systemd relance l'appli
        return jsonify({"ok": True, "message": "Enregistré. L'appli redémarre pour relire le dossier…"})
