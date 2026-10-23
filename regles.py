"""
Règles de recherche des torrents, comme Sonarr et Radarr :
  - des formats personnalisés : des conditions sur le titre, l'équipe, l'indexeur, la taille… (chacune peut être
    obligatoire ou inversée) ; un torrent « a » le format quand les conditions sont remplies ;
  - des profils : ce qui est refusé (mots, taille, sources, score trop bas) et combien de points vaut chaque format.
Enregistrés dans data/regles.json (jamais sur GitHub).
"""
import json
import re
import uuid
from pathlib import Path

FICHIER = Path(__file__).resolve().parent / "data" / "regles.json"
SERIES_CONNUES = lambda: []      # branché par app.py : noms des séries de la bibliothèque et des séries suivies

TYPES = {
    "titre": "Mot dans le titre",
    "regex": "Expression (regex) dans le titre",
    "equipe": "Équipe / groupe",
    "indexeur": "Indexeur (tracker)",
    "badge": "Étiquette (FR, Digital, Scan, Intégrale)",
    "taille_min": "Taille minimale (Go)",
    "taille_max": "Taille maximale (Go)",
}
_NUMERIQUES = ("taille_min", "taille_max")


def _liste(texte) -> list[str]:
    """« kaf, Tsundere-Raws » → ['kaf', 'Tsundere-Raws'] ; un terme par virgule ou par ligne."""
    if isinstance(texte, (list, tuple)):
        return [str(x).strip() for x in texte if str(x).strip()]
    return [x.strip() for x in re.split(r"[,\n]", texte or "") if x.strip()]


def _nombre(valeur, nom: str, entier=False):
    """Nombre saisi (virgule ou point) ; vide → None."""
    t = str(valeur if valeur is not None else "").strip().replace(",", ".")
    if not t:
        return None
    try:
        n = float(t)
    except ValueError:
        raise ValueError(f"{nom} doit être un nombre (ou vide).")
    return int(n) if entier else n


def _condition(c: dict) -> dict | None:
    """Une condition propre, ou None si elle est vide. Lève ValueError si elle est fausse (regex invalide…)."""
    type_ = (c.get("type") or "titre").strip()
    if type_ not in TYPES:
        raise ValueError(f"Type de condition inconnu : {type_}")
    valeur = c.get("valeur")
    if type_ in _NUMERIQUES:
        valeur = _nombre(valeur, TYPES[type_])
        if valeur is None:
            return None
    elif type_ == "regex":
        valeur = str(valeur or "").strip()
        if not valeur:
            return None
        try:
            re.compile(valeur, re.I)
        except re.error as e:
            raise ValueError(f"Expression invalide « {valeur} » : {e}")
    else:
        valeur = _liste(valeur)
        if not valeur:
            return None
    return {"type": type_, "valeur": valeur, "inverse": bool(c.get("inverse")), "obligatoire": bool(c.get("obligatoire"))}


def _conditions(liste) -> list[dict]:
    return [c for c in (_condition(x) for x in (liste or []) if isinstance(x, dict)) if c]


def _lire() -> dict:
    try:
        d = json.loads(FICHIER.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        d = {}
    formats = []
    for f in d.get("formats", []):
        f = dict(f)
        if not f.get("conditions") and f.get("termes"):          # ancien format : « un de ces mots dans le titre »
            f["conditions"] = [{"type": "titre", "valeur": list(f["termes"]), "inverse": False, "obligatoire": False}]
        f["conditions"] = f.get("conditions") or []
        f.setdefault("score", 0)
        formats.append(f)
    return {"profils": d.get("profils", []), "formats": formats}


def _ecrire(d: dict):
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    tmp = FICHIER.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FICHIER)


def profils() -> list[dict]:
    return _lire()["profils"]


def formats() -> list[dict]:
    return _lire()["formats"]


