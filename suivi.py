"""
➕ Séries suivies « comme Sonarr » : une série ajoutée (AniList) apparaît grisée dans la bibliothèque tant qu'elle
est vide ; les séries surveillées sont vérifiées chaque jour dans Prowlarr. Deux sortes de propositions :
  🆕 nouveau  : un torrent contient des tomes qu'on n'a pas (nouveau tome sorti, ou tome manquant) ;
  ⬆️ meilleur : la série est en Scan/Web et un torrent Digital existe (surclassement de qualité).
Rien n'est téléchargé tout seul : message Telegram + liste sur la fiche ; l'admin choisit. Fichier data/suivies.json.
"""
import json
import logging
import os
import re
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_ETAT = {"fichier": Path("suivies.json")}
_verrou = threading.Lock()
RANG_QUALITE = {"Web (chapitres)": 0, "Scan": 1, "Digital": 2}


def lire():
    try:
        d = json.loads(_ETAT["fichier"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("series", {})
    return d


def ecrire(d):
    f = _ETAT["fichier"]
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def ajouter(nom, serie=None, surveiller=True, qualite="Digital"):
    serie = serie or {}
    with _verrou:
        d = lire()
        x = d["series"].setdefault(nom, {"ajoutee": datetime.now().strftime("%Y-%m-%d"), "propositions": []})
        x.update(surveiller=bool(surveiller), qualite=qualite or "Digital")
        for k in ("anilist", "couverture", "annee"):
            if serie.get(k):
                x[k] = serie[k]
        titres = [t for t in (nom, serie.get("titre"), serie.get("original")) if t]
        x["titres"] = list(dict.fromkeys(titres + x.get("titres", [])))[:4]
        ecrire(d)
    return x


def retirer(nom):
    """Série supprimée de la bibliothèque : on arrête de la suivre (sinon elle reste affichée en grisé)."""
    with _verrou:
        d = lire()
        if d["series"].pop(nom, None) is not None:
            ecrire(d)
            return True
    return False


def renommer(ancien, nouveau):
    with _verrou:
        d = lire()
        if ancien in d["series"] and nouveau not in d["series"]:
            d["series"][nouveau] = d["series"].pop(ancien)
            ecrire(d)


def tomes_du_titre(titre: str) -> set:
    """Tomes couverts par un torrent d'après son nom : « T01-T14 », « Tomes 1 à 20 », « T07 », « Vol. 3 »."""
    t = titre.lower()
    m = re.search(r"\b(?:t|tomes?|vol\.?|volumes?)\s?\.?\s?(\d{1,3})\s?(?:-|à|a|to|\.)\s?(?:t|tome)?\.?\s?(\d{1,3})\b", t)
    if m and int(m.group(1)) <= int(m.group(2)) <= 300:
        return set(range(int(m.group(1)), int(m.group(2)) + 1))
    return {int(x) for x in re.findall(r"\b(?:t|tome|vol\.?|volume)\s?\.?\s?(\d{1,3})\b", t) if int(x) <= 300}


def propositions_pour(nom, info, resultats, deja):
    """info : {"tomes": set des tomes présents, "source": « Scan »…, "qualite": visée}. Renvoie les nouvelles propositions."""
    out, vus = [], set(deja)
    if info.get("complete") or info.get("en_cours"):          # série terminée ou téléchargement déjà lancé : rien à proposer
        return out
    possedes = info["tomes"]
    rang = RANG_QUALITE.get(info.get("source") or "", 1)
    for r in resultats:
        if r["titre"] in vus or "🇫🇷 FR" not in r["badges"]:
            continue
        couverts = tomes_du_titre(r["titre"])
        manquants = sorted(couverts - possedes)
        sorte = None
        if manquants:
            sorte = "nouveau"
        elif (possedes and info.get("qualite") == "Digital" and rang < 2 and "Digital" in r["badges"]
              and (not couverts or couverts & possedes or "Intégrale" in r["badges"])):
            sorte = "meilleur"
        if not sorte:
            continue
        vus.add(r["titre"])
        out.append({"id": uuid.uuid4().hex[:8], "type": sorte, "titre": r["titre"], "page": r.get("page", ""),
                    "taille": r.get("taille", 0), "sources": r.get("sources", 0), "badges": r["badges"],
                    "tomes": manquants[:40], "date": datetime.now().strftime("%Y-%m-%d"), "statut": "attente"})
        if len(out) >= 5:
            break
    return out


def _sans_point(titre):
    """Telegram transforme « Oda.FR » en lien (domaine) : les points des noms de torrents sont remplacés par des espaces."""
    return titre.replace(".", " ")


def verifier(nom, chercher, infos_serie):
    """Cherche dans Prowlarr pour une série suivie et garde les nouvelles propositions. Renvoie celles-ci."""
    d = lire()
    x = d["series"].get(nom)
    if not x:
        return []
    resultats, vus = [], set()
    for titre in x.get("titres", [nom])[:2]:
        for r in chercher(titre):
            if r["titre"] not in vus:
                vus.add(r["titre"])
                resultats.append(r)
    info = infos_serie(nom)
    info["qualite"] = x.get("qualite", "Digital")
    deja = [p["titre"] for p in x.get("propositions", [])]
    nouvelles = propositions_pour(nom, info, resultats, deja)
    with _verrou:
        d = lire()
        if nom in d["series"]:
            d["series"][nom].setdefault("propositions", []).extend(nouvelles)
            d["series"][nom]["propositions"] = d["series"][nom]["propositions"][-30:]
            d["series"][nom]["derniere_verif"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            ecrire(d)
    return nouvelles


def en_attente():
    return [(n, p) for n, x in lire()["series"].items() for p in x.get("propositions", []) if p["statut"] == "attente"]


def boucle(chercher, infos_serie, envoyer, adresse, actif):
    """Chaque jour (vers 7 h) : vérifie les séries surveillées ; un message Telegram groupé si du nouveau."""
    while True:
        time.sleep(600)
        try:
            maintenant = datetime.now()
            if maintenant.hour < 7 or not actif():
                continue
            jour = maintenant.strftime("%Y-%m-%d")
            for nom, x in list(lire()["series"].items()):
                if not x.get("surveiller") or (x.get("derniere_verif") or "")[:10] == jour:
                    continue
                try:
                    nouv = verifier(nom, chercher, infos_serie)
                except Exception as e:
                    logger.warning("Surveillance de %s impossible : %s", nom, e)
                    continue
                if nouv:
                    lien = adresse().rstrip("/") + "/#" + __import__("urllib.parse").parse.quote(nom) if adresse() else ""
                    envoyer(f"{'🆕' if nouv[0]['type'] == 'nouveau' else '⬆️'} MouFlanga : {nom} — {len(nouv)} proposition(s)\n"
                            + "\n".join(f"• « {_sans_point(p['titre'][:90])} »" for p in nouv)
                            + (f"\n👉 Ouvrir dans MouFlanga : {lien}" if lien else ""))
                time.sleep(20)                    # sobre avec Prowlarr et les indexeurs
        except Exception as e:
            logger.warning("Surveillance des séries : %s", e)
