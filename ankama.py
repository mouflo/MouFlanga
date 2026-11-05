"""
Ankama Boutique (ankama-shop.com) : le catalogue de l'éditeur de Radiant, Dofus, Wakfu, Mutafukaz…

Chaque tome a sa page (ISBN dans `gtin8`/`gtin13`, résumé, nom). Le robots.txt du site interdit seulement les comptes, paniers,
tris et recherches : on ne lit que les pages de catégories (`/fr/<n>-<série>`, pagination `?p=`) et les pages produit, sans jamais
utiliser la recherche du site. Tout passe par `reseau` (rythme, pannes) : une panne lève `reseau.Panne`, jamais prise pour « rien trouvé ».
"""
import html
import json
import re
import unicodedata

import reseau

BASE = "https://www.ankama-shop.com"
PAGES_MAX = 8                       # pages de catégorie lues au plus


def _slug(texte: str) -> str:
    t = unicodedata.normalize("NFKD", texte or "").encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", "-", t).strip("-")


def categorie_de(nom: str):
    """Adresse de la catégorie du site qui porte le nom de la série (menu de la page d'accueil), ou None. Lève reseau.Panne."""
    slug = _slug(nom)
    if not slug:
        return None
    page = reseau.get(f"{BASE}/fr/", attendu="texte", memo=3600, service="ankama").texte
    for url, nom_cat in re.findall(r'href="(https://www\.ankama-shop\.com/fr/\d+-([a-z0-9-]+))"', page):
        if nom_cat == slug or nom_cat.startswith(slug + "-"):
            return url
    return None


def tomes_de_la_serie(nom: str) -> list[dict]:
    """[{tome, titre, url}] des tomes « <nom> Tome N » de la catégorie de la série (pas les coffrets, collectors, romans, spin-offs),
    ou [] si le site ne la connaît pas. Lève reseau.Panne."""
    cat = categorie_de(nom)
    if not cat:
        return []
    slug = _slug(nom)
    motif = re.compile(rf'href="(https://www\.ankama-shop\.com/fr/[^"/]+/\d+-{re.escape(slug)}-tome-(\d+)(?:-[a-z0-9-]+)?\.html)"')
    trouves, vus = {}, 0
    for p in range(1, PAGES_MAX + 1):
        page = reseau.get(cat, params={"p": p} if p > 1 else None, attendu="texte", memo=600, service="ankama").texte
        nouveaux = {int(n): u for u, n in motif.findall(page) if int(n) not in trouves}
        if not nouveaux and p > 1:
            break
        trouves.update(nouveaux)
    return [{"tome": n, "titre": f"{nom} Tome {n}", "url": u} for n, u in sorted(trouves.items())]


def _isbn_valide(code: str) -> bool:
    if not re.fullmatch(r"97[89]\d{10}", code or ""):
        return False
    return (10 - sum(int(c) * (1 if i % 2 == 0 else 3) for i, c in enumerate(code[:12]))) % 10 == int(code[12])


def lire_tome(url: str) -> dict:
    """{isbn, resume, titre} d'après la page d'un tome. Lève reseau.Panne."""
    page = reseau.get(url, attendu="texte", memo=600, service="ankama").texte
    obs = {}
    for m in re.finditer(r'<script[^>]*application/ld\+json[^>]*>(.*?)</script>', page, re.S):
        try:
            d = json.loads(m.group(1), strict=False)
        except ValueError:
            continue
        if isinstance(d, dict) and d.get("@type") == "Product" and d.get("description"):
            code = str(d.get("gtin13") or d.get("gtin8") or "")
            if _isbn_valide(code):
                obs["isbn"] = code
            texte = re.sub(r"\s+", " ", html.unescape(re.sub(r"<[^>]+>", " ", html.unescape(d["description"])))).strip()
            if len(texte) >= 40:
                obs["resume"] = texte
            obs["titre"] = html.unescape(d.get("name") or "")
            break
    return obs


def chercher(noms: list[str], voulus=None) -> dict:
    """{tome: {isbn, resume, titre, editeur}} pour les tomes `voulus` (le premier nom que la boutique connaît). Lève reseau.Panne."""
    for nom in noms:
        liste = tomes_de_la_serie(nom)
        if not liste:
            continue
        out = {}
        for t in liste:
            if voulus and t["tome"] not in voulus:
                continue
            obs = lire_tome(t["url"])
            if obs.get("isbn") or obs.get("resume"):
                out[t["tome"]] = {**obs, "editeur": "Ankama"}
        return out
    return {}