def enregistrer_profil(id_: str, nom: str, actif: bool, doit: str, ne_doit_pas: str, series, taille_max_go: str,
                       scores: dict | None = None, score_min="", score_arret="", sources_min="") -> str:
    """Crée ou modifie un profil ; renvoie son identifiant. Le nom est obligatoire.
    scores : {id du format: points} (un format absent vaut ses points par défaut) ; score_min : en dessous, le torrent est refusé ;
    score_arret : à partir de là, c'est « assez bon » (sert plus tard au surclassement) ; sources_min : moins de sources = refusé."""
    nom = (nom or "").strip()
    if not nom:
        raise ValueError("Donne un nom au profil.")
    taille = _nombre(taille_max_go, "La taille maximale (Go)")
    d = _lire()
    ancien = next((x for x in d["profils"] if x["id"] == id_), {}) if id_ else {}
    pts = {}
    for k, v in (scores if scores is not None else ancien.get("scores", {})).items():
        n = _nombre(v, "Un score", entier=True)
        if n is not None:
            pts[str(k)] = n
    p = {"id": id_ or uuid.uuid4().hex[:10], "nom": nom, "actif": bool(actif), "doit": _liste(doit),
         "ne_doit_pas": _liste(ne_doit_pas),
         "series": [str(x).strip() for x in series if str(x).strip()] if isinstance(series, (list, tuple)) else _liste(series),
         "taille_max_go": taille, "scores": pts,
         "score_min": _nombre(score_min, "Le score minimum", entier=True),
         "score_arret": _nombre(score_arret, "Le score d'arrêt", entier=True),
         "sources_min": _nombre(sources_min, "Le nombre de sources minimum", entier=True) or 0}
    d["profils"] = [x for x in d["profils"] if x["id"] != p["id"]] + [p]
    _ecrire(d)
    return p["id"]


def enregistrer_format(id_: str, nom: str, termes: str, score: str, conditions=None) -> str:
    """Crée ou modifie un format. `conditions` : liste de {type, valeur, inverse, obligatoire} ; sans elle, `termes`
    (ancienne forme) devient une condition « mot dans le titre »."""
    nom = (nom or "").strip()
    if not nom:
        raise ValueError("Donne un nom au format personnalisé.")
    pts = _nombre(score, "Le score", entier=True) or 0
    if conditions is None:
        conditions = [{"type": "titre", "valeur": termes}]
    conds = _conditions(conditions)
    d = _lire()
    f = {"id": id_ or uuid.uuid4().hex[:10], "nom": nom, "conditions": conds, "score": pts}
    d["formats"] = [x for x in d["formats"] if x["id"] != f["id"]] + [f]
    _ecrire(d)
    return f["id"]


def supprimer(quoi: str, id_: str):
    d = _lire()
    cle = "profils" if quoi == "profil" else "formats"
    d[cle] = [x for x in d[cle] if x["id"] != id_]
    if quoi != "profil":                       # les points de ce format disparaissent aussi des profils
        for p in d["profils"]:
            (p.get("scores") or {}).pop(id_, None)
    _ecrire(d)


# ---------------------------------------------------------------- évaluation

def _mot(terme: str, titre: str) -> bool:
    return terme.lower() in titre.lower()


def _condition_vraie(c: dict, r: dict) -> bool:
    type_, v = c["type"], c["valeur"]
    titre = r.get("titre") or ""
    if type_ == "titre":
        ok = any(_mot(t, titre) for t in v)
    elif type_ == "regex":
        ok = bool(re.search(v, titre, re.I))
    elif type_ == "equipe":
        import provenance
        eq = provenance.equipe_torrent(titre).lower()
        ok = bool(eq) and any(t.lower() in eq for t in v)
    elif type_ == "indexeur":
        ok = any(_mot(t, r.get("indexeur") or "") for t in v)
    elif type_ == "badge":
        ok = any(_mot(t, b) for t in v for b in r.get("badges") or [])
    elif type_ == "taille_min":
        ok = bool(r.get("taille")) and r["taille"] >= v * 1024 ** 3
    else:                                      # taille_max
        ok = bool(r.get("taille")) and r["taille"] <= v * 1024 ** 3
    return ok != c.get("inverse", False)


def format_correspond(f: dict, r: dict) -> bool:
    """Comme Sonarr : toutes les conditions obligatoires doivent être vraies, et, s'il y en a des facultatives, au moins une."""
    conds = f.get("conditions") or []
    if not conds:
        return False
    obligatoires = [c for c in conds if c.get("obligatoire")]
    facultatives = [c for c in conds if not c.get("obligatoire")]
    if not all(_condition_vraie(c, r) for c in obligatoires):
        return False
    return not facultatives or any(_condition_vraie(c, r) for c in facultatives)


def _cle(s: str) -> str:
    return re.sub(r"[^a-z0-9]", "", s.lower())


def _resolue(serie: str) -> str:
    """La série visée par une recherche : le plus long nom connu (bibliothèque, séries suivies, séries des profils) contenu dans le texte.
    « Gantz : Osaka T03 » → « Gantz : Osaka » et non « Gantz » ; « Air Gear intégrale » → « Air Gear » et non « Air Gear Unlimited »."""
    q = _cle(serie or "")
    connues = {_cle(n) for n in SERIES_CONNUES()} | {_cle(x) for p in profils() for x in p.get("series") or []}
    return max((k for k in connues if k and k in q), key=len, default=q)


