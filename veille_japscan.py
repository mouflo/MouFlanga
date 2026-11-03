"""Veille de l'extension Japscan des applis de lecture Android (dépôt keiyoushi/extensions-source).

Une fois par jour, MouFlanga demande à GitHub s'il y a un nouveau commit sur le dossier de l'extension Japscan et, si oui, envoie un message
(titre du commit et lien). Elle ne parle qu'à GitHub, jamais à Japscan : aucune vérification Cloudflare à faire. Elle ne change aucun code
toute seule : le message dit seulement qu'il y a quelque chose à regarder. Réglage : data/veille_japscan.json."""
import logging
import time
from pathlib import Path

import reseau

logger = logging.getLogger(__name__)

DEPOT = "keiyoushi/extensions-source"
DOSSIER = "src/fr/japscan"
URL = f"https://api.github.com/repos/{DEPOT}/commits"
FICHIER = None                                   # app.py : data/veille_japscan.json
LIRE = lambda chemin, defaut: defaut             # app.py : lecture JSON
ECRIRE = lambda chemin, donnees: None            # app.py : écriture JSON


def etat() -> dict:
    d = LIRE(FICHIER, {}) if FICHIER else {}
    d = d if isinstance(d, dict) else {}
    return {"actif": bool(d.get("actif", True)), "dernier": str(d.get("dernier") or ""), "titre": str(d.get("titre") or ""),
            "date": str(d.get("date") or ""), "verifie_le": str(d.get("verifie_le") or ""), "message": str(d.get("message") or "")}


def regler(actif: bool) -> dict:
    d = etat()
    d["actif"] = bool(actif)
    ECRIRE(FICHIER, d)
    return d


def dernier_commit() -> dict:
    """{sha, titre, date, lien} du dernier commit qui touche le dossier Japscan (reseau.Panne si GitHub ne répond pas)."""
    rep = reseau.get(URL, params={"path": DOSSIER, "per_page": 1}, entetes={"Accept": "application/vnd.github+json"}, timeout=20)
    liste = rep.json()
    if not isinstance(liste, list) or not liste:
        raise reseau.Panne("github", "aucun commit renvoyé pour le dossier Japscan")
    c = liste[0]
    return {"sha": str(c.get("sha") or ""), "titre": str((c.get("commit") or {}).get("message") or "").split("\n")[0][:150],
            "date": str(((c.get("commit") or {}).get("committer") or {}).get("date") or "")[:10], "lien": str(c.get("html_url") or "")}


def verifier(envoyer=None) -> str:
    """Un passage : compare le dernier commit à celui déjà vu. Le premier passage note seulement le point de départ (pas de message).
    Rend une phrase qui dit ce qui s'est passé."""
    d = etat()
    maintenant = time.strftime("%Y-%m-%d %H:%M")
    try:
        c = dernier_commit()
    except Exception as e:                       # une panne de GitHub n'est jamais « rien de nouveau » : on le dit, on réessaiera demain
        d["message"] = f"GitHub n'a pas répondu ({e.__class__.__name__}), nouvel essai demain."
        d["verifie_le"] = maintenant
        ECRIRE(FICHIER, d)
        logger.warning("Veille Japscan : %s", d["message"])
        return d["message"]
    if not d["dernier"]:
        msg = f"Point de départ noté : dernier commit du {c['date']} (« {c['titre']} »)."
    elif c["sha"] == d["dernier"]:
        msg = "Rien de nouveau depuis la dernière vérification."
    else:
        msg = f"Nouveau changement de l'extension Japscan le {c['date']} : « {c['titre']} »."
        if envoyer:
            envoyer(f"👀 MouFlanga : l'extension Japscan des applis Android a changé ({c['date']}) : « {c['titre']} »\n{c['lien']}\n"
                    "Japscan a peut-être modifié son site : si le téléchargement Japscan ne marche plus, dis-le à Claude.")
    d.update(dernier=c["sha"], titre=c["titre"], date=c["date"], verifie_le=maintenant, message=msg)
    ECRIRE(FICHIER, d)
    logger.info("Veille Japscan : %s", msg)
    return msg


def boucle(envoyer, attente_debut: float = 900):
    """Une fois par jour (la première fois 15 minutes après le démarrage), si l'option est cochée."""
    time.sleep(attente_debut)
    while True:
        try:
            if etat()["actif"]:
                verifier(envoyer)
        except Exception as e:
            logger.warning("Veille Japscan : %s", e)
        time.sleep(86400)
