"""
➕ Séries suivies « comme Sonarr » : une série ajoutée (AniList) apparaît grisée dans la bibliothèque tant qu'elle
est vide ; les séries surveillées sont vérifiées chaque jour dans Prowlarr. Deux sortes de propositions :
  🆕 nouveau  : un torrent contient des tomes qu'on n'a pas (nouveau tome sorti, ou tome manquant) ;
  ⬆️ meilleur : la série est en Scan/Web et un torrent Digital existe (surclassement de qualité).
Comme Sonarr, un seul choix par tome : le meilleur torrent d'après le profil (jamais deux propositions pour le même tome).
Par défaut rien n'est téléchargé tout seul (message Telegram + liste sur la fiche, l'admin choisit) ; avec l'interrupteur 🤖 Auto
d'une série, les tomes manquants partent tout seuls. Le flux des nouveautés de Prowlarr est lu toutes les 15 minutes : une série
surveillée qui y apparaît est vérifiée tout de suite. Fichier data/suivies.json.
"""
import json
import correspondance
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
MAX_PROPOSITIONS = 40          # propositions gardées par vérification (une par tome ou groupe de tomes)
SOURCES_SAINES = 2             # en dessous, un torrent risque de rester bloqué : il passe après les autres à score égal
AUTO_MAX_JOUR = 40             # 🤖 torrents lancés tout seuls par jour, toutes séries confondues
FLUX_INTERVALLE = 900          # 📡 lecture du flux des nouveautés : toutes les 15 minutes
FLUX_REPOS = 3600              # une série n'est pas revérifiée par le flux moins d'une heure après sa dernière vérification


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
        # d'où vient la série (AniList, MangaDex, saisie à la main…) et ce qu'on sait d'elle
        for k in ("anilist", "mangadex", "mangaupdates", "couverture", "annee", "source", "auteur", "editeur", "lien"):
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


_OFFICIEL = re.compile(r"digital|officiel|num[ée]rique|neo[ ._-]?rip[ ._-]?club", re.I)


def est_officiel(titre: str) -> bool:
    """Un torrent d'ebook officiel (Digital, Neo Rip Club…) ? « eBook » seul ne suffit pas : ebdz appelle ainsi ses scans traduits."""
    t = titre or ""
    return bool(_OFFICIEL.search(t)) or (bool(re.search(r"e-?book", t, re.I)) and not re.search(r"ebdz", t, re.I))


def tomes_ameliorables(r: dict, deja_la, info: dict) -> set:
    """Parmi les tomes déjà là que ce torrent apporte, ceux qu'il vaut la peine de remplacer :
    - noté « Scantrad » ou « Scan… » (source du tome) alors que le torrent est un ebook officiel ;
    - ou, avec un profil, provenance moins bien notée que ce torrent et sous le score d'arrêt du profil (provenance inconnue : jamais)."""
    sources, scores, arret = info.get("sources_tomes") or {}, info.get("scores_tomes") or {}, info.get("arret")
    out = set()
    for t in deja_la:
        s = str(sources.get(str(t)) or sources.get(t) or "")
        if s and (s == "Scantrad" or s.lower().startswith("scan")) and est_officiel(r.get("titre")):
            out.add(t)
        elif info.get("profil") and t in scores and scores[t] < r.get("score", 0) and (arret is None or scores[t] < arret):
            out.add(t)
    return out


def tomes_du_titre(titre: str) -> set:
    """Tomes couverts par un torrent d'après son nom : « T01-T14 », « Tomes 1 à 20 », « T07 », « Vol. 3 »."""
    t = titre.lower()
    m = re.search(r"[\[(]\s*(?:t|tomes?|vol\.?)?\s?(\d{1,3})\s*(?:-|à|a|to)\s*(?:t|tome)?\s?(\d{1,3})\s*[\])]", t)
    if m and 1 <= int(m.group(1)) <= int(m.group(2)) <= 300:
        return set(range(int(m.group(1)), int(m.group(2)) + 1))
    m = re.search(r"\b(?:t|tomes?|vol\.?|volumes?)\s?\.?\s?(\d{1,3})\s?(?:-|à|a|to|\.)\s?(?:t|tome)?\.?\s?(\d{1,3})\b", t)
    if m and int(m.group(1)) <= int(m.group(2)) <= 300:
        return set(range(int(m.group(1)), int(m.group(2)) + 1))
    return {int(x) for x in re.findall(r"\b(?:t|tome|vol\.?|volume)\s?\.?\s?(\d{1,3})\b", t) if int(x) <= 300}


