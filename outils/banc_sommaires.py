"""Banc d'essai de la lecture des sommaires (sommaire.py) : mesure ce que trouve le lecteur, et en combien de temps, sur de vrais tomes.

Rien n'est jamais écrit dans la bibliothèque ni dans les infos des séries : tout va dans data/banc-sommaires/ (jamais sur GitHub).

    venv/bin/python outils/banc_sommaires.py preparer            # liste des tomes de référence + copie de leurs pages de sommaire
    venv/bin/python outils/banc_sommaires.py lancer NOM [-p 6]   # lit chaque tome avec le code actuel → resultats-NOM.jsonl
    venv/bin/python outils/banc_sommaires.py bilan NOM [AVANT]   # scores par catégorie (et comparaison avec une lecture AVANT)
    venv/bin/python outils/banc_sommaires.py pages               # test rapide : les pages de sommaire gardées, sans le reste du tome

Références : les tomes validés à la main (« valide ») et saisis à la main (« manuel ») font foi ; « ok », « estime » et « vide » sont des
lectures automatiques tirées au hasard (au plus 3 par série) pour voir ce qui gagne ou se perd. Les lectures OCR sont gardées dans
memo.sqlite (même image, mêmes réglages = même texte) : relancer après une modification ne relit que ce qui a changé ; le temps
« à froid » compte quand même chaque lecture à son coût réel.
"""
import argparse
import collections
import json
import multiprocessing as mp
import os
import random
import sqlite3
import sys
import time
from pathlib import Path

RACINE = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(RACINE))
DOSSIER = RACINE / "data" / "banc-sommaires"


class Memo:
    """Mémoire durable des lectures OCR pour sommaire.MEMO_DISQUE ; compte le temps gagné (coût d'origine des lectures retrouvées)."""
    def __init__(self, f):
        self.c = sqlite3.connect(str(f), timeout=60, isolation_level=None)
        self.c.execute("PRAGMA journal_mode=WAL")
        self.c.execute("CREATE TABLE IF NOT EXISTS memo (cle TEXT PRIMARY KEY, valeur TEXT, cout REAL)")
        self.debut, self.gagne, self.reel = {}, 0.0, 0.0

    def get(self, cle):
        r = self.c.execute("SELECT valeur, cout FROM memo WHERE cle=?", (cle,)).fetchone()
        if r is None:
            self.debut[cle] = time.time()
            return None
        self.gagne += r[1] or 0
        return r[0]

    def set(self, cle, valeur):
        cout = time.time() - self.debut.pop(cle, time.time())
        self.reel += cout
        for _ in range(5):
            try:
                self.c.execute("INSERT OR REPLACE INTO memo VALUES (?,?,?)", (cle, valeur, cout))
                return
            except sqlite3.OperationalError:
                time.sleep(1)


def _app():
    import logging
    logging.disable(logging.WARNING)
    import app
    return app


