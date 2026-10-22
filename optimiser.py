"""🪶 Alléger les tomes sans perte visible, et 🧼 éclaircir le papier des scans gris.

Alléger : pour chaque tome, quelques pages d'essai sont recompressées en JPEG à plusieurs qualités ; on garde la plus
basse dont l'écart avec l'original reste invisible (PSNR ≥ 42 dB sur chaque page d'essai) et qui fait gagner au moins
10 %. Une page qui ne gagne rien garde ses octets d'origine. Les noms et l'ordre des pages, chapitres.json et
ComicInfo.xml sont recopiés tels quels : le tome reste lisible et rangé pareil.
✨ Améliorer (vieux scans, seulement si on le demande) : réglages de 0 à 3 pour débruiter, adoucir les trames, blanchir
le papier (fond gris ou jauni, même inégal), renforcer les noirs, effacer les petites taches isolées, lisser les traits
en escalier et rendre plus net. Jamais sur une
page en couleur. Voir ameliorer().
L'original part à la corbeille (30 jours) seulement quand le nouveau fichier est écrit et relu ; un fichier encore
partagé par qBittorrent (lien physique) n'est jamais touché.
"""
import io
import logging
import threading
import time
import zipfile
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageOps

COMICINFO = "ComicInfo.xml"
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


# ✨ Amélioration des vieux scans : chaque réglage va de 0 (non) à 3 (fort), appliqué dans cet ordre
AMELIORATIONS = ("debruit", "trames", "papier", "noirs", "taches", "lisser", "nettete", "agrandir")


def reglages_amelioration(x) -> dict | None:
    """Réglages d'amélioration lus depuis la page : « 2,2,2,1,1,2,0 » (ordre d'AMELIORATIONS), un dict, ou True (ancien
    « 🧼 éclaircir » = papier moyen + noirs légers). None si rien n'est demandé."""
    if x is True:
        x = {"papier": 2, "noirs": 1}
    if isinstance(x, str):
        x = dict(zip(AMELIORATIONS, x.split(",")))
    if not isinstance(x, dict):
        return None
    r = {}
    for k in AMELIORATIONS:
        try:
            r[k] = max(0, min(3, int(x.get(k) or 0)))
        except (TypeError, ValueError):
            r[k] = 0
    return r if any(r.values()) else None


def _traits(g, seuil=25.0):
    """0 à 1 selon la présence d'un vrai trait (bord long et net), mesurée sur une version floue où les trames
    (petits points réguliers) ont disparu : ce masque protège les traits pendant que le reste est lissé."""
    f = cv2.GaussianBlur(g, (0, 0), 1.6)
    gx, gy = cv2.Sobel(f, cv2.CV_32F, 1, 0), cv2.Sobel(f, cv2.CV_32F, 0, 1)
    m = np.clip((np.sqrt(gx * gx + gy * gy) - seuil) / (2 * seuil), 0, 1)
    return cv2.GaussianBlur(m, (0, 0), 1.2)