def choisir(candidats, cle) -> list:
    """Un seul torrent par tome, comme Sonarr. candidats : [(résultat, tomes utiles)] ; on prend à chaque fois le meilleur d'après
    `cle(résultat, tomes encore à couvrir)`, puis on retire ses tomes des autres. Renvoie [(résultat, tomes qu'il apporte)]."""
    restants = set().union(*[set(c) for _, c in candidats]) if candidats else set()
    choisis = []
    while restants:
        dispo = [(r, set(c) & restants) for r, c in candidats if set(c) & restants and all(r is not x for x, _ in choisis)]
        if not dispo:
            break
        r, c = max(dispo, key=lambda x: cle(x[0], x[1]))
        choisis.append((r, c))
        restants -= c
    return choisis


def cle_torrent(r: dict, utiles: set, couverts=None) -> tuple:
    """Ordre de préférence entre deux torrents pour les mêmes tomes : score du profil, puis assez de sources pour ne pas rester bloqué,
    puis pas de gaspillage (un pack des tomes 1 à 32 pour 2 tomes manquants passe après les tomes seuls, s'ils existent), puis le plus
    de tomes utiles, puis le moins de tomes en trop, puis le nombre de sources."""
    couverts = couverts if couverts is not None else tomes_du_titre(r.get("titre") or "")
    trop = len(set(couverts) - set(utiles))
    return (r.get("score", 0), (r.get("sources") or 0) >= SOURCES_SAINES, trop <= max(2, 2 * len(utiles)), len(utiles), -trop,
            r.get("sources") or 0)


def propositions_pour(nom, info, resultats, deja):
    """info : {"tomes": set des tomes présents, "source": « Scan »…, "qualite": visée, "equipe": équipe principale,
    "equipe_tomes": {tome: équipe}, "tomes_en_cours": tomes déjà en téléchargement, "deja_pris": torrents déjà envoyés}.
    deja : noms de torrents à ne plus proposer. Renvoie les propositions, un seul torrent par tome (le meilleur d'après le profil,
    la MÊME ÉQUIPE en premier ⭐), au plus MAX_PROPOSITIONS."""
    import provenance
    if info.get("complete") or info.get("en_cours"):          # série terminée, ou torrent en cours dont on ne connaît pas les tomes
        return []
    en_cours = set(info.get("tomes_en_cours") or ())
    presents = set(info["tomes"])
    possedes = presents | en_cours                             # un tome en téléchargement compte comme là
    rang = RANG_QUALITE.get(info.get("source") or "", 1)
    equipe = info.get("equipe") or ""
    meme = lambda r: bool(equipe) and provenance.meme_equipe(provenance.equipe_torrent(r["titre"]), equipe)
    exclus = set(deja) | set(info.get("deja_pris") or ())
    cands = {"nouveau": [], "equipe": [], "meilleur": []}
    couverts_de, serie_entiere = {}, []
    for r in resultats:
        if r["titre"] in exclus or r.get("rejet") or ("🇫🇷 FR" not in r["badges"] and not r.get("profil")):
            continue
        couverts = tomes_du_titre(r["titre"])
        couverts_de[id(r)] = couverts
        manquants = couverts - possedes
        la = (couverts & presents) - en_cours
        # tomes déjà là mais d'une autre équipe, que l'équipe de la série sort enfin (NoFace696 → Paprika)
        autres = {t for t in la if (info.get("equipe_tomes") or {}).get(t) and not provenance.meme_equipe(info["equipe_tomes"][t], equipe)}
        mieux = tomes_ameliorables(r, la, info) if la else set()
        if manquants:
            cands["nouveau"].append((r, manquants))
        elif meme(r) and autres:
            cands["equipe"].append((r, autres))
        elif mieux:
            # un tome déjà là n'est proposé que s'il est en scan alors que ce torrent est officiel, ou s'il vaut PLUS de points d'après le profil
            cands["meilleur"].append((r, mieux))
        elif (not info.get("profil") and presents and info.get("qualite") == "Digital" and rang < 2 and "Digital" in r["badges"]
              and (not couverts or couverts & presents or "Intégrale" in r["badges"])):
            serie_entiere.append(r)                            # série en scan, torrent Digital sans tomes précis : toute la série
    cle = lambda r, utiles: (meme(r), (r.get("sources") or 0) > 0) + cle_torrent(r, utiles, couverts_de.get(id(r)))
    out = []
    for sorte in ("nouveau", "equipe", "meilleur"):
        for r, tomes in choisir(cands[sorte], cle):
            out.append((sorte, r, sorted(tomes)))
    if serie_entiere:
        out.append(("meilleur", max(serie_entiere, key=lambda r: cle(r, set())), []))
    return [{"id": uuid.uuid4().hex[:8], "type": sorte, "titre": r["titre"], "page": r.get("page", ""), "lien": r.get("lien") or "",
             "taille": r.get("taille", 0), "sources": r.get("sources", 0), "score": r.get("score", 0),
             "badges": (["⭐ même équipe"] if meme(r) else []) + list(r["badges"]), "meme_equipe": meme(r),
             "tomes": tomes[:40], "date": datetime.now().strftime("%Y-%m-%d"), "statut": "attente"}
            for sorte, r, tomes in out[:MAX_PROPOSITIONS]]


