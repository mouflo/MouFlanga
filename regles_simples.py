"""✨ Règles simples : les préférences de recherche de torrents dites en clair, sans profils, formats ni points à régler.

Rien de nouveau dans le moteur : ces choix sont traduits en un profil général ordinaire de regles.py (« ⭐ Mes préférences », marqué
`simple`, avec les choix gardés dans sa clé `preferences`) et, pour une série qui préfère une équipe, en un profil de série marqué
`simple_serie`. Les profils faits à la main (onglets avancés) ne sont jamais modifiés, seulement désactivés quand ils feraient double
emploi avec les préférences (un seul profil général sert, comme dans Sonarr) ; modifier « ⭐ Mes préférences » dans l'onglet avancé
en fait un profil à la main.
"""
import re
import uuid

import regles

NOM = "⭐ Mes préférences"
REFUS = -5000
DEFAUT = {"francais": "obligatoire",   # "obligatoire" : rien n'est pris sans indice de français ; "prefere" : le français passe devant
          "officiel": True,           # préférer l'édition numérique officielle au scan
          "integrale": True,          # préférer une intégrale aux tomes un par un
          "pdf": False,               # accepter les PDF
          "sans_source": False,       # accepter un torrent que personne ne partage
          "taille_max_go": None,
          "equipes_plus": [],         # équipes préférées : toujours en tête
          "equipes_moins": []}        # équipes refusées

# Les formats dont les préférences ont besoin (créés s'ils manquent, retrouvés par leur nom)
_FR = "Marqué français (FR, FRENCH, VF, MULTI)"
_EQ_FR = "Équipe française connue"
_VOCAB = "Vocabulaire français (Tome, Intégrale, Chapitre)"
_VO = "VO / sous-titré / raw (à éviter)"
_VOSTFR = "VOSTFR / anglais seul (à éviter)"
_DIGITAL = "Numérique (Digital)"
_INTEGRALE = "Intégrale"
_PDF = "PDF"
_FORMATS = [
    (_FR, [{"type": "badge", "valeur": "FR"}]),
    (_EQ_FR, [{"type": "titre", "valeur": "paprika, toner, printer, chromatique, ebdz, dogbanov, noface696, scantrads, ipman, corridor, notag"}]),
    (_VOCAB, [{"type": "regex", "valeur": r"\b(tomes?|int[ée]grale|chapitres?)\b"}]),
    (_VO, [{"type": "regex", "valeur": r"\b(vostfr|vo|jap|jpn|raws?)\b"}]),
    (_VOSTFR, [{"type": "regex", "valeur": r"\b(vostfr|eng(lish)?)\b"}]),
    (_DIGITAL, [{"type": "badge", "valeur": "Digital"}]),
    (_INTEGRALE, [{"type": "badge", "valeur": "Intégrale"}]),
    (_PDF, [{"type": "regex", "valeur": r"\bpdf\b"}]),
]
FRANCAIS = (_FR, _EQ_FR, _VOCAB)          # ce qui prouve qu'un torrent est en français
ORIGINALE = (_VO, _VOSTFR)                # version originale ou sous-titrée


def _equipes(v) -> list[str]:
    """« PapriKa, ebdz » → ["PapriKa", "ebdz"] (sans doublon, 2 à 30 signes chacune)."""
    morceaux = v if isinstance(v, (list, tuple)) else str(v or "").replace(";", ",").replace("\n", ",").split(",")
    out = []
    for m in morceaux:
        m = " ".join(str(m).split())
        if 2 <= len(m) <= 30 and regles._cle(m) and regles._cle(m) not in {regles._cle(x) for x in out}:
            out.append(m)
    return out


def valider(d) -> dict:
    """Des préférences complètes et propres d'après ce qu'on a lu ou reçu."""
    d = d if isinstance(d, dict) else {}
    p = dict(DEFAUT)
    p["francais"] = "prefere" if d.get("francais") == "prefere" else "obligatoire"
    for cle in ("officiel", "integrale", "pdf", "sans_source"):
        if cle in d:
            p[cle] = bool(d[cle]) and d[cle] not in ("0", "non")
    try:
        t = float(str(d.get("taille_max_go") or "").replace(",", "."))
        p["taille_max_go"] = t if 0 < t < 1000 else None
    except ValueError:
        if str(d.get("taille_max_go") or "").strip():
            raise ValueError("La taille maximale doit être un nombre de Go (ex. 5).")
        p["taille_max_go"] = None
    p["equipes_plus"] = _equipes(d.get("equipes_plus"))
    p["equipes_moins"] = [e for e in _equipes(d.get("equipes_moins")) if regles._cle(e) not in {regles._cle(x) for x in p["equipes_plus"]}]
    return p


