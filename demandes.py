"""
📮 Demandes de mangas : un lecteur cherche une série (AniList) et la demande ; l'admin accepte ou refuse.
Fichier data/demandes.json. Tant qu'une demande attend, un rappel Telegram groupé part à la fréquence choisie
(chaque jour, chaque semaine ou jamais, à l'heure voulue) ; il s'arrête dès que tout est traité.
"""
import json
import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

import requests
from flask import jsonify, request

logger = logging.getLogger(__name__)

STATUTS = {"FINISHED": "terminée", "RELEASING": "en cours", "NOT_YET_RELEASED": "pas encore sortie",
           "CANCELLED": "arrêtée", "HIATUS": "en pause"}
_ETAT = {"fichier": Path("demandes.json")}
_verrou = threading.Lock()


def _lire():
    try:
        d = json.loads(_ETAT["fichier"].read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    d.setdefault("demandes", [])
    d.setdefault("rappel", {"frequence": "jour", "heure": 19, "dernier": ""})
    return d


def _ecrire(d):
    f = _ETAT["fichier"]
    f.parent.mkdir(parents=True, exist_ok=True)
    tmp = f.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def chercher_anilist(q):
    """Séries correspondant au texte tapé (les 8 plus proches)."""
    requete = ("query($s:String){Page(perPage:8){media(search:$s,type:MANGA,sort:SEARCH_MATCH){id title{romaji english native} "
               "coverImage{medium} startDate{year} status volumes format countryOfOrigin}}}")
    r = requests.post("https://graphql.anilist.co", json={"query": requete, "variables": {"s": q}}, timeout=15)
    r.raise_for_status()
    out = []
    for m in ((r.json().get("data") or {}).get("Page") or {}).get("media") or []:
        t = m.get("title") or {}
        out.append({"anilist": m["id"], "titre": t.get("english") or t.get("romaji") or t.get("native") or "?",
                    "original": t.get("romaji") if t.get("english") and t.get("romaji") != t.get("english") else "",
                    "couverture": (m.get("coverImage") or {}).get("medium") or "",
                    "annee": (m.get("startDate") or {}).get("year"), "statut": STATUTS.get(m.get("status"), ""),
                    "tomes": m.get("volumes"), "type": {"KR": "manhwa", "CN": "manhua"}.get(m.get("countryOfOrigin"), "")})
    return out


def _message_rappel(attente, adresse):
    lignes = [f"📮 MouFlanga : {len(attente)} demande{'s' if len(attente) > 1 else ''} en attente"]
    lignes += [f"• {x['titre']} (par {x['par']}, le {x['date'][:10]})" for x in attente[:15]]
    if adresse:
        lignes.append(adresse.rstrip("/") + "/#demandes")
    return "\n".join(lignes)


def _boucle_rappels(envoyer, adresse):
    """Toutes les 5 minutes : rappel dû ? (heure passée, et pas déjà envoyé aujourd'hui / cette semaine)."""
    while True:
        time.sleep(300)
        try:
            with _verrou:
                d = _lire()
                rp, attente = d["rappel"], [x for x in d["demandes"] if x["statut"] == "attente"]
                maintenant = datetime.now()
                if not attente or rp.get("frequence") == "jamais" or maintenant.hour < int(rp.get("heure", 19)):
                    continue
                dernier = rp.get("dernier") or "2000-01-01"
                ecart = 7 if rp.get("frequence") == "semaine" else 1
                if datetime.strptime(dernier, "%Y-%m-%d").date() > (maintenant - timedelta(days=ecart)).date():
                    continue
                rp["dernier"] = maintenant.strftime("%Y-%m-%d")
                _ecrire(d)
            envoyer(_message_rappel(attente, adresse()))
            logger.info("Rappel des demandes envoyé (%d en attente)", len(attente))
        except Exception as e:
            logger.warning("Rappel des demandes impossible : %s", e)


def init_app(app, data_dir, envoyer, role, utilisateur, adresse, demarrer=True):
    """envoyer(texte) : Telegram ; role()/utilisateur() : compte connecté ; adresse() : adresse de l'appli (lien)."""
    _ETAT["fichier"] = Path(data_dir) / "demandes.json"

    def vue(x):
        return {k: x.get(k) for k in ("id", "titre", "original", "couverture", "annee", "statut", "par", "date", "motif", "traitee", "anilist")}

    @app.route("/api/demandes")
    def demandes_liste():
        d, admin = _lire(), role() == "admin"
        liste = d["demandes"] if admin else [x for x in d["demandes"] if x["par"] == utilisateur()]
        liste = sorted(liste, key=lambda x: (x["statut"] != "attente", x["date"]), reverse=False)
        rep = {"admin": admin, "demandes": [vue(x) for x in liste],
               "attente": sum(1 for x in d["demandes"] if x["statut"] == "attente")}
        if admin:
            rep["rappel"] = d["rappel"]
        return jsonify(rep)

    @app.route("/api/demandes/chercher")
    def demandes_chercher():
        q = (request.args.get("q") or "").strip()
        if len(q) < 2:
            return jsonify({"resultats": []})
        try:
            res = chercher_anilist(q[:80])
        except Exception as e:
            logger.warning("Recherche AniList impossible : %s", e)
            return jsonify({"error": "La recherche ne répond pas pour le moment, réessaie dans un instant."}), 502
        deja = {x["anilist"]: x["statut"] for x in _lire()["demandes"] if x["statut"] != "refuse"}
        for r in res:
            r["deja"] = deja.get(r["anilist"], "")
        return jsonify({"resultats": res})

    @app.route("/api/demandes", methods=["POST"])
    def demandes_action():
        body = request.get_json(silent=True) or {}
        action, qui, admin = str(body.get("action", "")), utilisateur(), role() == "admin"
        with _verrou:
            d = _lire()
            if action == "creer":
                a = body.get("serie") or {}
                try:
                    aid = int(a.get("anilist"))
                except (TypeError, ValueError):
                    return jsonify({"ok": False, "error": "Série inconnue"}), 400
                if any(x["anilist"] == aid and x["statut"] == "attente" for x in d["demandes"]):
                    return jsonify({"ok": False, "error": "Cette série est déjà demandée."}), 409
                if sum(1 for x in d["demandes"] if x["par"] == qui and x["statut"] == "attente") >= 20:
                    return jsonify({"ok": False, "error": "Tu as déjà 20 demandes en attente."}), 429
                x = {"id": uuid.uuid4().hex[:10], "anilist": aid, "titre": str(a.get("titre", "?"))[:120],
                     "original": str(a.get("original", ""))[:120], "couverture": str(a.get("couverture", ""))[:300]
                     if str(a.get("couverture", "")).startswith("https://") else "",
                     "annee": a.get("annee") if isinstance(a.get("annee"), int) else None,
                     "par": qui, "date": datetime.now().strftime("%Y-%m-%d %H:%M"), "statut": "attente", "motif": "", "traitee": ""}
                d["demandes"].append(x)
                _ecrire(d)
                message = f"Demande envoyée : « {x['titre']} »."
                texte = f"📮 MouFlanga : {qui} demande « {x['titre']} »" + (f" ({x['annee']})" if x["annee"] else "")
                if adresse():
                    texte += "\n" + adresse().rstrip("/") + "/#demandes"
                threading.Thread(target=envoyer, args=(texte,), daemon=True).start()
            elif action == "retirer":
                x = next((x for x in d["demandes"] if x["id"] == body.get("id")), None)
                if not x or (x["par"] != qui and not admin) or x["statut"] != "attente":
                    return jsonify({"ok": False, "error": "Demande introuvable"}), 404
                d["demandes"].remove(x)
                _ecrire(d)
                message = "Demande retirée."
            elif action in ("accepter", "refuser"):
                if not admin:
                    return jsonify({"ok": False, "error": "Réservé à l'admin"}), 403
                x = next((x for x in d["demandes"] if x["id"] == body.get("id")), None)
                if not x:
                    return jsonify({"ok": False, "error": "Demande introuvable"}), 404
                x["statut"] = "accepte" if action == "accepter" else "refuse"
                x["motif"] = str(body.get("motif", "")).strip()[:200]
                x["traitee"] = datetime.now().strftime("%Y-%m-%d %H:%M")
                _ecrire(d)
                message = f"« {x['titre']} » : " + ("acceptée." if action == "accepter" else "refusée.")
            elif action == "rappel":
                if not admin:
                    return jsonify({"ok": False, "error": "Réservé à l'admin"}), 403
                frequence = body.get("frequence") if body.get("frequence") in ("jour", "semaine", "jamais") else "jour"
                try:
                    heure = min(23, max(0, int(body.get("heure", 19))))
                except (TypeError, ValueError):
                    heure = 19
                d["rappel"].update(frequence=frequence, heure=heure)
                _ecrire(d)
                message = "Rappels coupés." if frequence == "jamais" else \
                    f"Rappel {'chaque jour' if frequence == 'jour' else 'chaque semaine'} à {heure} h tant qu'une demande attend."
            else:
                return jsonify({"ok": False, "error": "Action inconnue"}), 400
        logger.info("Demandes : %s par %s", action, qui)
        return jsonify({"ok": True, "message": message})

    if demarrer:
        threading.Thread(target=_boucle_rappels, args=(envoyer, adresse), daemon=True).start()
