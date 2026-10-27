"""Banc d'essai de l'assemblage des doubles pages (optimiser.estimer_decalage et optimiser.reperer_paires) sur de vraies doubles pages.

Principe : de vraies doubles pages de la bibliothèque (images plus larges que hautes) sont coupées au milieu ; la moitié droite est
décalée vers le haut ou le bas d'un nombre de pixels connu, avec parfois un peu de largeur perdue au milieu et un liseré de scan. On
regarde si la détection retrouve le décalage (alignement), et si les deux moitiés se distinguent de deux pages simples voisines (paires).

Rien n'est jamais écrit dans la bibliothèque : tout va dans data/banc-alignement/ (jamais sur GitHub).

Mémoire : les images sont écrites une par une sur le disque (JPEG) et relues une par une, jamais gardées en liste ; le script s'interdit en plus
plus de 3 Go de mémoire. (Une première version gardait toutes les images pleine taille en mémoire : plusieurs Go, le conteneur a saturé le 27/10/2026.)

    venv/bin/python outils/banc_alignement.py preparer     # extrait ~90 vraies doubles et ~400 paires de pages voisines
    venv/bin/python outils/banc_alignement.py alignement   # exactitude du décalage trouvé, selon la confiance annoncée
    venv/bin/python outils/banc_alignement.py paires       # rappel / fausses alertes du repérage des paires

Dernier bilan (27/10/2026, 279 essais de jusqu'à 35 px de décalage) : annoncé « sûr » (42 % des essais) : juste à 3 px près dans 89 % des cas, jamais faux de plus de 6 px ;
« probable » (11 %) : 48 % ; « incertain » (47 %) : décalage laissé à 0. Ancienne méthode : 57 % à 3 px près mais 35 % d'erreurs de plus de 6 px, sans indication de confiance
(en comptant les incertains à 0 px, le taux global n'est pas meilleur : la moitié des jointures n'a pas de dessin qui la traverse). Paires : « possible » 50 % des vraies paires
pour 2,3 % de fausses alertes sur 300 paires de pages voisines ; « probable » 26 % pour 0,3 %.
"""
import io
import random
import resource
import sys
import zipfile
from pathlib import Path

import numpy as np
from PIL import Image

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
import archives  # noqa: E402
import optimiser  # noqa: E402

DOSSIER = RACINE / "data" / "banc-alignement"
BIBLIOTHEQUE = Path("/mnt/mouflosyno/MouFlanga")
LIMITE_MEMOIRE = 3 * 1024 ** 3          # le banc s'arrête (MemoryError) plutôt que de faire saturer le serveur
HAUTEUR_MAX = 2400                      # hauteur maximale des images gardées : assez pour les raies de scan, jamais de très gros scans en mémoire
MAX_DOUBLES, MAX_VOISINES = 90, 300


