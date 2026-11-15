"""
Pilote : ce que l'appli fait toute seule sur un tome qui vient d'arriver (chapitres, uniformisation…), un tome à la fois,
en laissant toujours la place aux vrais travaux.

Ce module ne connaît rien de l'appli : elle lui donne cinq fonctions (`configurer`) et il tient
  - la liste des tomes déjà connus (data/pilote.json) : un tome qui apparaît est mis en file, une seule fois ;
  - la file d'attente, gardée sur le disque (un redémarrage ne fait rien perdre) ;
  - le journal de ce qui a été fait tout seul, pour le montrer.

Règles :
  - au tout premier lancement, tout ce qui est déjà là est noté « connu » et rien n'est traité (pas de raz-de-marée) ;
  - un tome nouveau n'est pris que si son fichier est identique sur deux contrôles de suite (la copie est finie) ;
  - un tome connu dont le fichier change n'est PAS repris (l'appli réécrit ses tomes : ça tournerait en rond) ;
    l'appli appelle `signaler` quand elle veut qu'un tome connu soit refait (tome remplacé, bouton) ;
  - une série renommée ou un tome déplacé (même fichier, autre nom) reste connu ;
  - une demande faite à la main passe devant et n'attend ni la nuit ni le réglage « automatisations » ;
  - rien n'est lancé pendant qu'un autre travail tourne, ni sur une série occupée.
"""
import datetime
import json
import logging
import os
import threading
import time
from pathlib import Path

import plage

logger = logging.getLogger("mouflanga")

VERSION = 1
JOURNAL_MAX = 200                # lignes gardées dans le journal
ESSAIS_MAX = 3                   # un tome reporté trois fois est abandonné (et c'est écrit dans le journal)
REPORT = 600                     # secondes avant de réessayer un tome reporté

_VERROU = threading.RLock()
_CFG = {}
_MEM = {"d": None}               # contenu de data/pilote.json, gardé en mémoire (écrit à chaque changement)
_ETAT = {"en_cours": False, "serie": "", "tome": "", "detail": "", "attente": "", "debut": 0.0}
_VUS = {}                        # (série, tome) → empreinte vue au contrôle précédent (tome nouveau pas encore en file)
_FIL = {"lance": False}
_REVEIL = threading.Event()      # un signalement réveille le fil sans attendre la minute


def configurer(fichier, series, tomes, traiter, occupe, reglages=None):
    """series() → noms des séries ({} ou [] si la bibliothèque n'est pas montée) ;
    tomes(nom) → {clé du tome: empreinte du fichier} ;
    traiter(nom, tome, quoi, avance, element) → {"fait": [textes], "attend": [textes]}, {"reporter": "raison"} ou None ;
    occupe(nom) → raison en clair, ou "" si libre ; occupe("") = l'appli entière ;
    reglages() → {"actif": bool, "quand": "arrivee" | "nuit"}."""
    with _VERROU:
        _CFG.clear()
        _CFG.update(fichier=Path(fichier), series=series, tomes=tomes, traiter=traiter, occupe=occupe,
                    reglages=reglages or (lambda: {}))
        _MEM["d"] = None
        _VUS.clear()
        _ETAT.update(en_cours=False, serie="", tome="", detail="", attente="", debut=0.0)


def _vide() -> dict:
    return {"v": VERSION, "n": 0, "amorce": False, "connus": {}, "file": [], "journal": []}


def _donnees() -> dict:
    """Le contenu du fichier (à appeler sous le verrou). Un fichier absent ou abîmé = premier lancement."""
    if _MEM["d"] is None:
        d = _vide()
        try:
            lu = json.loads(_CFG["fichier"].read_text(encoding="utf-8"))
        except (OSError, ValueError, KeyError):
            lu = None
        if isinstance(lu, dict):
            for k, defaut in d.items():
                if isinstance(lu.get(k), type(defaut)):
                    d[k] = lu[k]
            d["file"] = [e for e in d["file"] if isinstance(e, dict) and e.get("serie") and e.get("tome") is not None]
            for nom, t in list(d["connus"].items()):          # ancien format éventuel (liste) : toléré
                if not isinstance(t, dict):
                    d["connus"][nom] = {str(c): "" for c in (t or [])}
        _MEM["d"] = d
    return _MEM["d"]


def _sauver():
    f = _CFG["fichier"]
    try:
        f.parent.mkdir(parents=True, exist_ok=True)
        tmp = f.with_name(f.name + ".tmp")
        tmp.write_text(json.dumps(_MEM["d"], ensure_ascii=False, indent=1), encoding="utf-8")
        os.replace(tmp, f)
    except OSError as e:
        logger.warning("Pilote : file d'attente non enregistrée (%s)", e)


def _cle(tome) -> str:
    """« 3 », « 3.5 » : la même écriture partout pour un tome."""
    try:
        f = float(tome)
        return str(int(f)) if f.is_integer() else str(f)
    except (TypeError, ValueError):
        return str(tome)


def _maintenant_texte() -> str:
    return datetime.datetime.now(plage.FUSEAU).strftime("%Y-%m-%d %H:%M")


