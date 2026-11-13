"""
« ✏️ Mon édition » : tout ce qui aide à reconnaître l'édition qu'on possède (Deluxe, Ultime, Édition originale…) au même endroit :
son nom, son nombre de tomes, la page de l'éditeur, et les ISBN que les tomes eux-mêmes portent.

Les ISBN viennent de ce que les tomes disent d'eux-mêmes : imprimés dans le tome (`isbn`, lus par l'appli ou saisis), ou écrits sur la page
du torrent d'où le tome est venu (C411, TR4KER… : « ISBN : 9782344060483 » dans la présentation). Ils servent de PREUVE : quand on donne la
page d'un éditeur, les ISBN des tomes doivent être ceux de cette édition, sinon on refuse (ce n'est pas la bonne).
Rien n'est écrit ici : app.py enregistre (edition.ecrire) ; ce module lit, compare et décide.
"""
import re

import ankama
import glenat

ISBN = re.compile(r"(?<![\d-])(97[89](?:[ -]?\d){10})(?![\d])")
ECHANTILLON = 3                    # tomes dont la page de l'éditeur est lue pour vérifier un lien (premier, dernier, un du milieu)


def isbn13_dans(texte: str) -> list:
    """Les ISBN-13 valides écrits dans un texte (« ISBN : 978-2-344-06048-3 », « 9782344060483 »), dans l'ordre, sans doublon."""
    vus = []
    for m in ISBN.finditer(texte or ""):
        code = re.sub(r"\D", "", m.group(1))
        if ankama._isbn_valide(code) and code not in vus:
            vus.append(code)
    return vus


def isbn_des_tomes(infos: dict, pages: list) -> dict:
    """{tome: [{isbn, source}]} : les ISBN lus dans les tomes (`infos["isbn"]`) et ceux de la présentation des pages de torrents
    (`pages` : [{tomes: [8], presentation: "…"}] déjà lues par l'appli, jamais relues ici). Un tome sans ISBN n'apparaît pas."""
    out = {}

    def noter(tome, code, source):
        liste = out.setdefault(int(tome), [])
        if not any(x["isbn"] == code for x in liste):
            liste.append({"isbn": code, "source": source})

    for t, code in (infos.get("isbn") or {}).items():
        code = re.sub(r"\D", "", str(code))
        if str(t).isdigit() and ankama._isbn_valide(code):
            noter(t, code, "lu dans le tome")
    for p in pages or []:
        tomes_de_la_page = [int(t) for t in p.get("tomes") or [] if str(t).isdigit()]
        codes = isbn13_dans(p.get("presentation") or "")
        if len(tomes_de_la_page) == 1 and codes:                 # une page de plusieurs tomes ne dit pas quel ISBN va avec quel tome
            for code in codes[:1]:
                noter(tomes_de_la_page[0], code, f"page du torrent ({p.get('tracker') or 'tracker'})")
    return dict(sorted(out.items()))


def echantillon(isbn_par_tome: dict) -> list:
    """Quelques tomes qui ont un ISBN : le premier, le dernier et un du milieu."""
    t = sorted(isbn_par_tome)
    return sorted({t[0], t[-1], t[len(t) // 2]}) if t else []


def verifier_lien(lien: str, isbn_par_tome: dict) -> dict:
    """Lit la page d'éditeur donnée (+ quelques tomes de la même édition) et la confronte aux ISBN des tomes.
    {ok, edition, serie, tomes, concordent: [tomes], differents: {tome: (isbn du tome, isbn de l'éditeur)}, lus}.
    Lève glenat.PageIllisible (adresse refusée / page disparue) et reseau.Panne (l'éditeur ne répond pas)."""
    if not glenat.adresse(lien):
        raise glenat.PageIllisible("Cette adresse n'est pas lue pour l'instant : seule la page d'un tome sur glenat.com l'est "
                                   "(par exemple …/glenat-manga/rave-edition-originale-tome-01-9782344060414/).")
    premiere = glenat.lire_page(lien)
    if not premiere:
        raise glenat.PageIllisible("Glénat ne montre plus cette page : vérifie l'adresse.")
    # seulement les tomes que cette édition peut avoir : une série qui mêle deux éditions (tomes 1-12 d'une, 25-35 d'une autre) ne doit
    # pas être jugée sur les tomes de l'autre
    possibles = {t: x for t, x in isbn_par_tome.items() if t in premiere["voisins"]}
    voulus = echantillon(possibles)
    fiches = glenat.lire_edition(lien, voulus=set(voulus)) if voulus else {premiere["tome"]: premiere}
    concordent, differents = [], {}
    for t in voulus:
        f = fiches.get(t)
        if not f:
            continue
        codes = [x["isbn"] for x in possibles[t]]
        if f["isbn"] in codes or any(c in codes for c in f.get("autres_isbn") or []):
            concordent.append(t)
        else:
            differents[t] = (codes[0], f["isbn"])
    return {"ok": not differents, "edition": premiere["edition"], "serie": premiere["serie"], "titre": premiere["titre"],
            "pages": premiere["pages"], "concordent": concordent, "differents": differents, "lus": sorted(fiches)}


def a_retenir(corps: dict, avant: dict, verif: dict = None) -> dict:
    """Ce qu'il faut garder dans les infos de la série d'après le formulaire : {edition, volumes_attendus, volumes_manuel, edition_lien,
    edition_editeur}, les champs laissés vides étant oubliés (retour à la détection automatique). Le nom laissé vide prend celui de
    l'éditeur quand une page a été lue (« Édition originale »)."""
    nom = re.sub(r"\s+", " ", str(corps.get("nom") or "")).strip()
    if not nom and verif and verif.get("edition"):
        nom = verif["edition"]
    brut = str(corps.get("volumes") or "").strip()
    lien = glenat.adresse(corps.get("lien") or "").get("url", "")
    out = {}
    if nom:
        out["edition"] = nom
    if brut:
        out["volumes_attendus"], out["volumes_manuel"] = int(brut), True
    if lien:
        out["edition_lien"], out["edition_editeur"] = lien, "Glénat"
    return out


def valider(corps: dict):
    """Message d'erreur si le formulaire est inutilisable, sinon None."""
    nom = str(corps.get("nom") or "")
    if len(nom) > 80 or re.search(r"[\x00-\x1f<>]", nom):
        return "Le nom de l'édition doit tenir en une ligne de 80 caractères au plus."
    brut = str(corps.get("volumes") or "").strip()
    if brut and (not brut.isdigit() or not 1 <= int(brut) <= 999):
        return "Indique un nombre de tomes (ex. 18), ou laisse vide si tu ne le sais pas."
    lien = str(corps.get("lien") or "").strip()
    if len(lien) > 300:
        return "Cette adresse est trop longue."
    return None
