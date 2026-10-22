"""
Infos de l'édition d'une série : NFO trouvé à l'import, nom de l'archive d'origine, résolution des pages et source
(Digital, Scan, ou chapitres web assemblés). Rangées dans « <série>/.mouflanga-infos.json » : elles suivent la série
quand elle est renommée. Ce qui n'est pas écrit dans un NFO est deviné (et marqué comme tel), corrigeable à la main.
"""
import io
import json
import logging
import os
import re
import threading
import time
from collections import Counter
from pathlib import Path

logger = logging.getLogger(__name__)

FICHIER = ".mouflanga-infos.json"
_en_cours = set()
_verrou = threading.Lock()
MOTS_DIGITAL = re.compile(r"digital|num[ée]rique|\bweb[ -]?dl\b|\bnumerique\b", re.I)
MOTS_SCAN = re.compile(r"\bscann?(?:é|e|er|ed)?\b|\bc2c\b|papier", re.I)


def lire(dossier: Path) -> dict:
    try:
        d = json.loads((Path(dossier) / FICHIER).read_text(encoding="utf-8"))
        return d if isinstance(d, dict) else {}
    except (OSError, ValueError):
        return {}


def ecrire(dossier: Path, d: dict):
    f = Path(dossier) / FICHIER
    tmp = f.with_name(f.name + ".tmp")
    tmp.write_text(json.dumps(d, ensure_ascii=False, indent=1), encoding="utf-8")
    os.replace(tmp, f)


def _texte(octets: bytes) -> str:
    for enc in ("utf-8", "cp1252", "cp437"):
        try:
            return octets.decode(enc)
        except UnicodeDecodeError:
            continue
    return octets.decode("utf-8", "replace")


def analyser_nfo(texte: str) -> dict:
    """Ce que dit un NFO de torrent (lu par presentation.py, comme la page du tracker) : titres, auteur, éditeur, parution, genre, langue,
    format, pages, résolution, source, synopsis (seulement s'il porte son intertitre) et l'ISBN de chaque tome (« Tome 01 -- ISBN : 978… »).
    Seuls les ISBN dont la somme de contrôle est juste sont gardés."""
    import presentation
    out = presentation.analyser(texte, deviner_resume=False)
    out.pop("synopsis_langue", None)
    if out.get("isbn_unique") and not out.get("isbn"):
        out.pop("isbn_unique")                         # un ISBN sans numéro de tome : on ne sait pas à quel tome il va
    return out


def noter_nfo(dossier: Path, texte: str) -> dict:
    """Garde les infos d'un NFO dans celles de la série (« nfo_infos ») et note les ISBN des tomes qui n'en ont pas encore :
    un ISBN déjà noté (à la main ou lu dans les pages) n'est jamais remplacé."""
    nfo = analyser_nfo(texte)
    if not nfo:
        return {}
    d = lire(dossier)
    d["nfo_infos"] = {**(d.get("nfo_infos") or {}), **nfo}
    notes = d.setdefault("isbn", {})
    for t, c in (nfo.get("isbn") or {}).items():
        if not notes.get(t):
            notes[t] = c
    Path(dossier).mkdir(parents=True, exist_ok=True)
    ecrire(dossier, d)
    return nfo


def noter_import(dossier: Path, archive: str, temp: Path):
    """À l'import d'une archive : garde son nom et le texte des NFO (ou petits .txt d'infos) trouvés dedans."""
    textes = []
    for f in sorted(Path(temp).rglob("*")):
        if f.is_file() and f.suffix.lower() in (".nfo", ".txt") and f.stat().st_size < 200_000:
            try:
                textes.append(f"— {f.name} —\n" + _texte(f.read_bytes()).strip())
            except OSError:
                continue
    d = lire(dossier)
    d.setdefault("archives", [])
    if archive not in d["archives"]:
        d["archives"].append(archive)
    if textes:
        d["nfo"] = ("\n\n".join([d.get("nfo", "")] + textes)).strip()[:30000]
    d.pop("analyse", None)                       # nouvelle source : on refera l'analyse
    Path(dossier).mkdir(parents=True, exist_ok=True)
    ecrire(dossier, d)
    for t in textes:
        noter_nfo(dossier, t)                    # titres, synopsis et ISBN du NFO, gardés à part