def _format(d: dict, nom: str, conditions) -> dict:
    """Le format de ce nom (créé s'il manque, 0 point par défaut : il ne change rien aux profils faits à la main)."""
    f = next((x for x in d["formats"] if regles._cle(x["nom"]) == regles._cle(nom)), None)
    if f is None:
        f = {"id": uuid.uuid4().hex[:10], "nom": nom, "conditions": regles._conditions(conditions), "score": 0}
        d["formats"].append(f)
    return f


def _morceaux(equipe: str) -> list:
    return [m for m in re.split(r"[\s._-]+", equipe.strip()) if m]


def _format_equipe(d: dict, equipe: str) -> dict:
    """Une équipe en plusieurs mots s'écrit de dix façons dans un nom de torrent (« Neo Rip Club », « NEO.RIP-Club ») :
    on accepte un séparateur quelconque (ou aucun) entre ses mots."""
    mots = _morceaux(equipe)
    if len(mots) > 1:
        return _format(d, "Équipe " + equipe, [{"type": "regex", "valeur": "[ ._-]?".join(re.escape(m.lower()) for m in mots)}])
    return _format(d, "Équipe " + equipe, [{"type": "titre", "valeur": equipe.lower()}])


def _profil(d: dict, prefs: dict, base: dict, equipe: str = "") -> dict:
    """Remplit `base` (un profil) d'après les préférences. Chaque format reçoit des points écrits noir sur blanc : aucun point
    « par défaut » d'un format ne vient changer le résultat."""
    connus = {nom: _format(d, nom, conds) for nom, conds in _FORMATS}
    plus = [_format_equipe(d, e) for e in prefs["equipes_plus"] + ([equipe] if equipe else [])]
    scores = {f["id"]: 0 for f in d["formats"]}
    scores[connus[_FR]["id"]] = 100
    scores[connus[_EQ_FR]["id"]] = 60
    scores[connus[_VOCAB]["id"]] = 30
    scores[connus[_VO]["id"]] = -1000
    scores[connus[_VOSTFR]["id"]] = -1000
    scores[connus[_DIGITAL]["id"]] = 20 if prefs["officiel"] else 0
    scores[connus[_INTEGRALE]["id"]] = 20 if prefs["integrale"] else 0
    scores[connus[_PDF]["id"]] = -10
    for f in plus:
        scores[f["id"]] = 1000
    for e in prefs["equipes_moins"]:              # refusée : des points si bas qu'aucune autre qualité ne la rattrape
        scores[_format_equipe(d, e)["id"]] = REFUS
    base.update({"actif": True, "doit": [], "ne_doit_pas": [] if prefs["pdf"] else ["pdf"], "equipes_refusees": list(prefs["equipes_moins"]),
                 "taille_max_go": prefs["taille_max_go"], "scores": scores,
                 "score_min": 30 if prefs["francais"] == "obligatoire" else -500,
                 "score_arret": 1000 if equipe else 100, "sources_min": 0 if prefs["sans_source"] else 1})
    return base


def _simple(d: dict):
    return next((p for p in d["profils"] if p.get("simple")), None)


def etat() -> dict:
    """Ce que la page montre : les préférences (enregistrées ou proposées), les séries qui ont une équipe préférée, les règles
    faites à la main qui passent avant, les équipes connues."""
    d = regles._lire()
    p = _simple(d)
    general = next((x for x in d["profils"] if x.get("actif") and not x.get("series")), None)
    return {"enregistre": bool(p), "actif": bool(p and p.get("actif") and general is p),
            "prefs": valider(p.get("preferences")) if p else dict(DEFAUT),
            "general": general["nom"] if general and general is not p else "",
            "series": sorted(({"id": x["id"], "serie": (x.get("series") or [""])[0], "equipe": x.get("equipe", "")}
                              for x in d["profils"] if x.get("simple_serie")), key=lambda s: s["serie"].lower()),
            "a_la_main": [{"nom": x["nom"], "series": x["series"], "auto": bool(x.get("auto"))} for x in d["profils"]
                          if x.get("actif") and x.get("series") and not x.get("simple_serie")],
            "equipes": sorted({f["nom"][7:] for f in d["formats"] if f["nom"].startswith("Équipe ") and f["nom"] != _EQ_FR}, key=str.lower)}