def _noter(d, serie, tome, fait=(), attend=(), erreur=""):
    d["journal"].append({"date": _maintenant_texte(), "serie": serie, "tome": tome, "fait": list(fait or []),
                         "attend": list(attend or []), "erreur": erreur or ""})
    del d["journal"][:-JOURNAL_MAX]


# ───────────────────────────── Mettre en file ─────────────────────────────

def signaler(serie, tomes, quoi="tout", manuel=False, nuit=False, remplaces=()) -> int:
    """Met des tomes en file (même s'ils sont déjà connus). `quoi` : « tout », « chapitres » ou « uniformiser ».
    `manuel` : demandé par la personne (passe devant, n'attend rien). `nuit` : seulement entre minuit et 6 h.
    `remplaces` : tomes dont le fichier vient d'être remplacé par un autre. Renvoie le nombre de tomes ajoutés à la file."""
    if not _CFG or not serie:
        return 0
    remplaces = {_cle(t) for t in (remplaces or ())}
    ajoutes = 0
    with _VERROU:
        d = _donnees()
        en_file = {(e["serie"], e["tome"]): e for e in d["file"]}
        for t in tomes or ():
            c = _cle(t)
            d["n"] += 1
            e = en_file.get((serie, c))
            if e is None:
                e = {"id": d["n"], "serie": serie, "tome": c, "quoi": quoi, "manuel": bool(manuel), "nuit": bool(nuit),
                     "remplace": c in remplaces, "essais": 0, "pas_avant": 0}
                d["file"].append(e)
                en_file[(serie, c)] = e
                ajoutes += 1
            else:                                              # déjà en file : les deux demandes n'en font qu'une
                e["id"] = d["n"]                               # (nouvel identifiant : s'il est en cours, il sera refait)
                if e.get("quoi") != quoi:
                    e["quoi"] = "tout"
                e["manuel"] = bool(e.get("manuel") or manuel)
                e["nuit"] = bool(e.get("nuit") and nuit)
                e["remplace"] = bool(e.get("remplace") or c in remplaces)
                e["essais"], e["pas_avant"] = 0, 0
            d["connus"].setdefault(serie, {}).setdefault(c, "")
        _sauver()
    _REVEIL.set()
    return ajoutes


def controler() -> int:
    """Regarde la bibliothèque : les tomes nouveaux (fichier stable depuis le contrôle précédent) sont mis en file.
    Renvoie le nombre de tomes mis en file."""
    if not _CFG:
        return 0
    try:
        noms = list(_CFG["series"]() or ())
    except Exception as e:
        logger.warning("Pilote : bibliothèque illisible (%s)", e)
        return 0
    if not noms:                                               # bibliothèque pas montée : on ne conclut rien
        return 0
    actuel = {}
    for nom in noms:
        try:
            actuel[nom] = {_cle(c): str(e) for c, e in (_CFG["tomes"](nom) or {}).items()}
        except Exception as e:
            logger.warning("Pilote : tomes de « %s » illisibles (%s)", nom, e)
    a_signaler = []
    with _VERROU:
        d = _donnees()
        if not d["amorce"]:                                    # premier lancement : tout est « connu », rien n'est traité
            for nom, tomes in actuel.items():
                if tomes:
                    d["connus"].setdefault(nom, {}).update(tomes)
            d["amorce"] = True
            _VUS.clear()
            _sauver()
            return 0
        empreintes = {e for t in d["connus"].values() for e in t.values() if e}
        vus, change = {}, False
        for nom, tomes in actuel.items():
            connus = d["connus"].get(nom) or {}
            nouveaux = []
            for c, e in tomes.items():
                if c in connus:
                    if connus[c] != e:                         # réécrit par l'appli : on retient juste sa nouvelle empreinte
                        connus[c] = e
                        change = True
                elif e in empreintes:                          # même fichier sous un autre nom (série renommée, tome déplacé)
                    connus = d["connus"].setdefault(nom, {})
                    connus[c] = e
                    change = True
                elif _VUS.get((nom, c)) == e:                  # vu deux fois de suite, identique : la copie est finie
                    nouveaux.append(c)
                else:
                    vus[(nom, c)] = e
            if nouveaux:
                connus = d["connus"].setdefault(nom, {})
                for c in nouveaux:
                    connus[c] = tomes[c]
                a_signaler.append((nom, nouveaux))
                change = True
        _VUS.clear()
        _VUS.update(vus)
        if change:
            _sauver()
    return sum(signaler(nom, nouveaux) for nom, nouveaux in a_signaler)


# ───────────────────────────── Traiter ─────────────────────────────