def ameliorer(im: Image.Image, reglages) -> Image.Image:
    """Page noir et blanc d'un vieux scan, rendue plus propre (renvoyée en gris). Une page en couleur n'est pas touchée.
    « lisser » travaille sur la page doublée (il faut de la place pour arrondir) puis la ramène à sa taille : les bords
    restent lisses (anticrénelage) sans alourdir le fichier. « agrandir » garde la page doublée (petits scans de moins
    de 1700 px de haut seulement) : plus fin en zoomant, mais fichier bien plus lourd."""
    r = reglages_amelioration(reglages)
    if not r or est_couleur(im):
        return im
    g = np.asarray(im.convert("L"))
    h, w = g.shape
    echelle = max(1.0, (w * h) / 1.2e6)                   # les tailles suivent la résolution de la page
    if r["debruit"]:                                      # grain et petits carrés de la compression JPEG
        g = cv2.fastNlMeansDenoising(g, None, h=(0, 4, 7, 10)[r["debruit"]], templateWindowSize=7, searchWindowSize=21)
    if r["trames"]:                                       # aplats gris pointillés (trames) → gris uni, traits gardés
        flou = cv2.GaussianBlur(g, (0, 0), (0, 1.1, 1.6, 2.2)[r["trames"]] * echelle ** 0.5).astype(np.float32)
        m = _traits(g)
        g = (g * m + flou * (1 - m)).astype(np.uint8)
    if r["papier"]:
        # Fond de la page à grande échelle (l'encre retirée par une fermeture sur une version réduite), puis division :
        # le papier gris, jauni ou inégal devient blanc, un aplat gris reste gris. Le fond ne descend jamais sous 85 %
        # du papier de la page : une grande zone noire (cheveux) reste noire.
        pw, ph = max(1, w // 4), max(1, h // 4)
        k = max(7, (min(h, w) // 40) | 1)
        petit = cv2.resize(g, (pw, ph), interpolation=cv2.INTER_AREA)
        fond = cv2.morphologyEx(petit, cv2.MORPH_CLOSE, cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (k, k)))
        fond = cv2.resize(cv2.GaussianBlur(fond, (0, 0), k / 2), (w, h), interpolation=cv2.INTER_LINEAR).astype(np.float32)
        encre = min(float(np.percentile(g, 0.5)), 90.0)      # le noir le plus sombre de la page reste le noir
        fond = np.clip(fond, max(encre + 40, float(np.percentile(g, 90)) * 0.85), 255)
        blanc = (1, 0.975, 0.95, 0.91)[r["papier"]]          # fort : les gris les plus pâles deviennent blancs aussi
        g = np.clip((g.astype(np.float32) - encre) / ((fond - encre) * blanc) * 255, 0, 255).astype(np.uint8)
    if r["noirs"]:                                        # encre délavée : point noir relevé + légère courbe
        noir = (0, 25, 45, 65)[r["noirs"]]
        x = np.clip((np.arange(256, dtype=np.float32) - noir) / (255 - noir), 0, 1)
        g = cv2.LUT(g, (255 * x ** (1, 1.08, 1.15, 1.25)[r["noirs"]]).astype(np.uint8))
    if r["taches"]:
        # Poussières : petits points sombres SEULS au milieu du papier (aucune autre encre autour), bouchés avec le
        # fond voisin. Les points de suspension et les accents, collés à d'autres traits, restent.
        sombre = (g < 200).astype(np.uint8)
        nb, lab, st, _ = cv2.connectedComponentsWithStats(sombre, connectivity=8)
        rayon = int(4 + 2 * echelle)
        voisins = cv2.boxFilter(sombre.astype(np.float32), -1, (2 * rayon + 1,) * 2, normalize=False)
        maxi = np.zeros(nb, np.float32)
        np.maximum.at(maxi, lab.ravel(), voisins.ravel())
        aire = st[:, cv2.CC_STAT_AREA]
        isole = (aire <= (0, 3, 7, 14)[r["taches"]] * echelle) & (maxi <= aire + 0.5)
        isole[0] = False
        masque = isole[lab].astype(np.uint8) * 255
        if masque.any():
            g = cv2.inpaint(g, masque, 3, cv2.INPAINT_TELEA)
    if r["lisser"]:
        # Traits en escalier : page doublée si elle est petite, puis, sur les traits seulement, flou + courbe en S :
        # le bord redevient franc mais suit une courbe lisse. Les aplats et les gris ne sont pas touchés.
        g = cv2.resize(g, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
        m = _traits(g, 30.0)
        b = cv2.GaussianBlur(g, (0, 0), (0, 0.8, 1.2, 1.6)[r["lisser"]]).astype(np.float32) / 255
        pente = (0, 7, 9, 11)[r["lisser"]]
        bas, haut = 1 / (1 + np.exp(pente / 2)), 1 / (1 + np.exp(-pente / 2))
        s = (1 / (1 + np.exp(-(b - 0.5) * pente)) - bas) / (haut - bas) * 255
        g = np.clip(g * (1 - m) + s * m, 0, 255).astype(np.uint8)
        if not (r["agrandir"] and h < 1700):
            g = cv2.resize(g, (w, h), interpolation=cv2.INTER_AREA)
    elif r["agrandir"] and h < 1700:
        g = cv2.resize(g, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)
    if r["nettete"]:                                      # masque flou : traits plus francs
        a = (0, 0.5, 0.9, 1.4)[r["nettete"]]
        g = cv2.addWeighted(g, 1 + a, cv2.GaussianBlur(g, (0, 0), 1.0), -a, 0)
    return Image.fromarray(g, "L")


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
    eclairer = reglages_amelioration(eclairer)
    if eclairer:
        images = {n: ameliorer(im, eclairer) for n, im in images.items()}
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


def reecrire(chemin: Path, qualite: int, eclairer=False, largeur_max=None, destination: Path | None = None, comicinfo=None) -> int:
    """Écrit la version allégée (ou éclaircie) à côté, la relit, puis remplace. Renvoie le nombre d'octets gagnés.
    L'ancien fichier est renvoyé à l'appelant via un nom « .avant » (à mettre à la corbeille).
    Avec « destination » (fichier partagé par qBittorrent : le NAS refuse de le renommer), la version allégée est seulement
    écrite là, relue, et l'original n'est pas touché : l'appelant échange les dossiers.
    « comicinfo » : fonction (ancien ComicInfo.xml ou None) -> nouveau ComicInfo.xml, pour écrire les infos du tome dans la
    même passe ; le fichier est alors remplacé même sans gain. « qualite » vide : les images sont recopiées telles quelles."""
    eclairer = reglages_amelioration(eclairer)
    tmp = destination if destination is not None else chemin.with_name("." + chemin.name + ".allege")
    vu_comicinfo = False
    with zipfile.ZipFile(chemin) as src, zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        for info in src.infolist():
            data = src.read(info.filename)
            compression = zipfile.ZIP_STORED
            if qualite and Path(info.filename).suffix.lower() in _IMAGES:
                im = Image.open(io.BytesIO(data))
                im.load()
                traitee = ameliorer(im, eclairer) if eclairer else im
                im2 = reduire(traitee, largeur_max)
                nouveau = _jpeg(im2, qualite)
                if im2 is not im or len(nouveau) < len(data):
                    data = nouveau
            elif comicinfo is not None and info.filename == COMICINFO:
                data, vu_comicinfo, compression = comicinfo(data), True, zipfile.ZIP_DEFLATED
            info2 = zipfile.ZipInfo(info.filename, date_time=info.date_time)
            info2.compress_type = compression
            dst.writestr(info2, data)
        if comicinfo is not None and not vu_comicinfo:
            c = zipfile.ZipInfo(COMICINFO, date_time=time.localtime()[:6])
            c.compress_type = zipfile.ZIP_DEFLATED
            dst.writestr(c, comicinfo(None))
    with zipfile.ZipFile(tmp) as z:                       # relecture : mêmes pages (et le ComicInfo), archive saine
        if z.testzip() is not None:
            tmp.unlink()
            raise RuntimeError("archive allégée illisible")
        with zipfile.ZipFile(chemin) as o:
            attendu = o.namelist() + ([COMICINFO] if comicinfo is not None and not vu_comicinfo else [])
            if z.namelist() != attendu:
                tmp.unlink()
                raise RuntimeError("pages différentes après allègement")
    avant = chemin.stat().st_size
    gagne = avant - tmp.stat().st_size
    if gagne <= 0 and not eclairer and comicinfo is None:
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


def reecrire_partage(chemin: Path, qualite: int, vers_corbeille, eclairer=False, largeur_max=None, comicinfo=None) -> int:
    """Tome partagé : version allégée écrite à part puis dossiers échangés (voir echanger_dossier). Renvoie les octets gagnés."""
    gagne = [0]
    eclairer = reglages_amelioration(eclairer)

    def ecrire(dest):
        gagne[0] = reecrire(chemin, qualite, eclairer, largeur_max, destination=dest, comicinfo=comicinfo)
        return gagne[0] > 0 or bool(eclairer) or comicinfo is not None
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


def lancer(serie, fichiers, appliquer, vers_corbeille, eclairer=False, fini=None, largeur_max=None, qualite_forcee=None, infos_de=None):
    """En arrière-plan : analyse (appliquer=False) ou allègement de chaque fichier de la liste.
    « infos_de(fichier) » : fonction de ComicInfo (voir reecrire) ou None ; les infos du tome sont alors écrites dans la même passe."""
    eclairer = reglages_amelioration(eclairer)
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
                    comicinfo = infos_de(f) if (appliquer and infos_de) else None
                    if appliquer and (a["qualite"] or comicinfo):
                        if partage:
                            g = reecrire_partage(f, a["qualite"], vers_corbeille, eclairer, largeur_max, comicinfo)
                            ligne["note"] = "partagé par qBittorrent : version allégée à part, le torrent n'est pas touché"
                        else:
                            g = reecrire(f, a["qualite"], eclairer, largeur_max, comicinfo=comicinfo)
                            ancien = f.with_name(f.name + ".avant")
                            if ancien.exists():
                                vers_corbeille(ancien)
                        ligne["gagne_mo"] = round(g / 1048576, 1)
                        if comicinfo:
                            ligne["infos"] = True
                        gagne += g
                    elif a["qualite"]:
                        gagne += int(a["taille"] * a["gain_estime"])
                    if not a["qualite"]:
                        ligne["note"] = "déjà léger ou fragile : images laissées telles quelles" + (", infos écrites" if ligne.get("infos") else "")
                    rapport.append(ligne)
                except Exception as e:
                    logger.warning("Allègement de %s : %s", f, e)
                    rapport.append({"fichier": f.name, "note": f"erreur : {e}"})
                with _VERROU:
                    _ETAT[serie]["fait"] += 1
                    _ETAT[serie]["rapport"] = list(rapport)
            if gagne >= 0:
                verbe = "gagnés" if appliquer else "à gagner (estimation)"
                msg = f"{gagne / 1073741824:.2f} Go {verbe} sur {avant_total / 1073741824:.2f} Go"
            else:                                         # une amélioration peut alourdir les tomes : on le dit
                msg = (f"{-gagne / 1073741824:.2f} Go de plus" + ("" if appliquer else " (estimation)") +
                       f" sur {avant_total / 1073741824:.2f} Go (amélioration de l'image)")
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
    eclairer = reglages_amelioration(eclairer)
    cle = (str(chemin), chemin.stat().st_mtime_ns, index, qualite, tuple((eclairer or {}).values()), largeur_max, zoom)
    with _VERROU_COMPARAISON:            # la page demande avant, après et infos en même temps : un seul calcul, les autres attendent
        if cle not in _CACHE_COMPARAISON:
            res = _comparer(chemin, index, qualite, eclairer, largeur_max, zoom)
            if len(_CACHE_COMPARAISON) >= 8:
                _CACHE_COMPARAISON.pop(next(iter(_CACHE_COMPARAISON)))
            _CACHE_COMPARAISON[cle] = res
        return _CACHE_COMPARAISON[cle]


_VERROU_COMPARAISON = threading.Lock()


def _comparer(chemin, index, qualite, eclairer, largeur_max, zoom):
    with zipfile.ZipFile(chemin) as z:
        noms = _pages(z)
        if not noms:
            raise RuntimeError("aucune page JPEG dans ce tome")
        index = max(0, min(index, len(noms) - 1))
        data = z.read(noms[index])
    im = Image.open(io.BytesIO(data))
    im.load()
    couleur = bool(eclairer) and est_couleur(im)
    traitee = ameliorer(im, eclairer) if eclairer else im
    im2 = reduire(traitee, largeur_max)
    nouveau = _jpeg(im2, qualite) if qualite else data
    if qualite and not (im2 is not im or len(nouveau) < len(data)):
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
           "page": index, "pages": len(noms), "inchange": nouveau is data, "dimensions": [list(im.size), list(apres.size)],
           "ameliore": traitee is not im, "couleur": couleur}
    return res


# ---------------- 📖 Pages doubles : une image large contient souvent deux pages collées ----------------
import archives                         # ordre et numérotation des pages tels que le lecteur les voit
import xml.etree.ElementTree as ET

_RATIO_DOUBLE = 1.2                     # largeur / hauteur à partir de laquelle une image est une double page
_DOUBLES_CACHE = {}                     # (fichier, date, taille) → liste repérée
_COUPES_ETAT = {}                       # série → {"en_cours", "fait", "total", "message", "rapport"}
_COUPE_FORMATS = (".jpg", ".jpeg", ".png", ".webp")


def reperer_doubles(chemin: Path) -> list[dict]:
    """Doubles pages d'un tome (image plus large que haute) : [{"index", "nom"}], index = numéro de page du lecteur.
    Le repérage automatique ne sait pas distinguer une double normale d'une vraie double (une illustration) : c'est
    toi qui gardes les secondes entières dans la planche de vignettes."""
    chemin = Path(chemin)
    st = chemin.stat()
    cle = (str(chemin), st.st_mtime_ns, st.st_size)
    if cle in _DOUBLES_CACHE:
        return _DOUBLES_CACHE[cle]
    res = []
    with zipfile.ZipFile(chemin) as z:
        for i, nom in enumerate(archives.pages(chemin)):
            if Path(nom).suffix.lower() not in _COUPE_FORMATS:
                continue
            try:
                with Image.open(io.BytesIO(z.read(nom))) as im:
                    if im.width >= im.height * _RATIO_DOUBLE:
                        res.append({"index": i, "nom": nom})
            except Exception as e:
                logger.info("Page %s de %s ignorée pour les doubles : %s", nom, chemin.name, e)
    if len(_DOUBLES_CACHE) > 256:
        _DOUBLES_CACHE.clear()
    _DOUBLES_CACHE[cle] = res
    return res


def apercu_page(chemin: Path, index: int, largeur=300) -> bytes:
    """Une page du tome en JPEG réduit (vignette pour choisir les doubles pages)."""
    data, _ = archives.read_page(Path(chemin), index)
    im = Image.open(io.BytesIO(data))
    im.load()
    im = im.convert("RGB")
    im.thumbnail((largeur, largeur * 2))
    return _jpeg(im, 85)


def apercu_paire(chemin: Path, index: int, sens_manga=True, largeur=900) -> bytes:
    """La double page que donnerait l'assemblage des pages `index` et `index + 1`, calculée comme à l'assemblage (marges rognées,
    recalage), en JPEG réduit : c'est ce que montre la prévisualisation."""
    pages = []
    for n in (index, index + 1):
        data, _ = archives.read_page(Path(chemin), n)
        im = Image.open(io.BytesIO(data))
        im.load()
        pages.append(im)
    im = _coller(pages[0], pages[1], sens_manga)
    im.thumbnail((largeur, largeur))
    return _jpeg(im, 85)


def _moities(im, sens_manga):
    """Les deux moitiés d'une double page. Manga : la moitié droite se lit d'abord."""
    w, h = im.size
    m = w // 2
    gauche, droite = im.crop((0, 0, m, h)), im.crop((m, 0, w, h))
    return (droite, gauche) if sens_manga else (gauche, droite)


def _octets_page(im, nom):
    out = io.BytesIO()
    ext = Path(nom).suffix.lower()
    if ext == ".png":
        im.save(out, "PNG", optimize=True)
    elif ext == ".webp":
        im.save(out, "WEBP", quality=95)
    else:
        im.convert("RGB" if im.mode not in ("L", "RGB") else im.mode).save(out, "JPEG", quality=95, optimize=True, progressive=True)
    return out.getvalue()


def _comicinfo_maj(donnees: bytes, carte: dict, nb: int) -> bytes:
    """Numéros de page des signets (ComicInfo) suivis, et nombre total de pages mis à jour."""
    try:
        racine = ET.fromstring(donnees)
    except ET.ParseError:
        return donnees
    for p in racine.iter("Page"):
        try:
            ancien = int(p.get("Image", ""))
        except ValueError:
            continue
        if ancien in carte:
            p.set("Image", str(carte[ancien]))
    pc = racine.find("PageCount")
    if pc is not None:
        pc.text = str(nb)
    return ET.tostring(racine, encoding="utf-8", xml_declaration=True)


def couper(chemin: Path, indices, sens_manga=True, destination=None) -> dict:
    """Écrit le tome avec les pages « indices » (numéros du lecteur) coupées en deux. Même principe que reecrire : version
    à côté (ou « destination » pour un fichier partagé), relue, puis remplacée ; l'ancien part dans « avant » (corbeille).
    Renvoie {"carte": {ancien numéro: nouveau}, "pages_avant", "pages", "avant"}. Les noms des pages de chapitre
    (c0012.00-p003.jpg) sont renumérotés dans les chapitres touchés ; les autres moitiés s'appellent « 0008b.jpg »."""
    import tomes_cbz
    chemin = Path(chemin)
    ordre = archives.pages(chemin)
    coupees = {ordre[i] for i in indices if 0 <= i < len(ordre) and Path(ordre[i]).suffix.lower() in _COUPE_FORMATS}
    if not coupees:
        raise RuntimeError("aucune page double à couper")
    entrees = []                                  # [nom, octets, numéro ancien ou None, numéro de chapitre ou None, date]
    with zipfile.ZipFile(chemin) as z:
        for info in z.infolist():
            nom, data = info.filename, z.read(info.filename)
            num = tomes_cbz.num_page(nom)
            if nom not in coupees:
                entrees.append([nom, data, ordre.index(nom) if nom in ordre else None, num, info.date_time])
                continue
            a, b = _moities(Image.open(io.BytesIO(data)), sens_manga)
            a.load()
            stem, suf = Path(nom).stem, Path(nom).suffix
            entrees.append([nom, _octets_page(a, nom), ordre.index(nom), num, info.date_time])
            entrees.append([nom if num is not None else f"{stem}b{suf}", _octets_page(b, nom), None, num, info.date_time])
    touches = {tomes_cbz.num_page(n) for n in coupees} - {None}          # chapitres où une page a été coupée
    compte = {}
    for e in entrees:
        if e[3] is None or e[3] not in touches:
            continue
        compte[e[3]] = compte.get(e[3], 0) + 1
        e[0] = tomes_cbz.nom_page(e[3], compte[e[3]], ext=Path(e[0]).suffix.lstrip(".") or "jpg")
    nouvel_ordre = sorted((e[0] for e in entrees if e[0].lower().endswith(archives.IMAGE_EXT)
                           and "__MACOSX" not in e[0] and not Path(e[0]).name.startswith(".")), key=archives.natural_key)
    position = {nom: i for i, nom in enumerate(nouvel_ordre)}
    carte = {e[2]: position[e[0]] for e in entrees if e[2] is not None and e[0] in position}
    nb = len(nouvel_ordre)
    tmp = Path(destination) if destination is not None else chemin.with_name("." + chemin.name + ".coupe")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        for nom, data, _, _, date in entrees:
            if Path(nom).name == "ComicInfo.xml":
                data = _comicinfo_maj(data, carte, nb)
            info2 = zipfile.ZipInfo(nom, date_time=date)
            info2.compress_type = zipfile.ZIP_STORED
            dst.writestr(info2, data)
    with zipfile.ZipFile(tmp) as z:                   # relecture : archive saine, mêmes pages dans le même ordre
        if z.testzip() is not None:
            tmp.unlink()
            raise RuntimeError("archive coupée illisible")
        if archives._names(z) != nouvel_ordre:
            tmp.unlink()
            raise RuntimeError("pages différentes après coupe")
    res = {"carte": carte, "pages_avant": len(ordre), "pages": nb}
    if destination is not None:
        return res
    avant = chemin.with_name(chemin.name + ".avant")
    chemin.rename(avant)
    tmp.rename(chemin)
    res["avant"] = avant
    return res


def _coller(premiere, seconde, sens_manga):
    """Deux pages simples côte à côte en une double page. Manga : la première page à lire est à droite. Hauteurs différentes :
    la plus petite est agrandie à la hauteur de l'autre (proportions gardées)."""
    for im in (premiere, seconde):
        im.load()
    h = max(premiere.height, seconde.height)
    p, q = [im.convert("RGB").resize((max(1, round(im.width * h / im.height)), h), Image.LANCZOS) if im.height != h else im.convert("RGB")
            for im in (premiere, seconde)]
    gauche, droite = (q, p) if sens_manga else (p, q)
    gauche, droite = _rogner_bord(gauche, "droite"), _rogner_bord(droite, "gauche")
    decalage = _decalage_vertical(gauche, droite)
    out = Image.new("RGB", (gauche.width + droite.width, h), (255, 255, 255))
    out.paste(gauche, (0, 0))
    out.paste(droite, (gauche.width, decalage))
    return out


def _rogner_bord(im, cote, maxi=0.04):
    """Enlève, du côté qui touche l'autre page, les colonnes de bord du scan (liseré blanc ou noir, même dégradé) qui tranchent sur le dessin
    juste à côté : c'est ce qui fait la raie au milieu. Jamais plus de 4 % de la largeur pour le liseré, 8 % pour la marge blanche vide ; le dessin, lui, n'est pas touché."""
    moyennes = np.asarray(im.convert("L"), dtype=np.float32).mean(axis=0)
    ordre = moyennes[::-1] if cote == "droite" else moyennes
    limite = int(im.width * maxi)
    ref = float(np.median(ordre[8:40])) if len(ordre) > 40 else float(np.median(ordre))     # le dessin juste derrière le liseré
    n = 0
    while n < limite and n < len(ordre) and abs(ordre[n] - ref) > 12 and (ordre[n] > 170 or ordre[n] < 40):
        n += 1
    encre = (np.asarray(im.convert("L")) < 215).sum(axis=0)                  # traits par colonne
    encre = encre[::-1] if cote == "droite" else encre
    blanc_max = int(im.width * 0.08)
    while n < blanc_max and n < len(encre) and encre[n] <= max(2, im.height // 120) and (ordre[n] > 200 or ordre[n] < 40):   # marge blanche coupée par le scan
        n += 1
    if not n:
        return im
    return im.crop((0, 0, im.width - n, im.height)) if cote == "droite" else im.crop((n, 0, im.width, im.height))


def _decalage_vertical(gauche, droite, maxi=40):
    """De combien de pixels descendre (ou monter) la page de droite pour que le dessin continue de part et d'autre de la jointure.
    On compare les contours (traits, trames) des quelques colonnes qui touchent la jointure, débarrassés des grandes plages de gris : la
    corrélation la plus forte donne le décalage. 0 quand aucun décalage ne ressort nettement (page sans dessin au bord, par exemple)."""
    k, sigma = 4, 2.0
    h = min(gauche.height, droite.height)
    if h < 8 * maxi:
        return 0

    def contours(im, cote):
        a = np.asarray(im.convert("L"), dtype=np.float32)
        v = (a[:, -k:] if cote == "g" else a[:, :k]).mean(axis=1)
        v = v.reshape(-1, 1)
        return (cv2.GaussianBlur(v, (1, 0), sigma) - cv2.GaussianBlur(v, (1, 0), sigma * 5)).ravel()
    g, d = contours(gauche, "g"), contours(droite, "d")

    def correlation(dy):
        lo, hi = max(0, dy), min(h, h + dy)
        x, y = g[lo:hi] - g[lo:hi].mean(), d[lo - dy:hi - dy] - d[lo - dy:hi - dy].mean()
        return float((x * y).sum() / (np.sqrt((x * x).sum() * (y * y).sum()) + 1e-9))
    meilleur = max(range(-maxi, maxi + 1), key=lambda dy: (round(correlation(dy), 3), -abs(dy)))
    return meilleur if correlation(meilleur) >= 0.2 and correlation(meilleur) - correlation(0) >= 0.08 else 0


def carte_assemblage(avant: Path, apres: Path) -> dict:
    """Retrouve, en comparant l'archive d'origine et l'archive assemblée, où est passée chaque page : {ancien numéro: nouveau}.
    Les pages non collées sont reprises telles quelles (même somme de contrôle) ; une page qui ne retrouve pas la sienne est une double
    page née de deux pages d'origine. Sert à recaler après coup ce qui a été enregistré avant l'assemblage. Lève RuntimeError si les deux
    archives ne se correspondent pas."""
    def sommes(chemin):
        chemin = Path(chemin)
        with zipfile.ZipFile(chemin) as z:
            return [z.getinfo(n).CRC for n in archives.pages(chemin)]
    anciennes, nouvelles = sommes(avant), sommes(apres)
    carte, i = {}, 0
    for j, crc in enumerate(nouvelles):
        if i < len(anciennes) and anciennes[i] == crc:
            carte[i] = j
            i += 1
        elif i + 1 < len(anciennes):
            carte[i] = carte[i + 1] = j
            i += 2
        else:
            raise RuntimeError("les pages ne se correspondent pas")
    if i != len(anciennes):
        raise RuntimeError("les pages ne se correspondent pas")
    return carte


def assembler(chemin: Path, indices, sens_manga=True, destination=None) -> dict:
    """Inverse de `couper` : chaque page « i » des `indices` (numéros du lecteur) est collée à la page suivante pour faire une vraie
    double page. Même principe que `couper` (version à côté, relue, puis remplacée ; l'ancien part dans « avant »).
    Renvoie {"carte": {ancien numéro: nouveau}, "pages_avant", "pages", "avant"}."""
    import tomes_cbz
    chemin = Path(chemin)
    ordre = archives.pages(chemin)
    debuts = sorted({i for i in indices if 0 <= i < len(ordre) - 1 and Path(ordre[i]).suffix.lower() in _COUPE_FORMATS
                     and Path(ordre[i + 1]).suffix.lower() in _COUPE_FORMATS})
    if not debuts or any(b - a < 2 for a, b in zip(debuts, debuts[1:])):
        raise RuntimeError("aucune paire de pages à assembler (une page ne peut être dans deux paires)")
    suivantes = {ordre[i + 1]: ordre[i] for i in debuts}                 # page absorbée → page qui la reçoit
    premieres = {ordre[i] for i in debuts}
    entrees = []                                  # [nom, octets, numéro ancien ou None, numéro de chapitre ou None, date]
    with zipfile.ZipFile(chemin) as z:
        pages_lues = {}
        for nom in list(premieres) + list(suivantes):
            im = Image.open(io.BytesIO(z.read(nom)))
            im.load()
            pages_lues[nom] = im
        for info in z.infolist():
            nom = info.filename
            if nom in suivantes:
                continue
            data = z.read(nom)
            num = tomes_cbz.num_page(nom)
            if nom in premieres:
                seconde = ordre[ordre.index(nom) + 1]
                data = _octets_page(_coller(pages_lues[nom], pages_lues[seconde], sens_manga), nom)
            entrees.append([nom, data, ordre.index(nom) if nom in ordre else None, num, info.date_time])
    touches = {tomes_cbz.num_page(n) for n in premieres} - {None}        # chapitres où des pages ont été collées : renumérotés
    compte = {}
    for e in entrees:
        if e[3] is None or e[3] not in touches:
            continue
        compte[e[3]] = compte.get(e[3], 0) + 1
        e[0] = tomes_cbz.nom_page(e[3], compte[e[3]], ext=Path(e[0]).suffix.lstrip(".") or "jpg")
    nouvel_ordre = sorted((e[0] for e in entrees if e[0].lower().endswith(archives.IMAGE_EXT)
                           and "__MACOSX" not in e[0] and not Path(e[0]).name.startswith(".")), key=archives.natural_key)
    position = {nom: i for i, nom in enumerate(nouvel_ordre)}
    carte = {e[2]: position[e[0]] for e in entrees if e[2] is not None and e[0] in position}
    for i in debuts:                                                      # la page absorbée suit la double page qui la remplace
        carte[i + 1] = carte.get(i, 0)
    nb = len(nouvel_ordre)
    tmp = Path(destination) if destination is not None else chemin.with_name("." + chemin.name + ".assemble")
    with zipfile.ZipFile(tmp, "w", zipfile.ZIP_STORED) as dst:
        for nom, data, _, _, date in entrees:
            if Path(nom).name == "ComicInfo.xml":
                data = _comicinfo_maj(data, carte, nb)
            info2 = zipfile.ZipInfo(nom, date_time=date)
            info2.compress_type = zipfile.ZIP_STORED
            dst.writestr(info2, data)
    with zipfile.ZipFile(tmp) as z:                   # relecture : archive saine, une page de moins par paire
        if z.testzip() is not None:
            tmp.unlink()
            raise RuntimeError("archive assemblée illisible")
        if archives._names(z) != nouvel_ordre or len(nouvel_ordre) != len(ordre) - len(debuts):
            tmp.unlink()
            raise RuntimeError("pages différentes après assemblage")
    res = {"carte": carte, "pages_avant": len(ordre), "pages": nb}
    if destination is not None:
        return res
    avant = chemin.with_name(chemin.name + ".avant")
    chemin.rename(avant)
    tmp.rename(chemin)
    res["avant"] = avant
    return res


def lancer_coupes(serie, travaux, sens_manga, vers_corbeille, apres=None, operation=None) -> bool:
    """En arrière-plan : coupe les pages doubles de chaque tome (ou, avec operation=assembler, colle des paires de pages). travaux = [(chemin, {numéros de page})].
    apres(chemin, carte) est appelé après chaque tome (pour recaler la position de lecture). Un fichier partagé par
    qBittorrent suit la même règle que l'allègement : version à part, le torrent n'est pas touché."""
    with _VERROU:
        if (_COUPES_ETAT.get(serie) or {}).get("en_cours"):
            return False
        _COUPES_ETAT[serie] = {"en_cours": True, "fait": 0, "total": len(travaux), "message": "En cours…", "rapport": []}

    def travail():
        rapport, pages_coupees = [], 0
        try:
            for chemin, indices in travaux:
                chemin = Path(chemin)
                ligne = {"fichier": chemin.name}
                try:
                    if chemin.stat().st_nlink > 1 and not _dossier_a_lui(chemin, serie):
                        ligne["note"] = "partagé par qBittorrent hors d'un dossier de tome : jamais modifié"
                    elif chemin.stat().st_nlink > 1:
                        res = {}

                        def ecrire(dest):
                            res.update((operation or couper)(chemin, indices, sens_manga, destination=dest))
                            return True
                        echanger_dossier(chemin, ecrire, vers_corbeille)
                        ligne["note"] = "partagé par qBittorrent : nouvelle version à part, le torrent n'est pas touché"
                    else:
                        res = (operation or couper)(chemin, indices, sens_manga)
                        vers_corbeille(res.pop("avant"))
                    if res:
                        ligne.update(pages_avant=res["pages_avant"], pages=res["pages"])
                        pages_coupees += len(indices)
                        if apres:
                            apres(chemin, res["carte"])
                except Exception as e:
                    logger.warning("Coupe de %s : %s", chemin, e)
                    ligne["note"] = f"erreur : {e}"
                rapport.append(ligne)
                with _VERROU:
                    _COUPES_ETAT[serie]["fait"] += 1
                    _COUPES_ETAT[serie]["rapport"] = list(rapport)
            msg = (f"{pages_coupees} double(s) page(s) créée(s) dans {len(travaux)} tome(s)" if operation else
                   f"{pages_coupees} page(s) coupée(s) dans {len(travaux)} tome(s)")
        except Exception as e:
            msg = f"Erreur : {e}"
        with _VERROU:
            _COUPES_ETAT[serie].update(en_cours=False, message=msg, rapport=rapport)
        logger.info("Pages doubles de « %s » : %s", serie, msg)
    threading.Thread(target=travail, daemon=True).start()
    return True


def coupes_etat(serie):
    with _VERROU:
        return dict(_COUPES_ETAT.get(serie) or {})
