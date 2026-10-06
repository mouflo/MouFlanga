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
import notifier

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

    # ------------------------------------------------------------------
    # Alertes Telegram (prises en compte tout de suite, sans redémarrage)
    # ------------------------------------------------------------------
    def _enregistrer(nom, valeur):
        write_secret(secrets, nom, valeur)
        os.environ[nom] = valeur

    @app.route("/api/settings/telegram")
    def telegram_state():
        return jsonify({
            "configured": notifier.configure(),
            "token_hint": notifier.indice_token(),      # jamais le jeton complet
            "chat_id": os.getenv("TELEGRAM_CHAT_ID", "") or notifier._chat(),
            "app_url": os.getenv("APP_URL", ""),
            "source": notifier.source_reprise(),     # nom de l'autre appli dont les réglages sont repris
        })

    @app.route("/api/settings/telegram", methods=["POST"])
    def telegram_save():
        body = request.get_json(silent=True) or {}
        action = body.get("action", "save")
        token_saisi = str(body.get("token", "")).strip()
        chat_id = str(body.get("chat_id", "")).strip()
        app_url = str(body.get("app_url", "")).strip().rstrip("/")
        token = token_saisi or notifier._token()

        for valeur in (token_saisi, chat_id, app_url):
            if _BAD_CHARS & set(valeur) or " " in valeur:
                return jsonify({"ok": False, "error": "Caractère interdit (espace, guillemet, $ ou \\) dans un champ."}), 400
        if token_saisi and not notifier.token_valide(token_saisi):
            return jsonify({"ok": False, "error": "Ce jeton n'a pas la bonne forme (il ressemble à 123456789:ABC…, donné par @BotFather)."}), 400

        if action == "detect":
            if not token:
                return jsonify({"ok": False, "error": "Colle d'abord le jeton du bot."}), 400
            ok, rep = notifier.detecter_chat(token)
            return jsonify({"ok": ok, "chat_id": rep if ok else "", "error": "" if ok else rep,
                            "message": "Identifiant trouvé." if ok else ""}), (200 if ok else 400)

        if chat_id and not notifier.chat_valide(chat_id):
            return jsonify({"ok": False, "error": "L'identifiant Telegram est un nombre (ex. 123456789)."}), 400
        if app_url and not app_url.startswith(("http://", "https://")):
            return jsonify({"ok": False, "error": "L'adresse de l'appli doit commencer par http:// ou https://"}), 400

        if action == "test":
            ok, msg = notifier.envoyer("✅ MouFlanga : les alertes Telegram fonctionnent.", token or None, chat_id or None)
            return jsonify({"ok": ok, "message": "Message de test envoyé : regarde ton Telegram." if ok else "", "error": "" if ok else msg}), (200 if ok else 400)

        if token_saisi:
            _enregistrer("TELEGRAM_BOT_TOKEN", token_saisi)
        if chat_id:
            _enregistrer("TELEGRAM_CHAT_ID", chat_id)
        _enregistrer("APP_URL", app_url)
        notifier.vider_cache()
        logger.info("Réglages Telegram mis à jour depuis la page web")
        return jsonify({"ok": True, "message": "Enregistré. Les alertes sont actives tout de suite."})