def preparer(args):
    """Liste des tomes de référence (data/banc-sommaires/manifeste.json) et copie de leurs pages de sommaire (pages/)."""
    import glob
    app = _app()
    import archives
    random.seed(26)
    sommaires = {}
    for f in glob.glob(str(app.MANGA_DIR) + "/*/.mouflanga-infos.json"):
        try:
            sommaires[os.path.basename(os.path.dirname(f))] = json.load(open(f, encoding="utf-8")).get("sommaires") or {}
        except (OSError, ValueError):
            continue
    cats = collections.defaultdict(list)
    for s, som in sommaires.items():
        for t, x in som.items():
            ch = x.get("chapitres") or []
            avec_images = bool(ch) and all(c.get("image") is not None for c in ch)
            if x.get("valide_le"):
                if avec_images:
                    cats["valide"].append((s, t))
            elif x.get("manuel") or x.get("saisie"):
                if avec_images:
                    cats["manuel"].append((s, t))
            elif not ch:
                cats["vide"].append((s, t))
            elif any(c.get("estimee") for c in ch):
                cats["estime"].append((s, t))
            else:
                cats["ok"].append((s, t))

    def tirage(liste, n, par=3):
        random.shuffle(liste)
        vus, out = collections.Counter(), []
        for s, t in liste:
            if vus[s] < par:
                out.append((s, t))
                vus[s] += 1
            if len(out) >= n:
                break
        return out
    choix = [("valide", x) for x in cats["valide"]] + [("manuel", x) for x in cats["manuel"]] + \
        [(c, x) for c, n in (("ok", 60), ("estime", 40), ("vide", 50)) for x in tirage(cats[c], n)]
    pages_dir = DOSSIER / "pages"
    pages_dir.mkdir(parents=True, exist_ok=True)
    out = []
    for cat, (s, t) in choix:
        e = next((e for e in app._entrees(app._scan().get(s) or []) if e.get("tome") is not None
                  and float(e["tome"]) == float(t) and e.get("key") == e.get("path")), None)
        if not e:
            continue
        chemin = app.MANGA_DIR / e["path"]
        try:
            noms = archives.pages(chemin)
        except Exception:
            continue
        x = sommaires[s].get(t) or {}
        prec = (sommaires[s].get(str(int(float(t)) - 1)) or {}).get("chapitres") or []
        nums_prec = [c["num"] for c in prec if c.get("num") is not None]
        ligne = {"cat": cat, "serie": s, "tome": t, "chemin": str(chemin), "nb_pages": len(noms),
                 "numeros": app._numeros_fiables(s, int(float(t))), "suite_de": max(nums_prec) if nums_prec else None,
                 "attendu": [{k: c.get(k) for k in ("num", "image", "page", "estimee")} for c in x.get("chapitres") or []],
                 "page_sommaire": x.get("page_sommaire"), "source": x.get("source", "")}
        ps = x.get("page_sommaire")
        if cat in ("valide", "manuel") and isinstance(ps, int) and 0 <= ps < len(noms):
            gardees = []
            for i in (ps, ps + 1):
                if i < len(noms):
                    f = pages_dir / f"{s}-{t}-{i}.jpg".replace("/", "_")
                    if not f.exists():
                        f.write_bytes(archives.read_page(chemin, i)[0])
                    gardees.append(f.name)
            ligne["pages_sommaire"] = gardees
        out.append(ligne)
    (DOSSIER / "manifeste.json").write_text(json.dumps(out, ensure_ascii=False), encoding="utf-8")
    print(dict(collections.Counter(x["cat"] for x in out)), "→", DOSSIER / "manifeste.json")


def _init_travailleur():
    import logging
    logging.disable(logging.CRITICAL)
    global sommaire, archives, MEMO
    import archives
    import sommaire
    MEMO = Memo(DOSSIER / "memo.sqlite")
    sommaire.MEMO_DISQUE = MEMO
    sommaire._memo_lire = MEMO.get          # toutes les lectures retrouvées passent par le banc : leur coût est compté
    try:
        os.nice(12)
    except OSError:
        pass


def _un_tome(x):
    MEMO.gagne = MEMO.reel = 0.0
    t, err, r = time.time(), None, {}
    try:
        r = sommaire.lire(x["chemin"], lambda i, c=x["chemin"]: archives.read_page(c, i)[0], x["nb_pages"],
                          archives.pages(x["chemin"]), x["numeros"], x.get("suite_de"))
    except Exception as e:
        err = repr(e)[:200]
    mur = time.time() - t
    return {"cat": x["cat"], "serie": x["serie"], "tome": x["tome"], "erreur": err, "mur_s": round(mur, 1),
            "froid_s": round(mur + MEMO.gagne, 1), "source": r.get("source", ""), "page_sommaire": r.get("page_sommaire"),
            "chapitres": [{"num": c.get("num"), "image": c.get("image"), "page": c.get("page"), "estimee": bool(c.get("estimee"))}
                          for c in r.get("chapitres") or []]}


def lancer(args):
    manif = json.loads((DOSSIER / "manifeste.json").read_text(encoding="utf-8"))
    if args.categories:
        manif = [x for x in manif if x["cat"] in args.categories.split(",")]
    sortie = DOSSIER / f"resultats-{args.nom}.jsonl"
    faits = {(d["serie"], d["tome"]) for d in map(json.loads, sortie.open(encoding="utf-8"))} if sortie.exists() else set()
    manif = sorted((x for x in manif if (x["serie"], x["tome"]) not in faits), key=lambda x: -x["nb_pages"])
    with mp.Pool(args.processus, initializer=_init_travailleur) as pool, sortie.open("a", encoding="utf-8") as out:
        for k, r in enumerate(pool.imap_unordered(_un_tome, manif), 1):
            out.write(json.dumps(r, ensure_ascii=False) + "\n")
            out.flush()
            print(f"{k}/{len(manif)} {r['serie']} {r['tome']} : {len(r['chapitres'])} chapitre(s), {r['mur_s']} s", flush=True)