def dedoublonner(propositions) -> int:
    """Propositions en attente gardées avant le « un seul choix par tome » : celles dont tous les tomes sont déjà apportés par une
    proposition mieux notée passent en « ignoré » (doublon). Renvoie leur nombre."""
    attente = [p for p in propositions if p.get("statut") == "attente" and p.get("tomes")]
    vus, n = set(), 0
    for p in sorted(attente, key=lambda p: (-(p.get("score") or 0), -(p.get("sources") or 0), p.get("date") or "")):
        tomes = {int(x) for x in p["tomes"]}
        if tomes <= vus:
            p["statut"], p["obsolete"], p["doublon"] = "ignore", True, True
            n += 1
        vus |= tomes
    return n


def plage(tomes) -> str:
    """[1, 2, 3, 5] → « T1–T3, T5 »."""
    t, out = sorted({int(x) for x in tomes}), []
    i = 0
    while i < len(t):
        j = i
        while j + 1 < len(t) and t[j + 1] == t[j] + 1:
            j += 1
        out.append(f"T{t[i]}" if i == j else f"T{t[i]}–T{t[j]}")
        i = j + 1
    return ", ".join(out)


def purger(propositions, info) -> int:
    """Passe en « ignoré » les propositions en attente devenues inutiles : tous leurs tomes sont arrivés entre-temps (nouveau),
    sont maintenant au moins aussi bien notés (meilleur) ou sont déjà de la bonne équipe (équipe). Renvoie leur nombre."""
    import provenance
    possedes, scores, par_tome = info.get("tomes") or set(), info.get("scores_tomes") or {}, info.get("equipe_tomes") or {}
    n = 0
    for p in propositions:
        t = [int(x) for x in p.get("tomes") or []]
        if p.get("statut") != "attente" or not t:
            continue
        if p["type"] == "nouveau":
            inutile = all(x in possedes for x in t)
        elif p["type"] == "meilleur":
            inutile = bool(info.get("profil")) and all(x in scores and scores[x] >= p.get("score", 0) for x in t)
        else:
            inutile = all(provenance.meme_equipe(par_tome.get(x) or "", info.get("equipe") or "") for x in t)
        if inutile:
            p["statut"], p["obsolete"] = "ignore", True
            n += 1
    return n


def _sans_point(titre):
    """Telegram transforme « Oda.FR » en lien (domaine) : les points des noms de torrents sont remplacés par des espaces."""
    return titre.replace(".", " ")