def un_pas(maintenant=None) -> bool:
    """Traite UN tome de la file (les demandes faites à la main d'abord). Renvoie True s'il vaut la peine de rappeler
    tout de suite (un tome vient d'être traité), False s'il n'y a rien à faire pour l'instant."""
    if not _CFG:
        return False
    maintenant = time.time() if maintenant is None else maintenant
    try:
        reg = dict(_CFG["reglages"]() or {})
    except Exception:
        reg = {}
    with _VERROU:
        file = sorted((dict(e) for e in _donnees()["file"]), key=lambda e: (not e.get("manuel"), e.get("id", 0)))
    if not file:
        _ETAT.update(attente="")
        return False
    occupation = {}

    def occupe(nom):
        if nom not in occupation:
            try:
                occupation[nom] = str(_CFG["occupe"](nom) or "")
            except Exception as e:
                occupation[nom] = f"état de l'appli illisible ({e})"
        return occupation[nom]

    de_nuit = plage.dans_la_plage()
    choisi, attente = None, ""
    for e in file:
        if not e.get("manuel"):
            if not reg.get("actif", True):
                attente = attente or "automatisations coupées dans les réglages"
                continue
            if (e.get("nuit") or reg.get("quand") == "nuit") and not de_nuit:
                attente = attente or "en pause jusqu'à minuit"
                continue
        if (e.get("pas_avant") or 0) > maintenant:
            attente = attente or "nouvel essai dans quelques minutes"
            continue
        if occupe(""):                                         # un vrai travail tourne : personne ne passe
            attente = "en attente : " + occupe("")
            break
        if occupe(e["serie"]):
            attente = attente or f"en attente : « {e['serie']} » est occupée"
            continue
        choisi = e
        break
    if choisi is None:
        _ETAT.update(en_cours=False, attente=attente)
        return False

    serie, tome = choisi["serie"], choisi["tome"]
    _ETAT.update(en_cours=True, serie=serie, tome=tome, detail="", attente="", debut=time.time())

    def avance(texte):
        _ETAT["detail"] = str(texte or "")

    r, erreur = {}, ""
    try:
        r = _CFG["traiter"](serie, tome, choisi.get("quoi") or "tout", avance, dict(choisi)) or {}
    except Exception as e:                                     # un tome qui plante ne bloque pas les autres
        logger.warning("Pilote : « %s » tome %s : %s", serie, tome, e, exc_info=True)
        erreur = str(e) or type(e).__name__
    with _VERROU:
        d = _donnees()
        actuel = next((e for e in d["file"] if e["serie"] == serie and e["tome"] == tome), None)
        meme = actuel is not None and actuel.get("id") == choisi.get("id")
        if r.get("reporter") and not erreur:
            if meme:
                actuel["essais"] = int(actuel.get("essais") or 0) + 1
                if actuel["essais"] >= ESSAIS_MAX:
                    d["file"].remove(actuel)
                    _noter(d, serie, tome, erreur=f"abandonné après {ESSAIS_MAX} essais : {r['reporter']}")
                else:
                    actuel["pas_avant"] = maintenant + REPORT
        else:
            if meme:                                           # sinon : redemandé entre-temps, il reste en file
                d["file"].remove(actuel)
            if erreur or r.get("fait") or r.get("attend"):
                _noter(d, serie, tome, r.get("fait"), r.get("attend"), erreur)
        _ETAT.update(en_cours=False, serie="", tome="", detail="", debut=0.0)
        _sauver()
    return True


def surveiller(intervalle=300, delai_depart=120):
    """Lance le fil du pilote (une seule fois) : contrôle de la bibliothèque toutes les `intervalle` secondes, file vidée
    au fur et à mesure."""
    with _VERROU:
        if _FIL["lance"] or not _CFG:
            return
        _FIL["lance"] = True

    def boucle():
        try:
            os.nice(10)                                        # priorité basse : l'appli reste fluide
        except (OSError, AttributeError):
            pass
        time.sleep(delai_depart)
        dernier = 0.0
        while True:
            try:
                if time.time() - dernier >= intervalle:
                    dernier = time.time()
                    controler()
                while un_pas():
                    pass
            except Exception as e:
                logger.warning("Pilote : %s", e, exc_info=True)
            _REVEIL.wait(60)
            _REVEIL.clear()

    threading.Thread(target=boucle, daemon=True, name="pilote").start()


# ───────────────────────────── Lire l'état ─────────────────────────────

def etat() -> dict:
    with _VERROU:
        return dict(_ETAT, file=len(_donnees()["file"]) if _CFG else 0)


def en_file(serie=None) -> list:
    """Les tomes en attente (d'une série, ou tous)."""
    if not _CFG:
        return []
    with _VERROU:
        return [dict(e) for e in _donnees()["file"] if serie is None or e["serie"] == serie]


def journal(n=50, serie=None) -> list:
    """Les dernières choses faites toutes seules, les plus récentes d'abord."""
    if not _CFG:
        return []
    with _VERROU:
        lignes = [dict(x) for x in _donnees()["journal"] if serie is None or x.get("serie") == serie]
    return lignes[::-1][:n]


def retirer(serie=None, quoi=None) -> int:
    """Retire de la file les tomes d'une série (ou tout) : bouton « Arrêter ». Le tome en cours va au bout.
    `quoi` : ne retire que ce genre de demande. Renvoie le nombre de tomes retirés."""
    if not _CFG:
        return 0
    with _VERROU:
        d = _donnees()
        garder = [e for e in d["file"] if (serie is not None and e["serie"] != serie) or (quoi and e.get("quoi") != quoi)]
        n = len(d["file"]) - len(garder)
        if n:
            d["file"] = garder
            _sauver()
    return n
