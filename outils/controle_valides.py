"""Contrôle des tomes validés à la main : leurs chapitres sont-ils à la page que disent les numéros imprimés ?

Rien n'est modifié, ni dans la bibliothèque ni dans les infos des séries : le résultat va dans data/controle-valides.json.
Le sommaire dit « chapitre 12, page 77 » ; on lit le numéro imprimé en bas de chaque page du tome et on regarde quelle image
porte la page 77 (une double page compte pour deux). Si la validation dit une autre image, le tome est signalé.

    nice -n 15 venv/bin/python outils/controle_valides.py [-p 3] [--serie NOM]
    venv/bin/python outils/controle_valides.py --bilan
"""
import argparse
import glob
import json
import multiprocessing as mp
import os
import resource
import sys
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
SORTIE = RACINE / "data" / "controle-valides.json"


def _init():
    import logging
    logging.disable(logging.WARNING)
    resource.setrlimit(resource.RLIMIT_AS, (3 * 1024 ** 3, 3 * 1024 ** 3))


def _un_tome(x):
    serie, tome, chemin, chapitres = x
    import archives
    import chapitres_auto as ca
    import sommaire
    try:
        nb = len(archives.pages(Path(chemin)))
        releve = ca.relever(lambda i: archives.read_page(Path(chemin), i)[0], nb, sommaire.numero_imprime)
    except Exception as ex:
        return {"serie": serie, "tome": tome, "erreur": str(ex)[:200]}
    ratios, folios = releve["ratios"], releve["folios"]
    ecarts, d_accord, sans_avis = [], 0, 0
    for c in chapitres:
        page, image = c.get("page"), c.get("image")
        if not isinstance(page, int) or image is None or c.get("special"):
            continue
        vote, n, total = ca.place_par_numeros(ratios, folios, page)
        if vote is None:
            sans_avis += 1
        elif vote == image:
            d_accord += 1
        elif n >= 3 and n >= 0.6 * total and ca.place_globale(ratios, folios, page) == vote:
            ecarts.append({"num": c.get("num"), "titre": c.get("titre") or "", "page": page, "validee": image, "numeros": vote,
                           "votes": n})
        else:
            sans_avis += 1
    return {"serie": serie, "tome": tome, "pages": nb, "numeros_lus": len(folios), "d_accord": d_accord, "sans_avis": sans_avis,
            "ecarts": ecarts}


def _lire():
    try:
        return json.loads(SORTIE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}


def bilan():
    d = _lire()
    tomes = list(d.values())
    faits = [t for t in tomes if "erreur" not in t]
    avec = [t for t in faits if t["ecarts"]]
    ch = sum(t["d_accord"] + len(t["ecarts"]) for t in faits)
    print(f"{len(faits)} tomes validés contrôlés ({len(tomes) - len(faits)} illisibles) ; {sum(t['d_accord'] for t in faits)} chapitres "
          f"d'accord avec les numéros de page sur {ch} jugés, {sum(t['sans_avis'] for t in faits)} sans avis (pas assez de numéros lus).")
    print(f"{len(avec)} tomes où la validation contredit les numéros de page :")
    for t in sorted(avec, key=lambda t: (t["serie"], float(t["tome"]))):
        print(f"  {t['serie']} tome {t['tome']} : " + " ; ".join(
            f"ch. {e['num']:g} (p. {e['page']}) validé image {e['validee'] + 1}, numéros → image {e['numeros'] + 1}" for e in t["ecarts"]))


def main():
    p = argparse.ArgumentParser()
    p.add_argument("-p", type=int, default=3)
    p.add_argument("--serie")
    p.add_argument("--bilan", action="store_true")
    a = p.parse_args()
    if a.bilan:
        return bilan()
    import logging
    logging.disable(logging.WARNING)
    import app
    deja = _lire()
    travail = []
    for f in sorted(glob.glob(str(app.MANGA_DIR) + "/*/.mouflanga-infos.json")):
        serie = os.path.basename(os.path.dirname(f))
        if a.serie and a.serie != serie:
            continue
        try:
            som = json.load(open(f, encoding="utf-8")).get("sommaires") or {}
        except (OSError, ValueError):
            continue
        valides = {t: x for t, x in som.items() if x.get("valide_le") and x.get("chapitres")}
        if not valides:
            continue
        fichiers = app._fichiers_des_tomes(serie)
        for t, x in valides.items():
            try:
                chemin = fichiers.get(int(float(t)))
            except ValueError:
                chemin = None
            if isinstance(chemin, (set, list, tuple)):
                chemin = next(iter(chemin), None) if len(chemin) == 1 else None
            if not chemin or f"{serie}|{t}" in deja:
                continue
            chemin = Path(chemin) if os.path.isabs(str(chemin)) else app.MANGA_DIR / str(chemin)
            travail.append((serie, t, str(chemin), x["chapitres"]))
    print(f"{len(travail)} tomes validés à contrôler ({len(deja)} déjà faits)", flush=True)
    with mp.Pool(a.p, initializer=_init) as pool:
        for k, r in enumerate(pool.imap_unordered(_un_tome, travail), 1):
            deja[f"{r['serie']}|{r['tome']}"] = r
            tmp = SORTIE.with_suffix(".tmp")
            tmp.write_text(json.dumps(deja, ensure_ascii=False, indent=1), encoding="utf-8")
            os.replace(tmp, SORTIE)
            print(f"{k}/{len(travail)} {r['serie']} T{r['tome']} : " + (r.get("erreur") or f"{len(r['ecarts'])} écart(s)"), flush=True)
    bilan()


if __name__ == "__main__":
    main()
