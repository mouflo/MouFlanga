"""
Accès des autres applis à MouFlanga (par exemple MouFloster, pour envoyer une couverture),
avec une clé API générée depuis ⚙️ Réglages.

- La clé est montrée UNE seule fois, au moment où on la génère ; MouFlanga n'en garde que
  l'empreinte (SHA-256) et les 4 derniers caractères, dans data/secrets.env (jamais sur GitHub).
- Les autres applis l'envoient dans l'en-tête « X-Cle-API ».
- Ces routes (/api/externe/…) ne passent pas par l'écran de connexion : la clé les protège.
  Trop d'essais avec une mauvaise clé → blocage de l'adresse pendant 10 minutes.
"""
import hashlib
import hmac
import io
import logging
import os
import secrets as _secrets
import threading
import time
from pathlib import Path

from flask import jsonify, request, send_file

from secrets_store import write_secret

logger = logging.getLogger(__name__)
ENTETE = "X-Cle-API"
_ECHECS = {}                 # adresse -> [instants des mauvais essais]
_VERROU = threading.Lock()
_MAX_ECHECS, _FENETRE = 10, 600


def _empreinte(cle: str) -> str:
    return hashlib.sha256(cle.encode()).hexdigest()


def configuree() -> bool:
    return bool(os.getenv("MOUFLANGA_CLE_API_SHA256", "").strip())


def _bloquee(ip: str) -> bool:
    now = time.time()
    with _VERROU:
        essais = [t for t in _ECHECS.get(ip, []) if now - t < _FENETRE]
        _ECHECS[ip] = essais
        return len(essais) >= _MAX_ECHECS


def _cle_valide() -> bool:
    attendue = os.getenv("MOUFLANGA_CLE_API_SHA256", "").strip()
    donnee = (request.headers.get(ENTETE) or "").strip()
    ok = bool(attendue and donnee and hmac.compare_digest(_empreinte(donnee), attendue))
    if not ok:
        with _VERROU:
            _ECHECS.setdefault(request.remote_addr or "?", []).append(time.time())
    return ok


def init_app(app, base_dir, version_fn, series_fn, couverture_fn, enregistrer_fn):
    """series_fn() -> [{"name", "cover"}] ; couverture_fn(nom) -> Path de la couverture choisie ou None ;
    enregistrer_fn(nom, fichier) -> (réponse, code)."""
    fichier_secrets = Path(base_dir) / "data" / "secrets.env"

    def _garde():
        if not configuree():
            return jsonify({"ok": False, "error": "Aucune clé API dans MouFlanga : génère-la dans ⚙️ Réglages."}), 403
        if _bloquee(request.remote_addr or "?"):
            return jsonify({"ok": False, "error": "Trop d'essais avec une mauvaise clé : réessaie dans 10 minutes."}), 429
        if not _cle_valide():
            return jsonify({"ok": False, "error": "Clé API refusée par MouFlanga."}), 401
        return None

    @app.route("/api/externe/series")
    def externe_series():
        refus = _garde()
        if refus:
            return refus
        return jsonify({"ok": True, "app": "MouFlanga", "version": version_fn(), "series": series_fn()})

    @app.route("/api/externe/couverture")
    def externe_couverture():
        refus = _garde()
        if refus:
            return refus
        chemin = couverture_fn(request.args.get("id", ""))
        if chemin is None:
            return jsonify({"ok": False, "error": "Pas de couverture choisie"}), 404
        return send_file(io.BytesIO(chemin.read_bytes()), mimetype="image/jpeg")

    @app.route("/api/externe/couverture", methods=["POST"])
    def externe_couverture_envoi():
        refus = _garde()
        if refus:
            return refus
        nom = request.form.get("id", "")
        rep, code = enregistrer_fn(nom, request.files.get("image"))
        if rep.get("ok"):
            logger.info("Couverture de « %s » reçue d'une autre appli (%s)", nom, request.remote_addr)
        return jsonify(rep), code

    # ---------------- Réglages ----------------
    @app.route("/api/settings/cle-api")
    def cle_api_etat():
        fin = os.getenv("MOUFLANGA_CLE_API_FIN", "").strip()
        return jsonify({"configured": configuree(), "hint": ("…" + fin) if fin and configuree() else "",
                        "moufloster": os.getenv("MOUFLOSTER_URL", "").strip(),
                        "moufloster_externe": os.getenv("MOUFLOSTER_URL_EXTERNE", "").strip()})

    @app.route("/api/settings/cle-api", methods=["POST"])
    def cle_api_action():
        action = str((request.get_json(silent=True) or {}).get("action", ""))
        if action == "generer":
            cle = "mfl_" + _secrets.token_urlsafe(30).replace("-", "x").replace("_", "y")
            for nom, valeur in (("MOUFLANGA_CLE_API_SHA256", _empreinte(cle)), ("MOUFLANGA_CLE_API_FIN", cle[-4:])):
                write_secret(fichier_secrets, nom, valeur)
                os.environ[nom] = valeur
            logger.info("Nouvelle clé API générée (l'ancienne ne marche plus)")
            return jsonify({"ok": True, "cle": cle,
                            "message": "Nouvelle clé créée : copie-la maintenant, elle ne sera plus affichée."})
        if action == "supprimer":
            for nom in ("MOUFLANGA_CLE_API_SHA256", "MOUFLANGA_CLE_API_FIN"):
                write_secret(fichier_secrets, nom, "")
                os.environ[nom] = ""
            logger.info("Clé API supprimée : plus aucune appli ne peut envoyer de couverture")
            return jsonify({"ok": True, "message": "Clé supprimée : plus aucune appli ne peut se connecter."})
        return jsonify({"ok": False, "error": "Action inconnue"}), 400

    @app.route("/api/settings/moufloster", methods=["POST"])
    def moufloster_adresse():
        # Deux adresses : celle du réseau local (rapide) et l'adresse perso (proxy, depuis l'extérieur).
        # La page choisit selon la façon dont on est connecté à MouFlanga.
        body = request.get_json(silent=True) or {}
        adresses = {"MOUFLOSTER_URL": str(body.get("url", "")).strip().rstrip("/"),
                    "MOUFLOSTER_URL_EXTERNE": str(body.get("url_externe", "")).strip().rstrip("/")}
        for url in adresses.values():
            if url and (not url.startswith(("http://", "https://")) or set('"$`\\ \n\r') & set(url)):
                return jsonify({"ok": False, "error": f"Adresse invalide : « {url} » (elle commence par http:// ou https://)"}), 400
        for nom, url in adresses.items():
            write_secret(fichier_secrets, nom, url)
            os.environ[nom] = url
        if not any(adresses.values()):
            return jsonify({"ok": True, "message": "Adresses effacées : le bouton MouFloster est caché."})
        return jsonify({"ok": True, "message": "Adresses enregistrées."})
