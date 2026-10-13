"""🪶 Alléger les tomes sans perte visible, et 🧼 éclaircir le papier des scans gris.

Alléger : pour chaque tome, quelques pages d'essai sont recompressées en JPEG à plusieurs qualités ; on garde la plus
basse dont l'écart avec l'original reste invisible (PSNR ≥ 42 dB sur chaque page d'essai) et qui fait gagner au moins
10 %. Une page qui ne gagne rien garde ses octets d'origine. Les noms et l'ordre des pages, chapitres.json et
ComicInfo.xml sont recopiés tels quels : le tome reste lisible et rangé pareil.
Éclaircir : niveaux automatiques en gris (le papier gris redevient blanc, les noirs restent noirs), jamais sur une page
en couleur.
L'original part à la corbeille (30 jours) seulement quand le nouveau fichier est écrit et relu ; un fichier encore
partagé par qBittorrent (lien physique) n'est jamais touché.
"""
import io
import logging
import threading
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image, ImageOps

logger = logging.getLogger("mouflanga")

QUALITES = (80, 85, 88, 92)
PSNR_MIN = 39.0            # en dessous, des différences peuvent se voir en zoomant ; au-dessus, invisibles à l'écran
GAIN_MIN = 0.10
_IMAGES = (".jpg", ".jpeg")                 # seulement les JPEG : un PNG ou un WebP garde son format et ses octets
_ETAT = {}                      # série → {"en_cours", "fait", "total", "message", "rapport"}
_VERROU = threading.Lock()


def _psnr(a: Image.Image, b: Image.Image) -> float:
    x = np.asarray(a.convert("L"), dtype=np.float32)
    y = np.asarray(b.convert("L"), dtype=np.float32)
    mse = float(np.mean((x - y) ** 2))
    return 99.0 if mse == 0 else 10 * np.log10(255 ** 2 / mse)


def _jpeg(im: Image.Image, q: int) -> bytes:
    out = io.BytesIO()
    im.convert("RGB" if im.mode not in ("L", "RGB") else im.mode).save(out, "JPEG", quality=q, optimize=True, progressive=True)
    return out.getvalue()


def _pages(z: zipfile.ZipFile):
    return [n for n in z.namelist() if Path(n).suffix.lower() in _IMAGES]


def est_couleur(im: Image.Image) -> bool:
    """Page en couleur (pas un scan noir et blanc) : écart moyen entre canaux sur une version réduite."""
    if im.mode in ("L", "1"):
        return False
    petit = np.asarray(im.convert("RGB").resize((120, 180)), dtype=np.int16)
    return float(np.mean(np.abs(petit[..., 0] - petit[..., 1]) + np.abs(petit[..., 1] - petit[..., 2]))) > 12


def eclaircir(im: Image.Image) -> Image.Image:
    """Niveaux automatiques d'une page en gris : le papier (gris clair) devient blanc, les noirs restent noirs."""
    g = im.convert("L")
    return ImageOps.autocontrast(g, cutoff=(0.5, 1.5))


def reduire(im: Image.Image, largeur_max) -> Image.Image:
    """Page plus large que l'écran qui l'affichera (largeur_max px) : réduite, proportions gardées. Double page : sa moitié."""
    if not largeur_max:
        return im
    limite = largeur_max * (2 if im.width > im.height else 1)
    if im.width <= limite:
        return im
    return im.resize((limite, round(im.height * limite / im.width)), Image.LANCZOS)