def fabriquer(im, decalage, perdu, liseré, rng):
    """(gauche, droite) comme deux scans séparés : la moitié droite descendue de `decalage` pixels (négatif : montée)."""
    a = np.asarray(im.convert("RGB"))
    h, w = a.shape[:2]
    m = w // 2
    g, d = a[:, : m - perdu // 2], a[:, m + (perdu + 1) // 2:]
    if decalage > 0:
        d = np.concatenate([np.repeat(d[:1], decalage, axis=0), d[: h - decalage]])
    elif decalage < 0:
        d = np.concatenate([d[-decalage:], np.repeat(d[-1:], -decalage, axis=0)])
    if liseré:
        g, d = g.copy(), d.copy()
        g[:, -liseré:] = rng.choice([255, 20])
        d[:, :liseré] = rng.choice([255, 20])
    return Image.fromarray(np.ascontiguousarray(g)), Image.fromarray(np.ascontiguousarray(d))


def _reduite(im, mode, hauteur=HAUTEUR_MAX):
    im = im.convert(mode)
    if im.height > hauteur:
        im = im.resize((round(im.width * hauteur / im.height), hauteur), Image.BOX)
    return im


def preparer():
    """Extrait des vraies doubles (tomes à peu de pages larges, donc de vraies illustrations) et des paires de pages simples voisines,
    chacune écrite sur le disque aussitôt (doubles/N.jpg, voisines/N-a.jpg et N-b.jpg)."""
    (DOSSIER / "doubles").mkdir(parents=True, exist_ok=True)
    (DOSSIER / "voisines").mkdir(parents=True, exist_ok=True)
    rng = random.Random(7)
    series = sorted(p for p in BIBLIOTHEQUE.iterdir() if p.is_dir())
    rng.shuffle(series)
    nd = nv = 0
    for s in series:
        if nd >= MAX_DOUBLES and nv >= MAX_VOISINES:
            break
        tomes = sorted(s.rglob("*.cbz"))
        if not tomes:
            continue
        f = tomes[len(tomes) // 2]
        try:
            noms = archives.pages(f)
            if len(noms) < 100:
                continue
            with zipfile.ZipFile(f) as z:
                larges = []
                for i, n in enumerate(noms):
                    with z.open(n) as fh:
                        try:
                            w, h = Image.open(io.BytesIO(fh.read(16384))).size
                        except Exception:
                            continue
                    if w >= h * 1.2 and h >= 1000:
                        larges.append(i)
                if 3 <= len(larges) <= 30 and nd < MAX_DOUBLES:
                    for i in rng.sample(larges, min(4, len(larges))):
                        im = Image.open(io.BytesIO(z.read(noms[i])))
                        _reduite(im, "L" if im.mode == "L" else "RGB").save(DOSSIER / "doubles" / f"{nd}.jpg", quality=95)
                        nd += 1
                for i in rng.sample(range(8, len(noms) - 8), 10):
                    if nv >= MAX_VOISINES:
                        break
                    try:
                        a, b = (Image.open(io.BytesIO(z.read(noms[j]))) for j in (i, i + 1))
                        if a.width > a.height * 1.1 or b.width > b.height * 1.1:
                            continue
                        _reduite(a, "L", 1600).save(DOSSIER / "voisines" / f"{nv}-a.jpg", quality=92)
                        _reduite(b, "L", 1600).save(DOSSIER / "voisines" / f"{nv}-b.jpg", quality=92)
                        nv += 1
                    except Exception:
                        continue
        except Exception as e:
            print("ignoré", s.name, e)
    print(nd, "doubles,", nv, "paires de pages voisines")


def _doubles():
    """Les doubles, une par une (jamais toutes en mémoire)."""
    fichiers = sorted((DOSSIER / "doubles").glob("*.jpg"), key=lambda p: int(p.stem))
    if not fichiers:
        sys.exit("Lance d'abord : banc_alignement.py preparer")
    for f in fichiers:
        with Image.open(f) as im:
            im.load()
            yield im.copy()


def _voisines():
    for a in sorted((DOSSIER / "voisines").glob("*-a.jpg"), key=lambda p: int(p.stem.split("-")[0])):
        with Image.open(a) as ia, Image.open(a.with_name(a.name.replace("-a.", "-b."))) as ib:
            ia.load(), ib.load()
            yield ia.copy(), ib.copy()


def alignement():
    rng = random.Random(3)
    res = []
    for im in _doubles():
        for _ in range(3):
            s = 0 if rng.random() < 0.1 else rng.randint(-35, 35)
            g, d = fabriquer(im, s, rng.choice([0, 0, 6, 14]), rng.choice([0, 0, 0, 3]), rng)
            g, d = optimiser._rogner_bord(g, "droite"), optimiser._rogner_bord(d, "gauche")
            e = optimiser.estimer_decalage(g, d)
            res.append((abs(e["dy"] + s), e["niveau"]))
    for niveau in ("sur", "probable", "incertain"):
        err = np.array([e for e, n in res if n == niveau])
        if len(err):
            print(f"{niveau:9s} {len(err) / len(res) * 100:3.0f} % des essais · ≤1 px {np.mean(err <= 1) * 100:3.0f} % · ≤3 px {np.mean(err <= 3) * 100:3.0f} % · >6 px {np.mean(err > 6) * 100:3.0f} %")


def paires():
    rng = random.Random(21)
    positifs, negatifs = [], []
    for im in _doubles():
        for _ in range(3):
            g, d = fabriquer(im, rng.randint(-35, 35), rng.choice([0, 0, 6, 14]), rng.choice([0, 0, 0, 3]), rng)
            positifs.append(optimiser.score_paire(optimiser._bandes_de_bord(g)[1], optimiser._bandes_de_bord(d)[0]))
    for a, b in _voisines():                                 # manga : la page i+1 est à gauche, la page i à droite
        negatifs.append(optimiser.score_paire(optimiser._bandes_de_bord(b)[1], optimiser._bandes_de_bord(a)[0]))
    ok = lambda s, seuil: s[0] >= seuil and s[1] >= 0.15 and s[2] >= 12
    for nom, seuil in (("possible", optimiser.SEUIL_PAIRE_POSSIBLE), ("probable", optimiser.SEUIL_PAIRE_PROBABLE)):
        print(f"{nom:9s} (≥ {seuil}) : {np.mean([ok(s, seuil) for s in positifs]) * 100:3.0f} % des vraies paires · "
              f"{np.mean([ok(s, seuil) for s in negatifs]) * 100:4.1f} % de fausses alertes sur {len(negatifs)} paires de pages voisines")


if __name__ == "__main__":
    resource.setrlimit(resource.RLIMIT_AS, (LIMITE_MEMOIRE, LIMITE_MEMOIRE))
    {"preparer": preparer, "alignement": alignement, "paires": paires}.get(sys.argv[1] if len(sys.argv) > 1 else "", lambda: print(__doc__))()