AUTRES_SERIES = lambda nom: []            # réglé par app.py : les noms des autres séries de la collection


def _d_une_autre_serie(titre_torrent: str, noms, autres) -> bool:
    """Le torrent porte exactement le nom d'une AUTRE série de la collection (et pas celui de celle-ci) : il n'est pas pour elle."""
    import lecture_pages
    nom_torrent = set(correspondance.jetons(lecture_pages.nom_dans_titre(titre_torrent)))
    return bool(nom_torrent) and nom_torrent in autres and not any(set(correspondance.jetons(n)) == nom_torrent for n in noms)


def _quota_auto(d, n=0) -> int:
    """Torrents que le mode 🤖 peut encore lancer aujourd'hui ; avec n > 0, les compte comme lancés (d est ensuite écrit par l'appelant)."""
    jour = datetime.now().strftime("%Y-%m-%d")
    q = d.get("auto_jour") if isinstance(d.get("auto_jour"), dict) and d["auto_jour"].get("date") == jour else {"date": jour, "n": 0}
    q["n"] += n
    d["auto_jour"] = q
    return max(0, AUTO_MAX_JOUR - q["n"])


def verifier(nom, chercher, infos_serie, lancer=None, envoyer=None, apres=None):
    """Cherche dans Prowlarr pour une série suivie et met ses propositions à jour : un seul torrent par tome, le meilleur.
    Une proposition en attente que le nouveau choix rend inutile (un meilleur torrent pour tous ses tomes) passe en « ignoré ».
    lancer(lien, titre, nom, remplacer, page) : envoie un torrent à qBittorrent. Sert (1) au mode 🤖 Auto de la série : les tomes
    manquants partent tout seuls (jamais de remplacement, AUTO_MAX_JOUR par jour) ; (2) à la MÊME ÉQUIPE pour 1 à 3 tomes déjà là
    d'une autre équipe, téléchargée et mise à la place toute seule (ancien à la corbeille, lu gardé), avec un message.
    apres(nom, nouvelles) : appelé une fois les propositions gardées (lecture de leurs pages sur les trackers).
    Renvoie les nouvelles propositions ; celles lancées tout seules ont le statut « telecharge » et `auto`."""
    d = lire()
    x = d["series"].get(nom)
    if not x:
        return []
    resultats, vus = [], set()
    autres = [set(correspondance.jetons(a)) for a in AUTRES_SERIES(nom)]
    titres = [t for t in x.get("titres", [nom]) if t == nom or set(correspondance.jetons(t)) not in autres]     # « Air Gear » n'est pas « Air Gear Unlimited »
    for titre in titres[:2]:
        for r in chercher(titre):
            if r["titre"] not in vus:
                vus.add(r["titre"])
                resultats.append(r)
    resultats = [r for r in resultats if not _d_une_autre_serie(r["titre"], titres, autres)]
    info = infos_serie(nom)
    info["qualite"] = x.get("qualite", "Digital")
    anciennes = x.get("propositions", [])
    # les propositions en attente sont rejugées (gardées si elles restent le meilleur choix) ; ignorées ou téléchargées : plus jamais
    choix = propositions_pour(nom, info, resultats, [p["titre"] for p in anciennes if p.get("statut") != "attente"])
    attente = {p["titre"]: p for p in anciennes if p.get("statut") == "attente"}
    nouvelles = [c for c in choix if c["titre"] not in attente]
    gardees = {c["titre"]: c for c in choix if c["titre"] in attente}
    if lancer and x.get("equipe_auto", True):
        for p in nouvelles:
            if p["type"] == "equipe" and p.get("lien") and 1 <= len(p["tomes"]) <= 3 and not info.get("en_cours"):
                try:
                    lancer(p["lien"], p["titre"], nom, True, p.get("page", ""))
                    p["statut"] = "telecharge"
                    info["en_cours"] = True
                    if envoyer:
                        avant = ", ".join(sorted({(info.get("equipe_tomes") or {}).get(t, "?") for t in p["tomes"]}))
                        envoyer(f"🔁 MouFlanga : {nom} T{', T'.join(str(t) for t in p['tomes'])} : {avant} → {info.get('equipe')} "
                                f"(téléchargement lancé, l'ancien ira à la corbeille)")
                except Exception as e:
                    logger.warning("Remplacement automatique (même équipe) de %s : %s", nom, e)
    lances = set()
    if lancer and x.get("auto"):
        # 🤖 tomes manquants : partent tout seuls (nouvelles propositions et anciennes encore en attente qui restent le meilleur choix)
        with _verrou:
            reste = _quota_auto(lire())
        for c in choix:
            if reste <= 0:
                logger.info("🤖 %s : plafond de %d torrents automatiques atteint pour aujourd'hui", nom, AUTO_MAX_JOUR)
                break
            if c["type"] != "nouveau" or not c.get("lien") or not c.get("sources") or c.get("statut") != "attente":
                continue
            try:
                lancer(c["lien"], c["titre"], nom, False, c.get("page", ""))
            except Exception as e:
                logger.warning("🤖 Téléchargement automatique de %s (%s) : %s", nom, c["titre"], e)
                break                                    # qBittorrent injoignable : on réessaiera à la prochaine vérification
            c["statut"], c["auto"] = "telecharge", True
            lances.add(c["titre"])
            reste -= 1
        if lances:
            with _verrou:
                dq = lire()
                _quota_auto(dq, len(lances))
                ecrire(dq)
    for c in choix:
        c.pop("lien", None)           # le lien de Prowlarr contient sa clé API : jamais gardé (la page Télécharger en redemande un frais)
    with _verrou:
        d = lire()
        if nom in d["series"]:
            props = d["series"][nom].setdefault("propositions", [])
            choisis = {t for c in choix for t in c["tomes"]}
            for p in props:
                if p.get("statut") != "attente":
                    continue
                if _d_une_autre_serie(p["titre"], titres, autres):          # gardée avant, mais en fait d'une autre série
                    p["statut"] = "ignore"
                elif p["titre"] in gardees:                                  # toujours le meilleur choix : mise à jour
                    c = gardees[p["titre"]]
                    p.update(tomes=c["tomes"], score=c["score"], sources=c["sources"], type=c["type"])
                    if c["titre"] in lances:
                        p["statut"], p["auto"] = "telecharge", True
                elif p.get("tomes") and {int(t) for t in p["tomes"]} <= choisis:
                    p["statut"], p["obsolete"], p["remplacee"] = "ignore", True, True     # un meilleur torrent apporte tous ses tomes
            purger(props, info)
            dedoublonner(props)
            props.extend(nouvelles)
            # on garde toutes les propositions en attente, et les 50 dernières déjà traitées (historique)
            traitees = [p for p in props if p.get("statut") != "attente"]
            d["series"][nom]["propositions"] = [p for p in props if p.get("statut") == "attente" or p in traitees[-50:]]
            d["series"][nom]["derniere_verif"] = datetime.now().strftime("%Y-%m-%d %H:%M")
            ecrire(d)
    if apres and nouvelles:
        try:
            apres(nom, nouvelles)
        except Exception as e:
            logger.warning("Lecture des pages de %s : %s", nom, e)
    return nouvelles + [dict(gardees[t], statut="telecharge", auto=True) for t in lances if t in gardees]