def _concerne(profil: dict, serie: str, resolue: str | None = None) -> bool:
    """Un profil sans série s'applique à tout ; sinon seulement à la série visée, comparée par son nom entier (sans accents ni casse)."""
    if not profil.get("series"):
        return True
    r = resolue if resolue is not None else _resolue(serie)
    return any(_cle(x) == r for x in profil["series"] if _cle(x))


def profil_pour(serie: str = ""):
    """Le profil qui s'applique à cette série, comme dans Sonarr : un seul. Celui qui nomme la série passe avant
    le profil général (sans série) ; à égalité, le premier créé."""
    actifs = [p for p in profils() if p.get("actif")]
    r = _resolue(serie)
    precis = [p for p in actifs if p.get("series") and _concerne(p, serie, r)]
    general = [p for p in actifs if not p.get("series")]
    return (precis or general or [None])[0]


def _points(f: dict, profil) -> int:
    if profil and f["id"] in (profil.get("scores") or {}):
        return profil["scores"][f["id"]]
    return f.get("score", 0)


# Anglais : refusé à tout prix, avec ou sans profil. « En » seul (« One Piece En Couleurs ») n'est PAS de l'anglais : on n'exige que des marques explicites
# (ENG, ENGLISH, [EN] / (EN) entre crochets ou parenthèses, éventuellement avec un autre mot : « [CBR-CBZ ENG] », « [PDF EN] »).
_ANGLAIS = re.compile(r"\beng\b|\benglish\b|[\[(]\s*(?:[a-z0-9-]+[\s/-]+)?en\s*[\])]", re.I)


def est_anglais(titre: str) -> bool:
    return bool(_ANGLAIS.search((titre or "").replace("_", " ")))


def _refus(profil: dict, r: dict, score: int) -> str:
    """Pourquoi le profil refuse ce torrent (« » s'il l'accepte)."""
    titre = r.get("titre") or ""
    if profil.get("doit") and not any(_mot(t, titre) for t in profil["doit"]):
        return "aucun des mots obligatoires (" + ", ".join(profil["doit"]) + ")"
    for t in profil.get("ne_doit_pas") or []:
        if _mot(t, titre):
            return f"mot interdit : {t}"
    if profil.get("taille_max_go") and r.get("taille") and r["taille"] > profil["taille_max_go"] * 1024 ** 3:
        return "trop gros (%.1f Go, maximum %g Go)" % (r["taille"] / 1024 ** 3, profil["taille_max_go"])
    if profil.get("sources_min") and (r.get("sources") or 0) < profil["sources_min"]:
        return f"moins de {profil['sources_min']} source(s)"
    if profil.get("score_min") is not None and score < profil["score_min"]:
        return f"score trop bas ({score}, minimum {profil['score_min']})"
    return ""


def filtrer(resultats: list[dict], serie: str = "", avec_rejets: bool = False, profil="auto") -> list[dict]:
    """Ajoute à chaque torrent son score, ses formats reconnus et, s'il y a lieu, la raison du refus (`rejet`).
    Les refusés sont retirés, sauf avec `avec_rejets`. profil : "auto" = celui de la série, None = aucun, ou un profil donné."""
    if profil == "auto":
        profil = profil_pour(serie)
    fmts = formats()
    out = []
    for r in resultats:
        trouves = [f for f in fmts if format_correspond(f, r)]
        score = sum(_points(f, profil) for f in trouves)
        r["score"] = score
        r["formats"] = [f["nom"] for f in trouves]
        r["rejet"] = _refus(profil, r, score) if profil else ""
        if not r["rejet"] and est_anglais(r.get("titre")):
            r["rejet"] = "marqué en anglais (ENG / EN) : jamais pris"
        r["profil"] = profil["nom"] if profil else ""
        r["assez_bon"] = bool(profil and profil.get("score_arret") is not None and score >= profil["score_arret"])
        if r["rejet"] and not avec_rejets:
            continue
        out.append(r)
    return out


# ---------------------------------------------------------------- modèles de départ

MODELES_FORMATS = [
    ("Version française", 100, [{"type": "badge", "valeur": "FR"}]),
    ("Numérique (Digital)", 50, [{"type": "badge", "valeur": "Digital"}]),
    ("Intégrale", 30, [{"type": "badge", "valeur": "Intégrale"}]),
    ("Scan (qualité moindre)", -50, [{"type": "badge", "valeur": "Scan"}]),
    ("Archives CBZ", 10, [{"type": "regex", "valeur": r"\bcbz\b"}]),
    ("PDF", -20, [{"type": "regex", "valeur": r"\bpdf\b"}]),
    ("VOSTFR / anglais seul (à éviter)", -1000, [{"type": "regex", "valeur": r"\b(vostfr|eng(lish)?)\b"}]),
]


