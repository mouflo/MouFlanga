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
_cache = {"quand": 0.0, "resultat": None, "details": []}
_IGNORER = {"venv", ".venv", "node_modules", ".git", "__pycache__", "site-packages", "icons", "docs", "ui",
            "templates", "tests", "covers", "cache", "logs"}
_SUFFIXES = {".env", ".json", ".ini", ".conf", ".cfg", ".yml", ".yaml", ".toml"}
_CLE_TELEGRAM = re.compile(r"telegram|(^|_)tg(_|$)|chat|bot", re.I)
_CLE_CHAT = re.compile(r"chat|((telegram|(^|_)tg)[a-z0-9_]*(id|user|dest))", re.I)
_SEPARATEUR = re.compile(r"\s*[=:]\s*")


def _paires_texte(fichier: Path):
    """Paires clé/valeur d'un fichier de type .env, .ini ou .yml (une par ligne)."""
    for ligne in fichier.read_text(encoding="utf-8", errors="ignore").splitlines():
        ligne = ligne.strip()
        if not ligne or ligne.startswith(("#", ";", "//")):
            continue
        morceaux = _SEPARATEUR.split(ligne, maxsplit=1)
        if len(morceaux) == 2:
            yield morceaux[0].replace("export ", "").strip(" -\"'"), morceaux[1].strip().strip("\"',")


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


def _fichiers_reglages(appli: Path):
    """Fichiers de réglages probables d'une appli (3 niveaux de dossiers au plus, taille raisonnable)."""
    n = 0
    for racine, dossiers, fichiers in os.walk(appli):
        profondeur = len(Path(racine).relative_to(appli).parts)
        dossiers[:] = [d for d in dossiers if d not in _IGNORER] if profondeur < 3 else []
        for nom in fichiers:
            p = Path(racine) / nom
            bas = nom.lower()
            if p.suffix.lower() in _SUFFIXES or bas.startswith(".env") or "secret" in bas:
                try:
                    if p.suffix.lower() != ".py" and p.stat().st_size <= 262144:
                        n += 1
                        if n > 200:
                            return
                        yield p
                except OSError:
                    continue


def _analyser():
    """Cherche les réglages Telegram d'une autre appli. Renvoie (résultat, détails lisibles).

    résultat = (jeton, identifiant ou "", nom de l'appli, fichier) ou None.
    Un jeton est reconnu à sa FORME (123456789:ABC…), quel que soit le nom de la clé.
    Les détails ne contiennent que des noms de fichiers et de clés, jamais de valeurs.
    """
    if time.time() - _cache["quand"] < 60 and _cache["details"]:
        return _cache["resultat"], _cache["details"]
    details, resultat = [], None
    try:
        applis = sorted(p for p in RACINE_APPLIS.glob("*") if p.is_dir() and p.resolve() != _DOSSIER_ICI)
    except OSError:
        applis = []
    details.append(f"Applis cherchées sous {RACINE_APPLIS} : " + (", ".join(a.name for a in applis) or "aucune"))
    for appli in applis:
        analyses, cles_vues = 0, set()
        for f in _fichiers_reglages(appli):
            try:
                paires = list(_paires_json(f) if f.suffix.lower() == ".json" else _paires_texte(f))
            except OSError:
                continue
            analyses += 1
            jeton = next((v for _, v in paires if token_valide(v)), "")
            chat = next((v for k, v in paires if _CLE_CHAT.search(k) and chat_valide(v) and not token_valide(v)), "")
            cles_vues.update(k for k, _ in paires if _CLE_TELEGRAM.search(k))
            if jeton and not resultat:
                resultat = (jeton, chat, appli.name, str(f.relative_to(appli)))
                details.append(f"  ✅ {appli.name}/{f.relative_to(appli)} : jeton trouvé ({'…' + jeton[-4:]}), "
                               f"identifiant {'trouvé' if chat else 'NON trouvé (détection automatique à l’envoi)'}")
        details.append(f"  {appli.name} : {analyses} fichier(s) de réglages lu(s)"
                       + (f" ; clés évoquant Telegram : {', '.join(sorted(cles_vues)[:12])}" if cles_vues else " ; aucune clé évoquant Telegram"))
    if not resultat:
        details.append("  ❌ Aucun jeton Telegram trouvé dans les fichiers .env/.json/.ini/.yml des autres applis")
    _cache.update(quand=time.time(), resultat=resultat, details=details)
    return resultat, details


def diagnostic() -> list[str]:
    """Lignes pour le rapport de l'appli (aucune valeur secrète)."""
    perso = bool(os.getenv("TELEGRAM_BOT_TOKEN", "").strip())
    lignes = [f"Telegram : réglages propres à MouFlanga : {'oui' if perso else 'non'}"]
    lignes += _analyser()[1]
    return lignes


def _chercher_ailleurs():
    r = _analyser()[0]
    return r[:3] if r else None


def vider_cache():
    _cache.update(quand=0.0, resultat=None, details=[])


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
    """Prêt à envoyer : un jeton suffit (l'identifiant se détecte tout seul s'il manque)."""
    return bool(_token())


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
    if token and not chat_id:
        # Jeton connu mais pas d'identifiant : on le déduit du dernier message reçu par le bot
        ok, trouve = detecter_chat(token)
        if ok:
            chat_id = trouve
            logger.info("Identifiant Telegram détecté automatiquement")
        else:
            return False, "Identifiant Telegram introuvable : " + trouve
    if not token:
        return False, "Aucun jeton Telegram : MouFlanga n'en a pas et n'en a trouvé chez aucune autre appli (voir le rapport, section Telegram)."
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