def message(nom, nouvelles, lien="") -> str:
    """Message Telegram d'une vérification : ce qui est parti tout seul (📥), puis les propositions à décider. « » s'il n'y a rien."""
    if not nouvelles:
        return ""
    sortes = {"nouveau": "manque", "equipe": "même équipe", "meilleur": "meilleure qualité"}
    partis = [p for p in nouvelles if p.get("auto")]
    reste = [p for p in nouvelles if not p.get("auto")]
    lignes = []
    if partis:
        tomes = sorted({int(t) for p in partis for t in p.get("tomes") or []})
        lignes.append(f"📥 MouFlanga : {nom} — {plage(tomes) or str(len(partis)) + ' torrent(s)'} téléchargé{'s' if len(tomes) > 1 else ''} tout seul (🤖)")
        lignes += [f"• « {_sans_point(p['titre'][:90])} »" + (f" ({p['score']} pts)" if p.get("score") else "") for p in partis[:6]]
        if len(partis) > 6:
            lignes.append(f"… et {len(partis) - 6} autre(s)")
    if reste:
        lignes.append(f"{'🆕' if reste[0]['type'] == 'nouveau' else '⬆️'} MouFlanga : {nom} — {len(reste)} proposition(s)")
        lignes += [f"• « {_sans_point(p['titre'][:90])} » — {sortes.get(p['type'], '')} {plage(p.get('tomes') or [])}".rstrip() for p in reste[:8]]
        if len(reste) > 8:
            autres_tomes = sorted({int(t) for p in reste[8:] for t in p.get("tomes") or []})
            lignes.append(f"… et {len(reste) - 8} autre(s) {plage(autres_tomes)}".rstrip())
    if lien:
        lignes.append(f"👉 Ouvrir dans MouFlanga : {lien}")
    return "\n".join(lignes)


