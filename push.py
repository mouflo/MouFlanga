"""📱 Notifications sur le téléphone (Web Push), en plus de Telegram (qui reste pour l'historique).

Clés VAPID créées une fois par le serveur dans data/vapid.json (jamais sur GitHub). Chaque compte (admin ou lecteur)
abonne ses appareils et choisit ses sujets ; data/push.json garde les abonnements. Un abonnement refusé par le
navigateur (désinstallé, permission retirée) est oublié tout seul.
"""
import base64
import json
import logging
import threading
from pathlib import Path

logger = logging.getLogger("mouflanga")

SUJETS = {
    "alertes": "Alertes de l'appli (torrents, imports, vérifications, plantages)",
    "demandes": "Mes demandes (acceptée, disponible)",
    "nouveaux": "Nouveaux tomes des séries que je lis",
}
SUJETS_ADMIN = ("alertes", "demandes", "nouveaux")
SUJETS_LECTEUR = ("demandes", "nouveaux")
_ETAT = {"dossier": None}
_VERROU = threading.Lock()


def _fichier(nom):
    return Path(_ETAT["dossier"]) / nom


def cle_publique() -> str:
    """Clé publique VAPID (format applicationServerKey), créée au premier appel."""
    f = _fichier("vapid.json")
    with _VERROU:
        if not f.exists():
            from py_vapid import Vapid
            from cryptography.hazmat.primitives import serialization
            v = Vapid()
            v.generate_keys()
            prive = v.private_key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
                                                serialization.NoEncryption()).decode()
            pub = v.public_key.public_bytes(serialization.Encoding.X962, serialization.PublicFormat.UncompressedPoint)
            f.parent.mkdir(parents=True, exist_ok=True)
            f.write_text(json.dumps({"prive": prive, "public": base64.urlsafe_b64encode(pub).decode().rstrip("=")}))
            f.chmod(0o600)
        return json.loads(f.read_text())["public"]


def _lire():
    try:
        d = json.loads(_fichier("push.json").read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def _ecrire(d):
    f = _fichier("push.json")
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False), encoding="utf-8")
    tmp.chmod(0o600)
    tmp.replace(f)


def abonner(compte: str, abonnement: dict, sujets, appareil: str = ""):
    if not isinstance(abonnement, dict) or not str(abonnement.get("endpoint", "")).startswith("https://"):
        raise ValueError("Abonnement invalide")
    with _VERROU:
        d = _lire()
        liste = [a for a in d.get(compte, []) if a["sub"].get("endpoint") != abonnement["endpoint"]]
        liste.append({"sub": abonnement, "sujets": [s for s in sujets if s in SUJETS], "appareil": appareil[:80]})
        d[compte] = liste[-10:]
        _ecrire(d)


def desabonner(compte: str, endpoint: str):
    with _VERROU:
        d = _lire()
        d[compte] = [a for a in d.get(compte, []) if a["sub"].get("endpoint") != endpoint]
        _ecrire(d)


def abonnement(compte: str, endpoint: str):
    return next((a for a in _lire().get(compte, []) if a["sub"].get("endpoint") == endpoint), None)


def envoyer(comptes, sujet: str, titre: str, texte: str, url: str = "/"):
    """Envoie à chaque appareil des comptes donnés (None = tous) abonné à ce sujet. En arrière-plan, sans jamais planter."""
    def travail():
        try:
            from pywebpush import webpush, WebPushException
            from py_vapid import Vapid
            prive = Vapid.from_pem(json.loads(_fichier("vapid.json").read_text())["prive"].encode())   # clé PEM → objet que pywebpush accepte
        except Exception as e:
            logger.info("Notifications téléphone indisponibles : %s", e.__class__.__name__)
            return
        message = json.dumps({"titre": titre[:120], "texte": texte[:400], "url": url})
        oublier = []
        for compte, liste in _lire().items():
            if comptes is not None and compte not in comptes:
                continue
            for a in liste:
                if sujet not in a.get("sujets", []):
                    continue
                try:
                    webpush(a["sub"], message, vapid_private_key=prive, vapid_claims={"sub": "mailto:mouflanga@localhost"}, timeout=10)
                except WebPushException as e:
                    if getattr(e, "response", None) is not None and e.response.status_code in (404, 410):
                        oublier.append((compte, a["sub"]["endpoint"]))
                    else:
                        logger.info("Notification téléphone refusée : %s", str(e)[:120])
                except Exception as e:
                    logger.info("Notification téléphone impossible : %s", e.__class__.__name__)
        for compte, endpoint in oublier:
            desabonner(compte, endpoint)
    if _ETAT["dossier"]:
        threading.Thread(target=travail, daemon=True).start()