def _score(attendu, trouve):
    """(chapitres de référence, à la bonne image, à une image près, chapitres trouvés)."""
    ref = {float(c["num"]): c.get("image") for c in attendu if c.get("num") is not None and c.get("image") is not None}
    lu = {float(c["num"]): c.get("image") for c in trouve if c.get("num") is not None}
    exact = sum(1 for n, im in ref.items() if lu.get(n) == im)
    proche = sum(1 for n, im in ref.items() if lu.get(n) is not None and abs(lu[n] - im) <= 1)
    return len(ref), exact, proche, len(lu)


def bilan(args):
    manif = {(x["serie"], x["tome"]): x for x in json.loads((DOSSIER / "manifeste.json").read_text(encoding="utf-8"))}

    def charger(nom):
        f = Path(nom) if os.path.exists(nom) else DOSSIER / f"resultats-{nom}.jsonl"
        return {(d["serie"], d["tome"]): d for d in map(json.loads, f.open(encoding="utf-8"))}
    res = charger(args.nom)
    avant = charger(args.avant) if args.avant else {}
    communs = [k for k in res if not avant or k in avant]
    par = collections.defaultdict(lambda: collections.Counter())
    for k in communs:
        x, r = manif.get(k), res[k]
        if not x:
            continue
        c = par[x["cat"]]
        ref, exact, proche, nb = _score(x["attendu"], r["chapitres"])
        c["tomes"] += 1
        c["référence"] += ref
        c["exacts"] += exact
        c["à 1 près"] += proche
        c["trouvés"] += nb
        c["tomes avec chapitres"] += bool(r["chapitres"])
        c["estimés"] += sum(1 for ch in r["chapitres"] if ch.get("estimee"))
        c["secondes à froid"] += r["froid_s"]
        if avant and k in avant:
            a = _score(x["attendu"], avant[k]["chapitres"])
            if (exact, nb) < (a[1], a[3]) and (exact < a[1] or (not ref and nb < a[3])):
                print(f"  ↘ {x['cat']} {k[0]} {k[1]} : {a[1]}/{a[0]} exacts, {a[3]} trouvés  →  {exact}/{ref}, {nb}")
            elif (exact, nb) > (a[1], a[3]):
                print(f"  ↗ {x['cat']} {k[0]} {k[1]} : {a[1]}/{a[0]} exacts, {a[3]} trouvés  →  {exact}/{ref}, {nb}")
            c["secondes à froid avant"] += avant[k]["froid_s"]
    for cat, c in par.items():
        print(cat, dict(c))


def pages(args):
    """Test rapide : chaque page de sommaire gardée est relue seule (les deux lecteurs de texte) ; numéros et pages imprimées comparés."""
    import logging
    logging.disable(logging.WARNING)
    import sommaire
    manif = json.loads((DOSSIER / "manifeste.json").read_text(encoding="utf-8"))
    bons = total = 0
    for x in manif:
        if not x.get("pages_sommaire"):
            continue
        octets = [(DOSSIER / "pages" / n).read_bytes() for n in x["pages_sommaire"]]
        sommaire._LOCAL.memo = {}
        try:
            r = None
            for mode in ("tesseract", "moderne"):
                essai = sommaire._lire_avec(mode, False, x["serie"], lambda i: octets[i], len(octets), None, x["numeros"], placer=False)
                if r is None or sommaire._qualite(essai, x["numeros"]) > sommaire._qualite(r, x["numeros"]):
                    r = essai
        finally:
            sommaire._LOCAL.memo = None
        attendu = [(float(c["num"]), c.get("page")) for c in x["attendu"] if c.get("num") is not None]
        lu = [(float(c["num"]), c.get("page")) for c in r.get("chapitres") or []]
        total += 1
        bons += lu == attendu
        if lu != attendu:
            print(f"  ✗ {x['serie']} {x['tome']} : attendu {attendu[:4]}…, lu {lu[:4]}…")
    print(f"{bons}/{total} pages de sommaire lues exactement comme la référence")


if __name__ == "__main__":
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sp = p.add_subparsers(dest="action", required=True)
    sp.add_parser("preparer")
    l = sp.add_parser("lancer")
    l.add_argument("nom")
    l.add_argument("-p", "--processus", type=int, default=max(1, (os.cpu_count() or 2) - 2))
    l.add_argument("-c", "--categories", default="")
    b = sp.add_parser("bilan")
    b.add_argument("nom")
    b.add_argument("avant", nargs="?")
    sp.add_parser("pages")
    a = p.parse_args()
    {"preparer": preparer, "lancer": lancer, "bilan": bilan, "pages": pages}[a.action](a)