def verifier_et_prevenir(nom, chercher, infos_serie, envoyer, adresse, lancer=None, apres=None):
    """Une vérification complète d'une série (surveillance du jour, flux des nouveautés, torrent raté) avec son message Telegram."""
    nouv = verifier(nom, chercher, infos_serie, lancer, envoyer, apres)
    if nouv:
        lien = adresse().rstrip("/") + "/#" + __import__("urllib.parse").parse.quote(nom) if adresse() else ""
        envoyer(message(nom, nouv, lien))
    return nouv


def nettoyer(infos_serie) -> int:
    """Une fois au démarrage : les propositions en attente devenues inutiles (tomes arrivés entre-temps, même pour une série qui n'est
    plus surveillée) ou en doublon (gardées avant le « un seul choix par tome ») passent en « ignoré ». Renvoie leur nombre."""
    n = 0
    for nom, x in list(lire()["series"].items()):
        if not any(p.get("statut") == "attente" for p in x.get("propositions", [])):
            continue
        try:
            info = infos_serie(nom)                      # lu hors du verrou (ça lit la bibliothèque)
        except Exception as e:
            logger.warning("Nettoyage des propositions de %s : %s", nom, e)
            continue
        with _verrou:
            d = lire()
            props = (d["series"].get(nom) or {}).get("propositions", [])
            k = purger(props, info) + dedoublonner(props)
            if k:
                ecrire(d)
                n += k
    if n:
        logger.info("Propositions de torrents : %d en doublon ou périmées passées en « ignoré »", n)
    return n


def proposition(nom, pid):
    """La proposition `pid` de la série suivie `nom` (copie), ou None."""
    x = lire()["series"].get(nom) or {}
    return next((dict(p) for p in x.get("propositions", []) if p.get("id") == pid), None)


def noter_lecture(nom, pid, lu):
    """Garde sur la proposition ce que la lecture de sa page a donné (`lu`) ou pourquoi elle n'a pas pu être lue. Rien d'autre n'est touché."""
    with _verrou:
        d = lire()
        for p in (d["series"].get(nom) or {}).get("propositions", []):
            if p.get("id") == pid:
                p["lu"] = lu
                ecrire(d)
                return True
    return False


CHAMPS_TRACKER = ("synopsis", "auteur", "editeur", "genre")       # pas la date : celle d'une page est la parution d'un tome, pas de la série


def noter_tracker(nom, infos, page, tracker):
    """Complète la fiche d'une série suivie avec ce que dit la page d'un torrent : seulement ce qui manque, rien n'est jamais remplacé.
    Renvoie les champs ajoutés."""
    with _verrou:
        d = lire()
        x = d["series"].get(nom)
        if x is None:
            return []
        t = x.setdefault("tracker", {})
        ajoutes = [c for c in CHAMPS_TRACKER if infos.get(c) and not t.get(c)]
        for c in ajoutes:
            t[c] = infos[c]
        if "synopsis" in ajoutes:
            t["synopsis_de"] = {"tracker": tracker, "page": page}
        if ajoutes:
            ecrire(d)
        return ajoutes