def ajouter_modeles() -> int:
    """Ajoute les formats de départ qui n'existent pas encore (par nom) et un profil « Manga VF numérique » désactivé.
    Renvoie le nombre d'éléments ajoutés. Ne touche à rien d'existant."""
    deja = {f["nom"] for f in formats()}
    n = 0
    ids = {}
    for nom, pts, conds in MODELES_FORMATS:
        if nom in deja:
            ids[nom] = next(f["id"] for f in formats() if f["nom"] == nom)
            continue
        ids[nom] = enregistrer_format("", nom, "", str(pts), conds)
        n += 1
    if not any(p["nom"] == "Manga VF numérique" for p in profils()):
        enregistrer_profil("", "Manga VF numérique", False, "", "", [], "", scores={}, score_min="0", score_arret="150", sources_min="1")
        n += 1
    return n


# ---------------------------------------------------------------- profils par équipe, tenus à jour tout seuls

def _mot_equipe(equipe: str) -> str:
    """« PRiNTER-PapriKa+ » → « PapriKa » ; « Tadatoshi FUJIMAKI » (un nom d'auteur), « INT » ou « Oku » (trop court) → « »."""
    e = (equipe or "").strip()
    if not e or " " in e:
        return ""
    t = re.split(r"-+", e)[-1].rstrip("+").strip()
    return t if re.fullmatch(r"[A-Za-z0-9]{4,24}", t) else ""


def synchroniser_equipes(equipes_par_serie: dict) -> dict:
    """Crée, met à jour et retire les profils « Manga · <Équipe> » (marqués `auto`) d'après l'équipe de chaque série de la bibliothèque.
    Une équipe n'a un profil que si elle est celle d'au moins DEUX séries (sinon c'est souvent un auteur). Le profil donne +1000 au
    format « Équipe X » (créé au besoin, 0 point par défaut) et exige 1 source. Ne touche jamais à un profil modifié ou créé à la main
    (sans `auto`), ni aux séries déjà citées dans un profil à la main. Renvoie {crees, mis_a_jour, supprimes}."""
    groupes = {}
    for serie, eq in equipes_par_serie.items():
        t = _mot_equipe(eq)
        if t:
            groupes.setdefault(t.lower(), [t, []])[1].append(serie)
    d = _lire()
    a_la_main = {_cle(x) for p in d["profils"] if not p.get("auto") for x in p.get("series") or []}
    voulus = {}
    for cle, (nom_equipe, series) in groupes.items():
        series = sorted({x for x in series if _cle(x) not in a_la_main}, key=str.lower)
        if len(series) >= 2:
            voulus["Manga · " + nom_equipe] = (nom_equipe, series)
    bilan = {"crees": [], "mis_a_jour": [], "supprimes": []}
    for nom, (nom_equipe, series) in sorted(voulus.items()):
        p = next((x for x in d["profils"] if x["nom"] == nom), None)
        if p and not p.get("auto"):
            continue                                     # un profil du même nom fait à la main : on ne s'en mêle pas
        fmt = next((f for f in d["formats"] if f["nom"] == "Équipe " + nom_equipe), None)
        if fmt is None:
            fmt = {"id": uuid.uuid4().hex[:10], "nom": "Équipe " + nom_equipe,
                   "conditions": [{"type": "titre", "valeur": [nom_equipe.lower()], "inverse": False, "obligatoire": False}], "score": 0}
            d["formats"].append(fmt)
        if p is None:
            d["profils"].append({"id": uuid.uuid4().hex[:10], "nom": nom, "actif": True, "auto": True, "doit": [], "ne_doit_pas": [], "series": series,
                                 "taille_max_go": None, "scores": {fmt["id"]: 1000}, "score_min": None, "score_arret": 1000, "sources_min": 1})
            bilan["crees"].append(nom)
        elif p.get("series") != series:
            p["series"] = series
            bilan["mis_a_jour"].append(nom)
    for p in list(d["profils"]):
        if p.get("auto") and p["nom"] not in voulus:
            d["profils"].remove(p)
            bilan["supprimes"].append(p["nom"])
    if any(bilan.values()):
        _ecrire(d)
    return bilan


def score_titre(titre: str, serie: str = "") -> int:
    """Points qu'un nom de torrent (celui d'où vient un tome de la bibliothèque) obtiendrait avec le profil de la série, refus ignorés :
    sert à savoir si un tome déjà là est dans la qualité voulue par le profil."""
    import torrents                                   # import tardif : torrents importe déjà regles
    r = {"titre": titre, "taille": 0, "sources": 99, "indexeur": "", "badges": torrents.badges(titre)}
    return filtrer([r], serie, avec_rejets=True)[0]["score"]
