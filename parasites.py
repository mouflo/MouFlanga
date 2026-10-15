"""🧹 Pages parasites des scans d'équipe (scantrad) : crédits, « on recrute », pubs pour le site ou le Discord.

Ces pages reviennent à l'identique (ou presque : les pseudos changent) dans beaucoup de chapitres. Chaque page reçoit une
empreinte (dHash 16×16 = 256 bits, insensible à la taille et à la compression) ; les pages dont les empreintes diffèrent
de 20 bits au plus forment un groupe. Un groupe d'au moins 3 pages est proposé ; c'est l'administrateur qui coche ce qui
est à jeter (une vraie page du manga peut être en double). Les empreintes refusées sont gardées avec la série : les
prochains tomes arrivés sont nettoyés tout seuls.
Retrait : même principe que la découpe des doubles pages (optimiser.couper) : version écrite à côté, relue, puis
remplacée ; l'ancienne part à la corbeille (30 jours). Un fichier partagé par qBittorrent n'est jamais modifié sur place.
"""
import io
import logging
import threading
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageFile

import archives

logger = logging.getLogger("mouflanga")
SEUIL = 20                     # bits différents (sur 256) pour deux pages « identiques »
MIN_GROUPE = 3
_FORMATS = (".jpg", ".jpeg", ".png", ".webp", ".gif", ".bmp")
_ETAT = {}                     # série → {"en_cours", "fait", "total", "message", "groupes" | "rapport"}
_VERROU = threading.Lock()
_CACHE = {}                    # (chemin, mtime, taille) → [(index, empreinte, unie)]
_OCTETS_BITS = np.array([bin(i).count("1") for i in range(256)], dtype=np.uint8)


def empreinte(octets: bytes):
    """(empreinte en entier de 256 bits, page unie) : dHash sur 17×16 niveaux de gris."""
    ImageFile.LOAD_TRUNCATED_IMAGES = True
    with Image.open(io.BytesIO(octets)) as im:
        im.draft("L", (128, 128))                         # JPEG : décodage réduit, bien plus rapide
        g = np.asarray(im.convert("L").resize((17, 16)), dtype=np.int16)
    bits = (g[:, :-1] > g[:, 1:]).flatten()
    return int("".join("1" if b else "0" for b in bits), 2), float(g.std()) < 6


def empreintes_tome(chemin: Path) -> list:
    """[(index de page, empreinte, unie)] pour chaque image du tome (gardées en mémoire tant que le fichier ne change pas)."""
    chemin = Path(chemin)
    st = chemin.stat()
    cle = (str(chemin), st.st_mtime_ns, st.st_size)
    if cle in _CACHE:
        return _CACHE[cle]
    res = []
    with zipfile.ZipFile(chemin) as z:
        for i, nom in enumerate(archives.pages(chemin)):
            if Path(nom).suffix.lower() not in _FORMATS:
                continue
            try:
                h, unie = empreinte(z.read(nom))
                res.append((i, h, unie))
            except Exception as e:
                logger.info("Page %s de %s sans empreinte : %s", nom, chemin.name, e)
    if len(_CACHE) > 2000:
        _CACHE.clear()
    _CACHE[cle] = res
    return res


def _tableau(empreintes) -> np.ndarray:
    return np.array([list(int(h).to_bytes(32, "big")) for h in empreintes], dtype=np.uint8).reshape(-1, 32)


def distances(h, tableau: np.ndarray) -> np.ndarray:
    """Nombre de bits différents entre l'empreinte h et chaque ligne du tableau."""
    if not len(tableau):
        return np.zeros(0, dtype=np.int32)
    ligne = np.frombuffer(int(h).to_bytes(32, "big"), dtype=np.uint8)
    return _OCTETS_BITS[np.bitwise_xor(tableau, ligne)].sum(axis=1, dtype=np.int32)