def nettoyer_liens():
    """Retire des propositions déjà gardées le lien de Prowlarr (il contient sa clé API et ne sert qu'à la création). Renvoie le nombre retiré."""
    n = 0
    with _verrou:
        d = lire()
        for x in d["series"].values():
            for p in x.get("propositions", []):
                if p.pop("lien", None):
                    n += 1
        if n:
            ecrire(d)
    return n


def sans_liens(x):
    """Copie d'une entrée de série suivie sans aucun lien de téléchargement, pour ce qu'on envoie au navigateur."""
    if not isinstance(x, dict):
        return x
    return {**x, "propositions": [{k: v for k, v in p.items() if k != "lien"} for p in x.get("propositions", [])]}


def en_attente():
    return [(n, p) for n, x in lire()["series"].items() for p in x.get("propositions", []) if p["statut"] == "attente"]


def boucle(chercher, infos_serie, envoyer, adresse, actif, lancer=None, apres=None):
    """Chaque jour (vers 7 h) : vérifie les séries surveillées ; un message Telegram par série qui a du nouveau."""
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
                    verifier_et_prevenir(nom, chercher, infos_serie, envoyer, adresse, lancer, apres)
                except Exception as e:
                    logger.warning("Surveillance de %s impossible : %s", nom, e)
                    continue
                time.sleep(20)                    # sobre avec Prowlarr et les indexeurs
        except Exception as e:
            logger.warning("Surveillance des séries : %s", e)


def _cle(texte: str) -> str:
    import unicodedata
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]", "", t)


def series_du_flux(resultats, series, deja_pris=()) -> dict:
    """{série surveillée: [noms de torrents du flux qui la concernent]}. Un nom de la série (au moins 4 lettres) doit se trouver dans
    celui du torrent ; les torrents déjà proposés ou déjà pris ne comptent pas. Large exprès : la vraie recherche de la série trie ensuite."""
    out = {}
    for nom, x in series.items():
        if not x.get("surveiller"):
            continue
        cles = {_cle(t) for t in [nom] + list(x.get("titres") or []) if len(_cle(t)) >= 4}
        connus = {p.get("titre") for p in x.get("propositions", [])} | set(deja_pris)
        for r in resultats:
            titre = r.get("titre") or ""
            if titre not in connus and any(c in _cle(titre) for c in cles):
                out.setdefault(nom, []).append(titre)
    return out


def boucle_flux(lire_flux, verifier_serie, actif, deja_pris=lambda: set()):
    """📡 Toutes les 15 minutes : le flux des nouveautés de Prowlarr (une seule demande pour tous les trackers, comme le RSS de Sonarr).
    Une série surveillée qui y apparaît avec un torrent jamais vu est vérifiée tout de suite (recherche complète, 🤖 si elle est en Auto),
    au plus une fois par heure. Un torrent n'est compté comme vu qu'une fois sa série vérifiée."""
    vus = set()
    while True:
        time.sleep(FLUX_INTERVALLE)
        try:
            if not actif():
                continue
            resultats = [r for r in lire_flux() if r.get("titre") not in vus]
            d = lire()
            concernes = series_du_flux(resultats, d["series"], deja_pris())
            maintenant = datetime.now()
            for nom, titres in concernes.items():
                derniere = d["series"][nom].get("derniere_verif") or ""
                try:
                    if (maintenant - datetime.strptime(derniere, "%Y-%m-%d %H:%M")).total_seconds() < FLUX_REPOS:
                        continue                      # vérifiée il y a moins d'une heure : ses torrents seront revus au prochain passage
                except ValueError:
                    pass
                logger.info("📡 Flux des nouveautés : %s (%s)", nom, titres[0][:80])
                try:
                    verifier_serie(nom)
                except Exception as e:
                    logger.warning("📡 Vérification de %s impossible : %s", nom, e)
                    continue
                vus.update(titres)
                time.sleep(20)
            en_attente = {t for ts in concernes.values() for t in ts} - vus
            vus.update(r["titre"] for r in resultats if r.get("titre") not in en_attente)
            if len(vus) > 20000:
                vus = set(list(vus)[-10000:])
        except Exception as e:
            logger.warning("📡 Flux des nouveautés : %s", e)
