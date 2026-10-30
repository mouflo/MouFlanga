"""Découpage d'un gros fichier (intégrale en un seul .cbz) en un fichier par tome.

Deux façons :
- d'après le sommaire intégré au fichier (index.json des sites de lecture, ex. Buyuden : « Tome 1 - Chapitre 1 : … »
  et les pages de chaque chapitre) → tomes AVEC leurs chapitres (format des tomes de l'appli) ;
- à la main : l'utilisatrice indique la première page de chaque tome (écran ✂️) → un fichier par tome.
Le fichier d'origine n'est jamais modifié ; il part à la corbeille seulement quand tout est écrit.
"""
import io
import json
import logging
import re
import threading
import zipfile
from pathlib import Path

import archives
import tomes_cbz

logger = logging.getLogger("mouflanga")

_ETAT = {}                      # chemin du fichier → {"en_cours", "fait", "total", "message"}
_VERROU = threading.Lock()


def plan_index(chemin: Path) -> list[dict] | None:
    """Chapitres d'après index.json : [{"tome", "num", "titre", "pages": [indices]}], ou None s'il n'y en a pas."""
    try:
        with zipfile.ZipFile(chemin) as z:
            if "index.json" not in z.namelist():
                return None
            index = json.loads(z.read("index.json"))
    except (OSError, zipfile.BadZipFile, ValueError):
        return None
    noms = archives.pages(chemin)
    out = []
    for c in (index.get("chapters") or {}).values():
        m = re.match(r"\s*Tome\s*(\d+)\s*-\s*Chapitre\s*([\d.]+)\s*(?::\s*(.*))?$", c.get("name") or "", re.I)
        motif = c.get("entries") or ""
        if not m or not motif:
            continue
        try:
            rx = re.compile(motif.replace("\\\\", "\\"))
        except re.error:
            continue
        pages = [i for i, n in enumerate(noms) if rx.match(Path(n).stem)]
        if pages:
            out.append({"tome": int(m.group(1)), "num": float(m.group(2)), "titre": (m.group(3) or "").strip(), "pages": pages})
    if not out:
        return None
    out.sort(key=lambda c: (c["tome"], c["num"]))
    return out


def debuts_depuis_plan(plan) -> dict:
    """{tome: première page} d'après le plan des chapitres (pré-remplit l'écran ✂️)."""
    debuts = {}
    for c in plan:
        debuts[c["tome"]] = min(debuts.get(c["tome"], 10 ** 9), min(c["pages"]))
    return debuts


def etat(chemin):
    with _VERROU:
        return dict(_ETAT.get(str(chemin)) or {})


def decouper(chemin: Path, dossier: Path, serie: str, debuts: dict, plan=None, fini=None):
    """Écrit un fichier par tome dans dossier/Tome NN/. debuts = {tome: première page (index)} ; avec un plan de
    chapitres, chaque tome garde ses chapitres et leurs titres. fini(ok, message) est appelé à la fin (en arrière-plan)."""
    cle = str(chemin)
    with _VERROU:
        if (_ETAT.get(cle) or {}).get("en_cours"):
            return False
        _ETAT[cle] = {"en_cours": True, "fait": 0, "total": len(debuts), "message": "Découpage…"}

    def travail():
        ok, msg = True, ""
        try:
            nb = len(archives.pages(chemin))
            ordre = sorted(debuts.items(), key=lambda x: x[1])
            for k, (tome, debut) in enumerate(ordre):
                fin = ordre[k + 1][1] if k + 1 < len(ordre) else nb
                with _VERROU:
                    _ETAT[cle]["tome"] = tome
                cible = tomes_cbz.fichier_tome(dossier, serie, tome)
                cible.parent.mkdir(parents=True, exist_ok=True)
                chapitres = [c for c in (plan or []) if c["tome"] == tome]
                if chapitres:
                    ajouts = {c["num"]: [archives.read_page(chemin, i)[0] for i in c["pages"]] for c in chapitres}
                    tomes_cbz._reecrire(cible, serie, tome, set(), ajouts, {c["num"]: c["titre"] for c in chapitres})
                else:
                    tmp = cible.with_name("." + cible.name + ".tmp")
                    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as z:
                        for j, i in enumerate(range(debut, fin), 1):
                            data, mime = archives.read_page(chemin, i)
                            ext = {"image/png": ".png", "image/webp": ".webp", "image/gif": ".gif"}.get(mime, ".jpg")
                            z.writestr(f"{j:04d}{ext}", data)
                    tmp.replace(cible)
                with _VERROU:
                    _ETAT[cle]["fait"] = k + 1
            msg = f"✅ {len(ordre)} tome(s) écrits."
        except Exception as e:
            ok, msg = False, f"Découpage impossible : {e}"
            logger.warning("Découpage de %s : %s", chemin, e)
        if fini:
            try:
                extra = fini(ok, msg)
                if extra:
                    msg += " " + extra
            except Exception as e:
                logger.warning("Fin du découpage de %s : %s", chemin, e)
        with _VERROU:
            _ETAT[cle].update(en_cours=False, message=msg)
        logger.info("Découpage de « %s » : %s", serie, msg)
    threading.Thread(target=travail, daemon=True).start()
    return True


def miniature(chemin: Path, index: int, largeur=180) -> bytes:
    from PIL import Image
    data, _ = archives.read_page(chemin, index)
    im = Image.open(io.BytesIO(data))
    im.thumbnail((largeur, largeur * 2))
    out = io.BytesIO()
    im.convert("RGB").save(out, "JPEG", quality=70)
    return out.getvalue()