def grouper(pages: list, refusees=()) -> list:
    """pages = [(fichier, index, empreinte, unie)] → groupes d'au moins MIN_GROUPE pages qui se ressemblent, les plus
    nombreux d'abord : [{"empreinte", "pages": [(fichier, index)], "tomes", "unie", "refusee"}]."""
    if not pages:
        return []
    tab = _tableau([p[2] for p in pages])
    libre = np.ones(len(pages), dtype=bool)
    ref = _tableau(refusees) if refusees else np.zeros((0, 32), dtype=np.uint8)
    groupes = []
    for i in range(len(pages)):
        if not libre[i]:
            continue
        proches = np.where(libre & (distances(pages[i][2], tab) <= SEUIL))[0]
        if len(proches) < MIN_GROUPE:
            continue
        libre[proches] = False
        membres = [pages[j] for j in proches]
        groupes.append({"empreinte": format(pages[i][2], "064x"), "pages": [(m[0], m[1]) for m in membres],
                        "tomes": len({m[0] for m in membres}), "unie": sum(m[3] for m in membres) * 2 > len(membres),
                        "refusee": bool(len(ref)) and int(distances(pages[i][2], ref).min()) <= SEUIL})
    groupes.sort(key=lambda g: -len(g["pages"]))
    return groupes


def a_retirer(chemin: Path, refusees) -> list:
    """Numéros de page du tome qui ressemblent à une page déjà refusée pour la série."""
    if not refusees:
        return []
    ref = _tableau([int(h, 16) for h in refusees])
    return [i for i, h, _ in empreintes_tome(chemin) if int(distances(h, ref).min()) <= SEUIL]


def analyser(serie: str, fichiers, refusees=()) -> bool:
    """En arrière-plan : empreintes de toutes les pages des tomes, puis groupes (voir etat(serie)["groupes"])."""
    with _VERROU:
        if (_ETAT.get(serie) or {}).get("en_cours"):
            return False
        _ETAT[serie] = {"en_cours": True, "fait": 0, "total": len(fichiers), "message": "Comparaison des pages…"}

    def travail():
        pages = []
        try:
            for f in fichiers:
                try:
                    pages += [(Path(f).name, i, h, u) for i, h, u in empreintes_tome(Path(f))]
                except Exception as e:
                    logger.warning("Pages parasites, %s illisible : %s", f, e)
                with _VERROU:
                    _ETAT[serie]["fait"] += 1
            groupes = grouper(pages, [int(h, 16) for h in refusees])
            msg = f"{len(groupes)} groupe(s) de pages qui se répètent ({sum(len(g['pages']) for g in groupes)} pages)."
            with _VERROU:
                _ETAT[serie].update(en_cours=False, message=msg, groupes=groupes, pages=len(pages))
        except Exception as e:
            logger.warning("Pages parasites de %s : %s", serie, e)
            with _VERROU:
                _ETAT[serie].update(en_cours=False, message=f"Erreur : {e}")
    threading.Thread(target=travail, daemon=True).start()
    return True


def etat(serie):
    with _VERROU:
        return dict(_ETAT.get(serie) or {})


def _comicinfo_maj(donnees: bytes, carte: dict, nb: int) -> bytes:
    """Signets de ComicInfo : pages recalées, nombre de pages mis à jour. Le signet d'un chapitre posé sur une page
    retirée (souvent les crédits, au début du chapitre) passe à la page gardée qui suit."""
    try:
        racine = ET.fromstring(donnees)
    except ET.ParseError:
        return donnees
    for parent in list(racine.iter()):
        pris = set()
        for p in list(parent):
            if p.tag != "Page":
                continue
            try:
                ancien = int(p.get("Image", ""))
            except ValueError:
                continue
            if ancien not in carte:
                suivante = min((k for k in carte if k > ancien), default=None)
                if not p.get("Bookmark") or suivante is None:
                    parent.remove(p)
                    continue
                ancien = suivante
            nouveau = carte[ancien]
            if nouveau in pris:                               # deux entrées sur la même page : la première reste
                parent.remove(p)
                continue
            pris.add(nouveau)
            p.set("Image", str(nouveau))
    pc = racine.find("PageCount")
    if pc is not None:
        pc.text = str(nb)
    return ET.tostring(racine, encoding="utf-8", xml_declaration=True)


