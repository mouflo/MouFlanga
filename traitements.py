"""
Ce qui a été fait sur chaque tome d'une série (« où j'en suis ») : doubles pages, pages parasites, image améliorée, noirs et blancs
uniformisés, allègement. Garde la mémoire de ce que l'appli a fait toute seule, et ce que la personne a noté à la main pour du travail
fait avant que l'appli ne s'en souvienne.

Le registre est rangé dans les infos de la série (`.mouflanga-infos.json`, clé « traitements »), un enregistrement par fichier de tome :
    {"Serie - Tome 05.cbz": {"taille": 96000000, "etapes": {"allegement": {"date": "2026-11-13", "detail": "…"}, "image": {…}}}}
La taille du fichier est la garantie que la mémoire parle bien de CE fichier : un tome remplacé par une autre édition a une autre
taille, ses anciennes marques ne comptent plus (à ±3 % près : écrire les infos dans le tome ou ajouter une page change sa taille de
quelques ko seulement). Quand l'appli réécrit elle-même un tome, `noter` garde les marques d'avant et enregistre la nouvelle taille.
Rien n'est lu ni écrit sur le disque ici : app.py donne et reprend le dictionnaire d'infos (module facile à tester).
"""
import time

TOLERANCE = 0.03                     # écart de taille toléré entre le moment où la marque a été posée et aujourd'hui
MANUELLES = ("doubles", "parasites", "image", "allegement")      # étapes qu'on peut cocher à la main (pas de preuve à lire dans le fichier)

# (clé, nom, icône, groupe) : ce que « où j'en suis » suit, dans l'ordre d'affichage
ETAPES = (
    ("resumes", "Résumés des tomes", "📝", "identite"),
    ("isbn", "ISBN des tomes", "🔢", "identite"),
    ("titres", "Titres des chapitres", "🔖", "identite"),
    ("liens", "Liens des chapitres", "🔗", "identite"),
    ("couvertures", "Couvertures des tomes", "🖼", "images"),
    ("doubles", "Pages simples et doubles", "📖", "images"),
    ("parasites", "Pages parasites", "🧹", "images"),
    ("image", "Image améliorée", "✨", "images"),
    ("uniformise", "Noirs et blancs uniformes", "🎨", "images"),
    ("allegement", "Allègement (compression)", "🗜", "images"),
    ("reecriture", "Infos écrites dans les fichiers", "📄", "fichiers"),
)
GROUPES = {"identite": "🔎 Identification", "images": "✨ Images", "fichiers": "📁 Fichiers"}


def proche(taille_notee, taille_actuelle) -> bool:
    """Le fichier a-t-il toujours la taille (à ±3 %) qu'il avait quand la marque a été posée ?"""
    try:
        a, b = int(taille_notee), int(taille_actuelle)
    except (TypeError, ValueError):
        return False
    if a <= 0 or b <= 0:
        return False
    return abs(a - b) <= max(a, b) * TOLERANCE


def lire(infos: dict, fichier: str, taille: int) -> dict:
    """{étape: marque} encore valables pour ce fichier ({} si le fichier a changé depuis ou n'a aucune marque)."""
    fiche = (infos.get("traitements") or {}).get(fichier)
    if not isinstance(fiche, dict) or not proche(fiche.get("taille"), taille):
        return {}
    return {k: dict(v) for k, v in (fiche.get("etapes") or {}).items() if isinstance(v, dict)}


def noter(infos: dict, fichier: str, avant: int, apres: int, faits: dict, date: str = None) -> None:
    """L'appli vient de travailler sur ce fichier (`avant` / `apres` : sa taille avant et après). `faits` : {étape: détails}.
    Les marques d'avant sont gardées si elles valaient pour le fichier d'avant (taille connue) ; sinon elles sont oubliées."""
    tout = infos.setdefault("traitements", {})
    ancien = tout.get(fichier) if isinstance(tout.get(fichier), dict) else {}
    etapes = dict(ancien.get("etapes") or {}) if proche(ancien.get("taille"), avant) else {}
    jour = date or time.strftime("%Y-%m-%d")
    for etape, detail in (faits or {}).items():
        marque = {"date": jour}
        marque.update(detail if isinstance(detail, dict) else {"detail": str(detail)})
        marque.pop("manuel", None)
        etapes[etape] = marque
    tout[fichier] = {"taille": int(apres), "etapes": etapes}


def marquer_main(infos: dict, fichier: str, taille: int, etape: str, fait: bool, date: str = None) -> bool:
    """Coche (ou décoche) à la main une étape pour un tome. Seules les étapes de `MANUELLES` se cochent, et une marque posée par
    l'appli ne se décoche pas (c'est un fait). Renvoie False quand rien n'a changé."""
    if etape not in MANUELLES:
        return False
    tout = infos.setdefault("traitements", {})
    fiche = tout.get(fichier) if isinstance(tout.get(fichier), dict) else {}
    valable = proche(fiche.get("taille"), taille)
    etapes = dict(fiche.get("etapes") or {}) if valable else {}
    if fait:
        if etape in etapes and not etapes[etape].get("manuel"):
            return False                                           # l'appli le sait déjà
        etapes[etape] = {"date": date or time.strftime("%Y-%m-%d"), "manuel": True}
    else:
        if etape not in etapes or not etapes[etape].get("manuel"):
            return False
        del etapes[etape]
    tout[fichier] = {"taille": int(taille), "etapes": etapes}
    return True


def oublier(infos: dict, fichier: str = None) -> None:
    """Efface la mémoire d'un fichier (un tome remplacé par une autre version), ou de toute la série."""
    if fichier is None:
        infos.pop("traitements", None)
    elif isinstance(infos.get("traitements"), dict):
        infos["traitements"].pop(fichier, None)


def resume_court(comptes: dict, total: int) -> str:
    """Une ligne discrète pour la fiche : « 📖 3/10 · 🎨 10/10 · 🗜 6/10 », seulement les étapes d'images déjà commencées."""
    morceaux = []
    for cle, nom, icone, groupe in ETAPES:
        if groupe == "images" and cle != "couvertures" and comptes.get(cle):
            morceaux.append(f"{icone} {comptes[cle]}/{total}")
    return " · ".join(morceaux)
