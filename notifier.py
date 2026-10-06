"""
Alertes Telegram de MouFlanga.

Réglages lus à chaque envoi (donc pris en compte sans redémarrer) :
  TELEGRAM_BOT_TOKEN : le jeton du bot (créé avec @BotFather)
  TELEGRAM_CHAT_ID   : ton identifiant Telegram (l'appli sait le détecter)
Ils sont enregistrés dans data/secrets.env (jamais sur GitHub) depuis la page ⚙️ Réglages.
Le jeton n'apparaît jamais dans les journaux ni dans les réponses de l'appli.
"""
import logging
import os
import re

import requests

logger = logging.getLogger("mouflanga.notifier")

_TOKEN_RE = re.compile(r"^\d{6,12}:[A-Za-z0-9_-]{30,50}$")
_CHAT_RE = re.compile(r"^-?\d{3,20}$")
API = "https://api.telegram.org"


def token_valide(token: str) -> bool:
    return bool(_TOKEN_RE.match(token or ""))


def chat_valide(chat_id: str) -> bool:
    return bool(_CHAT_RE.match(chat_id or ""))


def _token() -> str:
    return os.getenv("TELEGRAM_BOT_TOKEN", "").strip()


def _chat() -> str:
    return os.getenv("TELEGRAM_CHAT_ID", "").strip()


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