def _blancheur(img) -> float:
    """Part des pixels « papier » (clairs) qui sont d'un blanc parfait : ~1 pour du digital, bien moins pour un scan."""
    g = img.convert("L")
    g.thumbnail((700, 700))
    h = g.histogram()
    papier = sum(h[200:])
    return sum(h[252:]) / papier if papier else 0.0


def analyser(fichiers: list[Path], indices_texte: str = "") -> dict:
    """Résolution la plus fréquente et source devinée, d'après 3 fichiers et 3 pages chacun (hors couverture)."""
    from PIL import Image
    import archives
    import tomes_cbz
    tailles, blancs, assembles = Counter(), [], 0
    choix = fichiers if len(fichiers) <= 3 else [fichiers[0], fichiers[len(fichiers) // 2], fichiers[-1]]
    for f in choix:
        try:
            if tomes_cbz.lire_info(f) is not None:
                assembles += 1
            noms = archives.pages(f)
        except Exception:
            continue
        n = len(noms)
        for i in sorted({min(n - 1, max(0, k)) for k in (n // 4, n // 2, (3 * n) // 4)}) if n else []:
            try:
                data, _ = archives.read_page(f, i)
                img = Image.open(io.BytesIO(data))
                tailles[img.size] += 1
                blancs.append(_blancheur(img))
            except Exception:
                continue
    res = {"date": time.strftime("%Y-%m-%d"), "devine": True}
    if tailles:
        (l, h), _ = tailles.most_common(1)[0]
        res["resolution"] = f"{l} × {h}"
    moyenne = sum(blancs) / len(blancs) if blancs else None
    if MOTS_DIGITAL.search(indices_texte):
        res.update(source="Digital", pourquoi="nom de l'archive ou NFO", devine=False)
    elif MOTS_SCAN.search(indices_texte):
        res.update(source="Scan", pourquoi="nom de l'archive ou NFO", devine=False)
    elif assembles and assembles * 2 >= len(choix):
        res.update(source="Web (chapitres)", pourquoi="chapitres téléchargés et regroupés en tomes")
    elif tailles:
        (l, h), _ = tailles.most_common(1)[0]
        arrondies = Counter()                      # 1600 × 2397 et 1600 × 2400 : même format
        for (a, b), k in tailles.items():
            arrondies[(round(a / 60), round(b / 60))] += k
        varie = arrondies.most_common(1)[0][1] < sum(tailles.values()) * 0.6
        if l > h:
            res.update(source="Scan", pourquoi="pages scannées par paires (format paysage)")
        elif h >= 1600 and not varie:
            res.update(source="Digital", pourquoi="haute résolution, pages toutes de la même taille")
        elif h <= 1300:
            res.update(source="Scan", pourquoi="résolution d'un scan web")
        elif moyenne is not None and moyenne >= 0.85:
            res.update(source="Digital", pourquoi="blancs parfaits")
        elif moyenne is not None and moyenne < 0.55:
            res.update(source="Scan", pourquoi="grain du papier")
        else:
            res.update(source="", pourquoi="indécis")
        if moyenne is not None:
            res["blancheur"] = round(moyenne, 2)
    return res


def volumes_du_titre(titre: str):
    """« Cat's Eye - Édition de luxe [Intégrale 15 tomes] » → 15 ; None si le titre ne le dit pas."""
    m = re.search(r"(\d{1,3})\s*tomes?\b", titre or "", re.I)
    if m:
        return int(m.group(1))
    # « Gantz - Perfect Édition (01-18) », « Intégrale T01-77 » : une plage qui commence au tome 1
    m = re.search(r"[(\[\s]T?0*1\s*[-–]\s*T?(\d{1,3})(?=[)\]\s]|$)", titre or "", re.I)
    return int(m.group(1)) if m and int(m.group(1)) > 1 else None


def edition_du_titre(titre: str):
    """« Cat's Eye - Édition de luxe [...] » → « Édition de luxe » ; None si aucune mention d'édition."""
    import noms_editions
    m = noms_editions.MENTION.search(titre or "")
    return m.group(0).strip().capitalize() if m else None


def noter_volumes(dossier: Path, titre: str):
    """Garde le nombre de tomes et la mention d'édition de l'import (l'édition peut différer de l'édition standard)."""
    d = lire(dossier)
    n, ed = volumes_du_titre(titre), edition_du_titre(titre)
    changed = False
    if n and d.get("volumes_attendus") != n:
        d["volumes_attendus"], changed = n, True
    if ed and d.get("edition") != ed:
        d["edition"], changed = ed, True
    if changed:
        ecrire(dossier, d)


def detecter_regroupement(sommaires: dict, standard: dict):
    """Édition qui regroupe les tomes autrement que l'édition standard (Perfect, deluxe, intégrale… sans que le nom du
    fichier le dise) : d'après les chapitres lus dans le sommaire imprimé de CHAQUE tome (sommaires = {tome: {"chapitres":
    [{"num"}]}}) comparés à la répartition connue de l'édition standard (standard = {tome: [numéros de chapitres]}).
    Renvoie {"tomes": [tomes locaux en désaccord], "exemple": (tome local, tomes standard)} ou None. Il faut au moins un tome
    local qui contient des chapitres de deux tomes standard ou plus."""
    de_chapitre = {}
    for t, nums in (standard or {}).items():
        for n in nums:
            de_chapitre.setdefault(float(n), str(t))
    if len(set(de_chapitre.values())) < 2:
        return None
    desaccord, exemple = [], None
    for t, s in (sommaires or {}).items():
        nums = [float(c["num"]) for c in (s or {}).get("chapitres", []) if c.get("num") is not None]
        vus = {}
        for n in nums:
            if n in de_chapitre:
                vus[de_chapitre[n]] = vus.get(de_chapitre[n], 0) + 1
        couverts = sorted((k for k, c in vus.items() if c >= 2), key=lambda x: int(x))     # un seul chapitre : mauvaise lecture
        suite = bool(couverts) and int(couverts[-1]) - int(couverts[0]) == len(couverts) - 1   # tomes standard à la suite
        if len(nums) >= 3 and len(couverts) >= 2 and suite:
            desaccord.append(str(t))
            exemple = exemple or (str(t), couverts)
    return {"tomes": desaccord, "exemple": exemple} if desaccord else None


def oublier_source(dossier: Path):
    """Tous les tomes d'une série viennent d'être remplacés : les archives et NFO de l'ancienne source ne la décrivent plus."""
    d = lire(dossier)
    if [d.pop(k, None) for k in ("archives", "nfo", "analyse")] != [None, None, None]:
        ecrire(dossier, d)


def invalider(dossier: Path):
    """Après un remplacement de tomes : la résolution et la source sont à refaire avec les nouveaux fichiers."""
    d = lire(dossier)
    if d.pop("analyse", None) is not None:
        ecrire(dossier, d)


def infos(dossier: Path, fichiers: list[Path], lancer=True) -> dict:
    """Infos à afficher ; l'analyse des pages se fait une fois, en arrière-plan (le résultat vient au rechargement)."""
    d = lire(dossier)
    if "analyse" not in d and fichiers and lancer:
        cle = str(dossier)
        with _verrou:
            if cle in _en_cours:
                return d
            _en_cours.add(cle)

        def travail():
            try:
                texte = " ".join(d.get("archives", [])) + " " + d.get("nfo", "")[:3000] + " " + " ".join(f.name for f in fichiers[:50])
                a = analyser(fichiers, texte)
                d2 = lire(dossier)
                d2["analyse"] = a
                ecrire(dossier, d2)
                logger.info("Édition de « %s » : %s %s", Path(dossier).name, a.get("source") or "?", a.get("resolution", ""))
            except Exception as e:
                logger.warning("Analyse de l'édition de %s impossible : %s", dossier, e)
            finally:
                _en_cours.discard(cle)
        threading.Thread(target=travail, daemon=True).start()
    return d
