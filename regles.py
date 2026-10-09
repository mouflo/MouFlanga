"""
Règles de recherche des torrents, comme Sonarr : des profils (quels torrents sont acceptés) et des formats
personnalisés (quels mots donnent des points). Enregistrés dans data/regles.json (jamais sur GitHub).
"""
import json
import re
import uuid
from pathlib import Path

FICHIER = Path(__file__).resolve().parent / "data" / "regles.json"


def _lire() -> dict:
    try:
        d = json.loads(FICHIER.read_text(encoding="utf-8"))
        return {"profils": d.get("profils", []), "formats": d.get("formats", [])}
    except (OSError, ValueError):
        return {"profils": [], "formats": []}


def _ecrire(d: dict):
    FICHIER.parent.mkdir(parents=True, exist_ok=True)
    tmp = FICHIER.with_suffix(".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    tmp.replace(FICHIER)


def _liste(texte: str) -> list[str]:
    """« kaf, Tsundere-Raws » → ['kaf', 'Tsundere-Raws'] ; un terme par virgule ou par ligne."""
    return [x.strip() for x in re.split(r"[,\n]", texte or "") if x.strip()]


def profils() -> list[dict]:
    return _lire()["profils"]


def formats() -> list[dict]:
    return _lire()["formats"]


def enregistrer_profil(id_: str, nom: str, actif: bool, doit: str, ne_doit_pas: str, series: str, taille_max_go: str) -> str:
    """Crée ou modifie un profil ; renvoie son identifiant. Le nom est obligatoire."""
    nom = (nom or "").strip()
    if not nom:
        raise ValueError("Donne un nom au profil.")
    try:
        taille = float(str(taille_max_go).replace(",", ".")) if str(taille_max_go).strip() else None
    except ValueError:
        raise ValueError("La taille maximale doit être un nombre de Go (ou vide).")
    d = _lire()
    p = {"id": id_ or uuid.uuid4().hex[:10], "nom": nom, "actif": bool(actif), "doit": _liste(doit),
         "ne_doit_pas": _liste(ne_doit_pas), "series": _liste(series), "taille_max_go": taille}
    d["profils"] = [x for x in d["profils"] if x["id"] != p["id"]] + [p]
    _ecrire(d)
    return p["id"]


def enregistrer_format(id_: str, nom: str, termes: str, score: str) -> str:
    nom = (nom or "").strip()
    if not nom:
        raise ValueError("Donne un nom au format personnalisé.")
    try:
        pts = int(str(score).strip() or "0")
    except ValueError:
        raise ValueError("Le score doit être un nombre entier (négatif pour pénaliser).")
    d = _lire()
    f = {"id": id_ or uuid.uuid4().hex[:10], "nom": nom, "termes": _liste(termes), "score": pts}
    d["formats"] = [x for x in d["formats"] if x["id"] != f["id"]] + [f]
    _ecrire(d)
    return f["id"]


def supprimer(quoi: str, id_: str):
    d = _lire()
    cle = "profils" if quoi == "profil" else "formats"
    d[cle] = [x for x in d[cle] if x["id"] != id_]
    _ecrire(d)


def _mot(terme: str, titre: str) -> bool:
    return terme.lower() in titre.lower()


def _concerne(profil: dict, serie: str) -> bool:
    """Un profil sans série s'applique à tout ; sinon seulement aux séries nommées (sans accents ni casse)."""
    if not profil.get("series"):
        return True
    cle = lambda s: re.sub(r"[^a-z0-9]", "", s.lower())
    return any(cle(s) and cle(s) in cle(serie or "") for s in profil["series"])


def filtrer(resultats: list[dict], serie: str = "") -> list[dict]:
    """Garde les torrents acceptés par les profils actifs qui concernent la série, et ajoute leur score."""
    actifs = [p for p in profils() if p.get("actif")]
    fmts = [f for f in formats() if f.get("termes")]
    out = []
    for r in resultats:
        titre = r.get("titre") or ""
        ok = True
        for p in actifs:
            if not _concerne(p, serie):
                continue
            if p.get("doit") and not any(_mot(t, titre) for t in p["doit"]):
                ok = False
            if any(_mot(t, titre) for t in p.get("ne_doit_pas") or []):
                ok = False
            if p.get("taille_max_go") and r.get("taille") and r["taille"] > p["taille_max_go"] * 1024 ** 3:
                ok = False
        if not ok:
            continue
        r["score"] = sum(f["score"] for f in fmts if any(_mot(t, titre) for t in f["termes"]))
        out.append(r)
    return out