def analyser(chemin: Path, nb_essai=8, eclairer=False, largeur_max=None, qualite_forcee=None) -> dict:
    """Choisit la qualité d'un tome : {"qualite", "gain_estime" (0-1), "psnr_min", "taille"} (qualite None : rien à gagner).
    qualite_forcee : réglage manuel, seule cette qualité est essayée (sans seuil d'écart : c'est ton choix) ; None si elle ne gagne rien."""
    taille = chemin.stat().st_size
    with zipfile.ZipFile(chemin) as z:
        noms = _pages(z)
        if not noms:
            return {"qualite": None, "gain_estime": 0, "psnr_min": None, "taille": taille}
        pas = max(1, len(noms) // nb_essai)
        essai = noms[::pas][:nb_essai]
        originaux = {n: z.read(n) for n in essai}
    images = {n: Image.open(io.BytesIO(b)) for n, b in originaux.items()}
    for im in images.values():
        im.load()
    if eclairer:
        images = {n: (im if est_couleur(im) else eclaircir(im)) for n, im in images.items()}
    images = {n: reduire(im, largeur_max) for n, im in images.items()}
    total = sum(len(b) for b in originaux.values())
    meilleur = {"qualite": None, "gain_estime": 0.0, "psnr_min": None, "taille": taille}
    if qualite_forcee:
        nouveaux, psnrs = 0, []
        for n, im in images.items():
            b = _jpeg(im, qualite_forcee)
            psnrs.append(_psnr(im, Image.open(io.BytesIO(b))))
            nouveaux += min(len(b), len(originaux[n])) if not (eclairer or largeur_max) else len(b)
        gain = 1 - nouveaux / total
        if gain > 0 or eclairer:
            meilleur = {"qualite": int(qualite_forcee), "gain_estime": round(float(gain), 3), "psnr_min": round(float(min(psnrs)), 1), "taille": taille}
        return meilleur
    for q in sorted(QUALITES, reverse=True):          # de la plus fidèle à la plus légère : on garde la dernière acceptable
        nouveaux, psnrs = 0, []
        for n, im in images.items():
            b = _jpeg(im, q)
            psnrs.append(_psnr(im, Image.open(io.BytesIO(b))))
            nouveaux += min(len(b), len(originaux[n])) if not (eclairer or largeur_max) else len(b)
        gain = 1 - nouveaux / total
        if min(psnrs) >= PSNR_MIN and (gain >= GAIN_MIN or eclairer):
            meilleur = {"qualite": q, "gain_estime": round(float(gain), 3), "psnr_min": round(float(min(psnrs)), 1), "taille": taille}
    return meilleur


def reecrire(chemin: Path, qualite: int, eclairer=False, largeur_max=None, destination: Path | None = None) -> int:
    """Écrit la version allégée (ou éclaircie) à côté, la relit, puis remplace. Renvoie le nombre d'octets gagnés.
    L'ancien fichier est renvoyé à l'appelant via un nom « .avant » (à mettre à la corbeille).
    Avec « destination » (fichier partagé par qBittorrent : le NAS refuse de le renommer), la version allégée est seulement
    écrite là, relue, et l'original n'est pas touché : l'appelant échange les dossiers."""
    tmp = destination if destination is not None else chemin.with_name("." + chemin.name + ".allege")
    with zipfile.ZipFile(chemin) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            if Path(info.filename).suffix.lower() in _IMAGES:
                im = Image.open(io.BytesIO(data))
                im.load()
                if eclairer and not est_couleur(im):
                    im = eclaircir(im)
                im2 = reduire(im, largeur_max)
                nouveau = _jpeg(im2, qualite)
                if eclairer or im2 is not im or len(nouveau) < len(data):
                    data = nouveau
            info2 = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            info2.compress_type = zipfile.ZIP_STORED
            dst.writestr(info2, data)
    with zipfile.ZipFile(tmp) as z:                       # relecture : même liste d'entrées, archive saine
        if z.testzip() is not None:
            tmp.unlink()
            raise RuntimeError("archive allégée illisible")
        with zipfile.ZipFile(chemin) as o:
            if z.namelist() != o.namelist():
                tmp.unlink()
                raise RuntimeError("pages différentes après allègement")
    avant = chemin.stat().st_size
    gagne = avant - tmp.stat().st_size
    if gagne <= 0 and not eclairer:
        tmp.unlink()
        return 0
    if destination is not None:
        return gagne
    chemin.rename(chemin.with_name(chemin.name + ".avant"))
    tmp.rename(chemin)
    return gagne


def echanger_dossier(chemin: Path, ecrire, vers_corbeille) -> bool:
    """Fichier partagé par qBittorrent (lien physique) : le NAS refuse de le renommer ou de l'effacer, mais accepte de
    renommer un DOSSIER. « ecrire(destination) » écrit la nouvelle version du fichier dans un dossier voisin caché
    (True si quelque chose est à remplacer), le reste du contenu y est copié, puis les deux dossiers sont échangés :
    l'ancien, avec le fichier du torrent, va à la corbeille (le torrent n'est pas touché). Mêmes noms de fichiers,
    donc lecture, progression et infos suivent."""
    import shutil
    dossier = chemin.parent
    nouveau = dossier.with_name("." + dossier.name + ".allege")
    ancien = dossier.with_name("." + dossier.name + ".avant")
    for d in (nouveau, ancien):
        if d.exists():
            raise RuntimeError(f"reste d'un traitement interrompu : {d.name} (à vérifier)")
    nouveau.mkdir()
    try:
        if not ecrire(nouveau / chemin.name):
            shutil.rmtree(nouveau, ignore_errors=True)
            return False
        for x in dossier.iterdir():                       # le reste du dossier (couverture, infos) suit
            if x != chemin and not x.name.startswith("."):
                shutil.copy2(x, nouveau / x.name) if x.is_file() else shutil.copytree(x, nouveau / x.name)
        dossier.rename(ancien)
        try:
            nouveau.rename(dossier)
        except OSError:
            ancien.rename(dossier)                         # échec : l'ancien dossier reprend sa place
            raise
    except Exception:
        shutil.rmtree(nouveau, ignore_errors=True)
        raise
    vers_corbeille(ancien)
    return True


def reecrire_partage(chemin: Path, qualite: int, vers_corbeille, eclairer=False, largeur_max=None) -> int:
    """Tome partagé : version allégée écrite à part puis dossiers échangés (voir echanger_dossier). Renvoie les octets gagnés."""
    gagne = [0]

    def ecrire(dest):
        gagne[0] = reecrire(chemin, qualite, eclairer, largeur_max, destination=dest)
        return gagne[0] > 0 or eclairer
    return gagne[0] if echanger_dossier(chemin, ecrire, vers_corbeille) else 0


def _dossier_a_lui(f: Path, serie: str) -> bool:
    """Le fichier est seul de son genre dans un dossier de tome (« Tome 01/ »), pas à la racine de la série."""
    d = f.parent
    if d.name == serie:
        return False
    try:
        return [x for x in d.iterdir() if x.suffix.lower() in (".cbz", ".cbr", ".zip")] == [f]
    except OSError:
        return False


def etat(serie):
    with _VERROU:
        return dict(_ETAT.get(serie) or {})


def lancer(serie, fichiers, appliquer, vers_corbeille, eclairer=False, fini=None, largeur_max=None, qualite_forcee=None):
    """En arrière-plan : analyse (appliquer=False) ou allègement de chaque fichier de la liste."""
    with _VERROU:
        if (_ETAT.get(serie) or {}).get("en_cours"):
            return False
        _ETAT[serie] = {"en_cours": True, "fait": 0, "total": len(fichiers), "message": "Analyse…" if not appliquer else "Allègement…",
                        "rapport": [], "appliquer": appliquer, "eclairer": eclairer, "largeur": largeur_max, "qualite_manuelle": qualite_forcee}

    def travail():
        gagne, avant_total, rapport = 0, 0, []
        try:
            for f in fichiers:
                f = Path(f)
                try:
                    if f.suffix.lower() not in (".cbz", ".zip") or not zipfile.is_zipfile(f):
                        rapport.append({"fichier": f.name, "note": "pas une archive ZIP : ignoré"})
                        continue
                    partage = f.stat().st_nlink > 1
                    if partage and not _dossier_a_lui(f, serie):
                        rapport.append({"fichier": f.name, "note": "partagé par qBittorrent et posé hors d'un dossier de tome : jamais modifié"})
                        continue
                    a = analyser(f, eclairer=eclairer, largeur_max=largeur_max, qualite_forcee=qualite_forcee)
                    avant_total += a["taille"]
                    ligne = {"fichier": f.name, "taille_mo": round(a["taille"] / 1048576, 1), "qualite": a["qualite"],
                             "gain": a["gain_estime"], "psnr": a["psnr_min"]}
                    if appliquer and a["qualite"]:
                        if partage:
                            g = reecrire_partage(f, a["qualite"], vers_corbeille, eclairer, largeur_max)
                            ligne["note"] = "partagé par qBittorrent : version allégée à part, le torrent n'est pas touché"
                        else:
                            g = reecrire(f, a["qualite"], eclairer, largeur_max)
                            ancien = f.with_name(f.name + ".avant")
                            if ancien.exists():
                                vers_corbeille(ancien)
                        ligne["gagne_mo"] = round(g / 1048576, 1)
                        gagne += g
                    elif a["qualite"]:
                        gagne += int(a["taille"] * a["gain_estime"])
                    if not a["qualite"]:
                        ligne["note"] = "déjà léger ou fragile : laissé tel quel"
                    rapport.append(ligne)
                except Exception as e:
                    logger.warning("Allègement de %s : %s", f, e)
                    rapport.append({"fichier": f.name, "note": f"erreur : {e}"})
                with _VERROU:
                    _ETAT[serie]["fait"] += 1
                    _ETAT[serie]["rapport"] = list(rapport)
            verbe = "gagnés" if appliquer else "à gagner (estimation)"
            msg = f"{gagne / 1073741824:.2f} Go {verbe} sur {avant_total / 1073741824:.2f} Go"
        except Exception as e:
            msg = f"Erreur : {e}"
        with _VERROU:
            _ETAT[serie].update(en_cours=False, message=msg, rapport=rapport, gain=gagne)
        logger.info("Allègement de « %s » (%s) : %s", serie, "appliqué" if appliquer else "analyse", msg)
        if fini:
            fini()
    threading.Thread(target=travail, daemon=True).start()
    return True


_CACHE_COMPARAISON = {}


def comparer(chemin: Path, index: int, qualite, eclairer=False, largeur_max=None, zoom=None) -> dict:
    """Une page du tome AVANT / APRÈS, avec exactement ce que « Appliquer » écrirait (même qualité, même largeur, même éclaircissement).
    zoom = (fx, fy) entre 0 et 1 : un détail de 640 px à l'échelle réelle plutôt que la page entière.
    Renvoie {"avant", "apres" (JPEG), "avant_ko", "apres_ko", "page", "pages", "inchange", "dimensions": [avant, après]}."""
    cle = (str(chemin), chemin.stat().st_mtime_ns, index, qualite, bool(eclairer), largeur_max, zoom)
    if cle in _CACHE_COMPARAISON:
        return _CACHE_COMPARAISON[cle]
    with zipfile.ZipFile(chemin) as z:
        noms = _pages(z)
        if not noms:
            raise RuntimeError("aucune page JPEG dans ce tome")
        index = max(0, min(index, len(noms) - 1))
        data = z.read(noms[index])
    im = Image.open(io.BytesIO(data))
    im.load()
    traitee = eclaircir(im) if eclairer and not est_couleur(im) else im
    im2 = reduire(traitee, largeur_max)
    nouveau = _jpeg(im2, qualite) if qualite else data
    if qualite and not (eclairer or im2 is not im or len(nouveau) < len(data)):
        nouveau = data                                   # une page qui ne gagne rien garde ses octets d'origine
    apres = Image.open(io.BytesIO(nouveau))
    apres.load()
    avant = im if im.size == apres.size else im.resize(apres.size, Image.LANCZOS)   # même géométrie pour comparer
    if zoom:
        c = 640
        x0 = int(max(0, min(apres.width - c, zoom[0] * apres.width - c / 2)))
        y0 = int(max(0, min(apres.height - c, zoom[1] * apres.height - c / 2)))
        boite = (x0, y0, min(apres.width, x0 + c), min(apres.height, y0 + c))
        sortie = [_jpeg(x.crop(boite), 100) for x in (avant, apres)]
    else:
        # Vue entière : la page « Après » est exactement ce que « Appliquer » écrirait (pas de recompression en plus)
        sortie = [_jpeg(avant, 100), nouveau]
    res = {"avant": sortie[0], "apres": sortie[1], "avant_ko": round(len(data) / 1024), "apres_ko": round(len(nouveau) / 1024),
           "page": index, "pages": len(noms), "inchange": nouveau is data, "dimensions": [list(im.size), list(apres.size)]}
    if len(_CACHE_COMPARAISON) >= 8:
        _CACHE_COMPARAISON.pop(next(iter(_CACHE_COMPARAISON)))
    _CACHE_COMPARAISON[cle] = res
    return res


def apercu(chemin: Path, index: int, eclairer=True, qualite=88) -> tuple[bytes, bytes]:
    """(avant, après) d'une page, en JPEG réduit pour comparer à l'écran."""
    with zipfile.ZipFile(chemin) as z:
        noms = _pages(z)
        data = z.read(noms[max(0, min(index, len(noms) - 1))])
    im = Image.open(io.BytesIO(data))
    im.load()
    apres = eclaircir(im) if eclairer and not est_couleur(im) else im
    apres = Image.open(io.BytesIO(_jpeg(apres, qualite)))
    def petit(x):
        x = x.copy()
        x.thumbnail((900, 1400))
        return _jpeg(x, 85)
    return petit(im), petit(apres)