def enregistrer(recu) -> dict:
    """Enregistre les préférences : elles deviennent LE profil général. Les autres profils généraux actifs sont désactivés (gardés,
    jamais supprimés) ; les séries qui ont une équipe préférée sont refaites avec les nouveaux choix. Renvoie {desactives: [noms]}."""
    prefs = valider(recu)
    d = regles._lire()
    p = _simple(d)
    if p is None:
        p = {"id": uuid.uuid4().hex[:10], "nom": NOM, "series": [], "simple": True}
        d["profils"].append(p)
    p["preferences"] = prefs
    p["series"] = []
    _profil(d, prefs, p)
    desactives = []
    for x in d["profils"]:
        if x is not p and x.get("actif") and not x.get("series"):
            x["actif"] = False
            desactives.append(x["nom"])
        if x.get("simple_serie"):
            _profil(d, prefs, x, x.get("equipe", ""))
    regles._ecrire(d)
    return {"desactives": desactives}


def regler_serie(serie: str, equipe: str) -> str:
    """« Pour cette série, je préfère cette équipe » : ses torrents passent devant tout le reste, les autres restent acceptés.
    Refusé tant que les préférences ne sont pas enregistrées, ou si la série a déjà une règle faite à la main."""
    serie = " ".join((serie or "").split())
    eq = _equipes(equipe)
    if not serie:
        raise ValueError("Choisis une série.")
    if len(eq) != 1:
        raise ValueError("Écris le nom d'une équipe (une seule), tel qu'il apparaît dans le nom des torrents.")
    d = regles._lire()
    p = _simple(d)
    if p is None:
        raise ValueError("Enregistre d'abord tes préférences (bouton en haut de la page).")
    cle = regles._cle(serie)
    for x in d["profils"]:
        if not x.get("auto") and not x.get("simple_serie") and any(regles._cle(s) == cle for s in x.get("series") or []):
            raise ValueError(f"« {serie} » a déjà une règle faite à la main (« {x['nom']} », onglet Profils) : c'est elle qui sert.")
    for x in d["profils"]:
        if x.get("auto"):                                    # la série quitte le profil d'équipe tenu tout seul
            x["series"] = [s for s in x.get("series") or [] if regles._cle(s) != cle]
    d["profils"] = [x for x in d["profils"] if not (x.get("auto") and not x["series"])
                    and not (x.get("simple_serie") and any(regles._cle(s) == cle for s in x.get("series") or []))]
    nouveau = _profil(d, valider(p.get("preferences")), {"id": uuid.uuid4().hex[:10], "nom": f"⭐ {serie} · {eq[0]}", "series": [serie],
                                                         "simple_serie": True, "equipe": eq[0]}, eq[0])
    d["profils"].append(nouveau)
    regles._ecrire(d)
    return nouveau["id"]


def retirer_serie(id_: str) -> bool:
    d = regles._lire()
    reste = [x for x in d["profils"] if not (x.get("simple_serie") and x["id"] == id_)]
    if len(reste) == len(d["profils"]):
        return False
    d["profils"] = reste
    regles._ecrire(d)
    return True


def phrase(prefs: dict) -> str:
    """Les préférences dites en une phrase (page des règles, page Télécharger)."""
    p = valider(prefs)
    m = ["en français seulement" if p["francais"] == "obligatoire" else "le français d'abord"]
    if p["officiel"]:
        m.append("l'édition numérique officielle avant le scan")
    if p["integrale"]:
        m.append("les intégrales avant les tomes un par un")
    if not p["pdf"]:
        m.append("pas de PDF")
    if not p["sans_source"]:
        m.append("jamais un torrent que personne ne partage")
    if p["taille_max_go"]:
        m.append("%g Go au plus" % p["taille_max_go"])
    if p["equipes_plus"]:
        m.append("en tête : " + ", ".join(p["equipes_plus"]))
    if p["equipes_moins"]:
        m.append("refusées : " + ", ".join(p["equipes_moins"]))
    t = " ; ".join(m)
    return t[:1].upper() + t[1:] + "."


def raison_claire(profil: dict, r: dict, raison: str) -> str:
    """Le refus d'un profil simple dit sans chiffres (« score trop bas (0, minimum 30) » ne veut rien dire pour elle)."""
    if not (profil.get("simple") or profil.get("simple_serie")):
        return raison
    noms = set(r.get("formats") or [])
    if raison.startswith("score trop bas"):
        refusees = [e for e in profil.get("equipes_refusees") or [] if "Équipe " + e in noms]
        if refusees:
            return "équipe que tu refuses : " + refusees[0]
        if noms & set(ORIGINALE):
            return "version originale ou sous-titrée, pas en français"
        if not noms & set(FRANCAIS):
            return "rien n'indique qu'il est en français"
        return "pas assez bon d'après tes préférences"
    if raison == "mot interdit : pdf":
        return "c'est un PDF (tu les refuses)"
    if raison.startswith("moins de "):
        return "personne ne le partage (aucune source)"
    return raison