def retirer(chemin: Path, indices, destination=None) -> dict:
    """Écrit le tome sans les pages « indices » (numéros du lecteur). Version à côté (ou « destination » pour un fichier
    partagé), relue, puis remplacée ; l'ancienne est renvoyée dans « avant » (à mettre à la corbeille).
    Renvoie {"carte": {ancien numéro: nouveau}, "pages_avant", "pages", "avant"}."""
    chemin = Path(chemin)
    ordre = archives.pages(chemin)
    enlevees = {ordre[i] for i in indices if 0 <= i < len(ordre)}
    if not enlevees:
        raise RuntimeError("aucune page à retirer")
    if len(enlevees) >= len(ordre):
        raise RuntimeError("toutes les pages seraient retirées")
    gardees = [n for n in ordre if n not in enlevees]
    carte = {ordre.index(n): k for k, n in enumerate(gardees)}
    tmp = Path(destination) if destination is not None else chemin.with_name("." + chemin.name + ".nettoye")
    with zipfile.ZipFile(chemin) as z, zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        for info in z.infolist():
            if info.filename in enlevees:
                continue
            data = z.read(info.filename)
            if Path(info.filename).name == "ComicInfo.xml":
                data = _comicinfo_maj(data, carte, len(gardees))
            info2 = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            info2.compress_type = zipfile.ZIP_STORED
            dst.writestr(info2, data)
    with zipfile.ZipFile(tmp) as z:                       # relecture : archive saine, les pages gardées dans le même ordre
        if z.testzip() is not None or archives._names(z) != gardees:
            tmp.unlink()
            raise RuntimeError("archive nettoyée illisible ou pages différentes")
    res = {"carte": carte, "pages_avant": len(ordre), "pages": len(gardees)}
    if destination is not None:
        return res
    avant = chemin.with_name(chemin.name + ".avant")
    chemin.rename(avant)
    tmp.rename(chemin)
    res["avant"] = avant
    return res


def nettoyer_tome(chemin: Path, indices, serie: str, vers_corbeille) -> dict:
    """Retire les pages d'un tome en respectant les fichiers partagés par qBittorrent (voir optimiser.echanger_dossier)."""
    import optimiser
    chemin = Path(chemin)
    if chemin.stat().st_nlink > 1 and not optimiser._dossier_a_lui(chemin, serie):
        return {"note": "partagé par qBittorrent hors d'un dossier de tome : jamais modifié"}
    if chemin.stat().st_nlink > 1:
        res = {}

        def ecrire(dest):
            res.update(retirer(chemin, indices, destination=dest))
            return True
        optimiser.echanger_dossier(chemin, ecrire, vers_corbeille)
        return {**res, "note": "partagé par qBittorrent : version nettoyée à part, le torrent n'est pas touché"}
    res = retirer(chemin, indices)
    vers_corbeille(res.pop("avant"))
    return res


def lancer_nettoyage(serie, travaux, vers_corbeille, apres=None) -> bool:
    """En arrière-plan : travaux = [(chemin, {numéros de page})]. apres(chemin, carte) après chaque tome."""
    with _VERROU:
        if (_ETAT.get(serie) or {}).get("en_cours"):
            return False
        _ETAT[serie] = {"en_cours": True, "fait": 0, "total": len(travaux), "message": "Nettoyage…", "rapport": []}

    def travail():
        rapport, retirees = [], 0
        for chemin, indices in travaux:
            ligne = {"fichier": Path(chemin).name}
            try:
                res = nettoyer_tome(chemin, indices, serie, vers_corbeille)
                ligne.update({k: v for k, v in res.items() if k in ("pages_avant", "pages", "note")})
                if "carte" in res:
                    retirees += res["pages_avant"] - res["pages"]
                    if apres:
                        apres(Path(chemin), res["carte"])
            except Exception as e:
                logger.warning("Pages parasites retirées de %s : %s", chemin, e)
                ligne["note"] = f"erreur : {e}"
            rapport.append(ligne)
            with _VERROU:
                _ETAT[serie]["fait"] += 1
                _ETAT[serie]["rapport"] = list(rapport)
        msg = f"{retirees} page(s) parasite(s) retirée(s) dans {len(travaux)} tome(s)."
        with _VERROU:
            _ETAT[serie].update(en_cours=False, message=msg, rapport=rapport, groupes=None)
        logger.info("Pages parasites de « %s » : %s", serie, msg)
    threading.Thread(target=travail, daemon=True).start()
    return True


