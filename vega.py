"""
Vega Livres (vega-livres.fr) : le catalogue d'un éditeur français (collections VEGA, K-Factory, LYR, ALPHA).

Utile surtout pour les séries qu'aucune base ne connaît (un manga français comme « Arena » n'est ni sur AniList ni sur Wikipédia) :
chaque tome a sa page avec l'ISBN (dans l'adresse), le résumé, les auteurs, la collection et la date de parution.
Le robots.txt du site autorise le catalogue (seul /api est interdit) ; tout passe par `reseau` (rythme, pannes) et rien n'est
lu hors des pages `/catalog` du site. Une panne lève `reseau.Panne` (jamais prise pour « rien trouvé »).
"""
import html
import json
import re
from urllib.parse import quote

import correspondance
import reseau

BASE = "https://www.vega-livres.fr"
_ISBN = re.compile(r"/catalog/(97[89]\d{10})/")
_NUM = re.compile(r"(?:tome|t\.?)\s*0*(\d{1,3})\s*$", re.I)


def _blocs_json(page: str):
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page or "", re.S):
        try:
            yield json.loads(m.group(1))
        except ValueError:
            continue


def tomes_de_la_serie(nom: str) -> list[dict]:
    """[{tome, titre, isbn, url}] des livres du catalogue dont la série s'appelle exactement `nom` (filtre « Série » du site),
    ou [] si le catalogue ne la connaît pas. Lève reseau.Panne si le site n'a pas répondu."""
    rep = reseau.get(f"{BASE}/catalog?series={quote(nom)}", attendu="texte", memo=600, service="vega")
    out = []
    for bloc in _blocs_json(rep.texte):
        for el in ((bloc.get("mainEntity") or {}).get("itemListElement") or []) if isinstance(bloc, dict) else []:
            titre, url = html.unescape(el.get("name") or ""), el.get("url") or ""
            isbn = _ISBN.search(url)
            num = _NUM.search(titre)
            if isbn and num and url.startswith(BASE + "/catalog/") and correspondance.jetons(titre.rsplit(",", 1)[0]):
                out.append({"tome": int(num.group(1)), "titre": titre, "isbn": isbn.group(1), "url": url})
    # le filtre du site cherche par série : on ne garde que les livres dont le titre commence par le nom demandé
    simple = lambda t: re.sub(r"[^a-z0-9]+", " ", t.lower()).strip()
    sur = [t for t in out if simple(t["titre"]).startswith(simple(nom))]
    return sorted({t["tome"]: t for t in sur}.values(), key=lambda t: t["tome"])


def _texte(fragment: str) -> str:
    return re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", fragment or ""))).strip()


def lire_tome(url: str) -> dict:
    """{resume, auteurs, editeur, date} d'après la page d'un tome (ce qui manque reste absent). Lève reseau.Panne."""
    page = reseau.get(url, attendu="texte", memo=600, service="vega").texte
    obs = {}
    for bloc in _blocs_json(page):
        genre = bloc.get("@type") if isinstance(bloc, dict) else None
        if isinstance(bloc, dict) and (genre == "Book" or (isinstance(genre, list) and "Book" in genre)):
            auteurs = bloc.get("author") or []
            auteurs = [auteurs] if isinstance(auteurs, dict) else auteurs
            obs["auteurs"] = ", ".join(a.get("name", "") for a in auteurs if isinstance(a, dict) and a.get("name"))
            obs["editeur"] = "Vega Livres" + (f" ({bloc['category']})" if isinstance(bloc.get("category"), str) else "")
            obs["date"] = str(bloc.get("releaseDate") or "")
            obs["resume"] = _texte(bloc.get("description") or "")
    if not obs.get("resume"):                                    # repli : le paragraphe de présentation de la page
        m = re.search(r'<meta (?:name|property)="(?:og:)?description" content="([^"]{60,})"', page)
        if m:
            obs["resume"] = _texte(m.group(1))
    return {k: v for k, v in obs.items() if v}


def chercher(noms: list[str], voulus=None) -> dict:
    """{tome: {isbn, resume, titre, editeur, date}} pour les tomes `voulus` de la série (le premier nom que le catalogue connaît).
    Lève reseau.Panne si le site n'a pas répondu."""
    for nom in noms:
        liste = tomes_de_la_serie(nom)
        if not liste:
            continue
        out = {}
        for t in liste:
            if voulus and t["tome"] not in voulus:
                continue
            obs = lire_tome(t["url"])
            out[t["tome"]] = {"isbn": t["isbn"], "titre": t["titre"], **{k: obs[k] for k in ("resume", "editeur", "date") if k in obs}}
        return out
    return {}
