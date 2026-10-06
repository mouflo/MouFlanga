"""
Alertes Telegram de MouFlanga.

Réglages lus à chaque envoi (donc pris en compte sans redémarrer) :
  TELEGRAM_BOT_TOKEN : le jeton du bot (créé avec @BotFather)
  TELEGRAM_CHAT_ID   : ton identifiant Telegram (l'appli sait le détecter)
Ils sont enregistrés dans data/secrets.env (jamais sur GitHub) depuis la page ⚙️ Réglages.
Si MouFlanga n'a pas les siens, il reprend (en lecture seule) ceux d'une autre appli du serveur sous /opt.
Le jeton n'apparaît jamais dans les journaux ni dans les réponses de l'appli.
"""
import json
import logging
import os
import re
import time
from pathlib import Path

import requests

logger = logging.getLogger("mouflanga.notifier")

_TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,50}$")
_CHAT_RE = re.compile(r"^-?\d{3,20}$")
API = "https://api.telegram.org"


def token_valide(token: str) -> bool:
    return bool(_TOKEN_RE.match(token or ""))


def chat_valide(chat_id: str) -> bool:
    return bool(_CHAT_RE.match(chat_id or ""))


# ----------------------------------------------------------------------
# Reprise automatique des réglages Telegram des autres applis du serveur
# ----------------------------------------------------------------------
RACINE_APPLIS = Path("/opt")          # là où vivent MouFloster, MouFlanimeXer, MouFlopening…
_DOSSIER_ICI = Path(__file__).resolve().parent
_cache = {"quand": 0.0, "valeur": None}
_CLE_TOKEN = re.compile(r"(TELEGRAM|(^|_)TG)[A-Z0-9_]*(TOKEN|BOT)", re.I)
_CLE_CHAT = re.compile(r"(TELEGRAM|(^|_)TG)[A-Z0-9_]*(CHAT|USER|DEST|ID)", re.I)


def _paires_env(fichier: Path):
    for ligne in fichier.read_text(encoding="utf-8", errors="ignore").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith("#") or "=" not in ligne:
            continue
        cle, _, val = ligne.partition("=")
        yield cle.replace("export ", "").strip(), val.strip().strip("\"'")


def _paires_json(fichier: Path):
    try:
        donnees = json.loads(fichier.read_text(encoding="utf-8", errors="ignore"))
    except (ValueError, OSError):
        return
    # On recolle le chemin complet : {"telegram": {"bot_token": …}} devient « telegram_bot_token »
    pile = [("", donnees)] if isinstance(donnees, dict) else []
    while pile:
        prefixe, d = pile.pop()
        for cle, val in d.items():
            nom = f"{prefixe}_{cle}" if prefixe else str(cle)
            if isinstance(val, dict):
                pile.append((nom, val))
            elif isinstance(val, (str, int)) and not isinstance(val, bool):
                yield nom, str(val)


def _chercher_ailleurs():
    """(jeton, identifiant, nom de l'appli) trouvés chez une autre appli du serveur, sinon None.

    Lecture seule, sur les fichiers de réglages habituels ; seules les valeurs qui ont la bonne forme
    d'un jeton / identifiant Telegram sont retenues. Rien n'est écrit ni journalisé.
    """
    if time.time() - _cache["quand"] < 60:
        return _cache["valeur"]
    trouve = None
    try:
        for appli in sorted(p for p in RACINE_APPLIS.glob("*") if p.is_dir() and p.resolve() != _DOSSIER_ICI):
            candidats = [appli / "data" / "secrets.env", appli / ".env", appli / "data" / "settings.json",
                         appli / "data" / "config.json", appli / "config.json", appli / "settings.json"]
            for f in candidats:
                if not f.is_file():
                    continue
                jeton = chat = ""
                for cle, val in (_paires_json(f) if f.suffix == ".json" else _paires_env(f)):
                    if not jeton and _CLE_TOKEN.search(cle) and token_valide(val):
                        jeton = val
                    elif not chat and _CLE_CHAT.search(cle) and chat_valide(val):
                        chat = val
                if jeton and chat:
                    trouve = (jeton, chat, appli.name)
                    break
            if trouve:
                break
    except OSError:
        trouve = None
    _cache.update(quand=time.time(), valeur=trouve)
    return trouve


def vider_cache():
    _cache.update(quand=0.0, valeur=None)


def source_reprise() -> str:
    """Nom de l'appli dont on reprend les réglages (vide si MouFlanga a les siens)."""
    if os.getenv("TELEGRAM_BOT_TOKEN", "").strip() and os.getenv("TELEGRAM_CHAT_ID", "").strip():
        return ""
    t = _chercher_ailleurs()
    return t[2] if t else ""


def _token() -> str:
    perso = os.getenv("TELEGRAM_BOT_TOKEN", "").strip()
    if perso:
        return perso
    t = _chercher_ailleurs()
    return t[0] if t else ""


def _chat() -> str:
    perso = os.getenv("TELEGRAM_CHAT_ID", "").strip()
    if perso:
        return perso
    t = _chercher_ailleurs()
    return t[1] if t else ""


def configure() -> bool:
    return bool(_token() and _chat())


def indice_token() -> str:
    """Ce qu'on peut afficher du jeton : seulement les 4 derniers caractères."""
    t = _token()
    return ("…" + t[-4:]) if t else ""


def _propre(texte: str, token: str) -> str:
    """Retire le jeton d'un message d'erreur (les erreurs réseau contiennent l'adresse complète)."""
    return str(texte).replace(token, "***") if token else str(texte)


def _appel(token: str, methode: str, donnees: dict | None = None, timeout: int = 15) -> tuple[bool, dict | str]:
    try:
        r = requests.post(f"{API}/bot{token}/{methode}", json=donnees or {}, timeout=timeout)
        try:
            corps = r.json()
        except ValueError:
            return False, f"Réponse inattendue de Telegram (code {r.status_code})"
        if r.ok and corps.get("ok"):
            return True, corps
        return False, corps.get("description") or f"Erreur Telegram (code {r.status_code})"
    except requests.RequestException as e:
        return False, "Telegram injoignable : " + _propre(e.__class__.__name__ + " " + str(e), token)[:150]


def envoyer(texte: str, token: str | None = None, chat_id: str | None = None) -> tuple[bool, str]:
    """Envoie un message. Renvoie (réussi, message lisible)."""
    token = token or _token()
    chat_id = chat_id or _chat()
    if not token or not chat_id:
        return False, "Telegram n'est pas réglé (jeton ou identifiant manquant)."
    ok, rep = _appel(token, "sendMessage", {"chat_id": chat_id, "text": texte, "disable_web_page_preview": True})
    if ok:
        return True, "Message envoyé."
    logger.warning("Envoi Telegram échoué : %s", _propre(rep, token))
    return False, str(rep)


def detecter_chat(token: str) -> tuple[bool, str]:
    """Trouve ton identifiant à partir du dernier message que tu as envoyé au bot."""
    ok, rep = _appel(token, "getUpdates", {"limit": 20, "timeout": 0})
    if not ok:
        return False, str(rep)
    for m in reversed(rep.get("result", [])):
        msg = m.get("message") or m.get("my_chat_member") or {}
        chat = msg.get("chat") or {}
        if chat.get("type") == "private" and chat.get("id"):
            return True, str(chat["id"])
    return False, "Aucun message reçu : ouvre ton bot dans Telegram, envoie-lui « bonjour », puis réessaie."