LONGUEUR_MIN = 8               # pages au moins dans un chapitre (sinon : plusieurs pages d'équipe à la suite)


def debuts_de_chapitres(reperes, nb_pages: int) -> list:
    """Débuts de chapitres d'un tome d'après la place des pages d'équipe (avant leur retrait) : une suite de pages
    d'équipe (crédits au début d'un chapitre, « on recrute » à la fin) sépare deux chapitres ; le chapitre suivant
    commence à la première page qui n'en est pas une. Renvoie [(index, estimé)] : les trous réguliers (un passage
    sans crédits long de 2 ou 3 chapitres) reçoivent des débuts estimés d'après la longueur habituelle."""
    reperes = set(reperes)
    debuts = []
    for i in sorted(reperes):
        j = i + 1
        while j in reperes:
            j += 1
        if j < nb_pages and (not debuts or j != debuts[-1]):
            debuts.append(j)
    propres = []                                           # chapitres trop courts : pages d'équipe proches, un seul début
    for d in debuts:
        if not propres or d - propres[-1] >= LONGUEUR_MIN:
            propres.append(d)
    if len(propres) < 2:
        return [(d, False) for d in propres]
    fin = max([i for i in range(nb_pages) if i not in reperes] or [nb_pages - 1]) + 1
    bornes = propres + [fin]
    longueurs = sorted(b - a for a, b in zip(bornes, bornes[1:]))
    L = longueurs[len(longueurs) // 2]                     # longueur habituelle d'un chapitre (médiane)
    sortie = []
    premier = min([i for i in range(nb_pages) if i not in reperes] or [0])
    avant = propres[0] - premier                           # pages sans crédits au début du tome : chapitres entiers ?
    k = round(avant / L) if L else 0
    if k >= 1 and abs(avant - k * L) <= 0.3 * L * k:
        sortie += [(propres[0] - (k - n) * round(avant / k), True) for n in range(k)]
    for a, b in zip(bornes, bornes[1:]):
        sortie.append((a, False))
        k = round((b - a) / L) if L else 1
        if k >= 2 and abs((b - a) - k * L) <= 0.3 * L * k:
            sortie += [(a + n * round((b - a) / k), True) for n in range(1, k)]
    return sortie


def chapitres_par_reperes(reperes, nb_pages: int, numeros=(), suite_de=None) -> list:
    """Chapitres numérotés : numéros connus du tome (liste Internet) s'il y en a autant que de débuts, sinon suite du
    tome précédent (suite_de = dernier chapitre). [] si on ne peut pas numéroter sans risque de décalage."""
    debuts = debuts_de_chapitres(reperes, nb_pages)
    if len(debuts) < 2:
        return []
    numeros = sorted(float(n) for n in numeros or [])
    if numeros and len(numeros) == len(debuts):
        nums = numeros
    elif not numeros and suite_de is not None:
        nums = [float(int(suite_de) + 1 + k) for k in range(len(debuts))]
    else:
        return []
    return [{"num": n, "titre": f"Chapitre {n:g}", "page": i + 1, "image": i, **({"estimee": True} if e else {})}
            for n, (i, e) in zip(nums, debuts)]
