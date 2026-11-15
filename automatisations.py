"""🤖 Automatisations : ce que l'appli fait toute seule quand un tome arrive (réglage général, data/automatisations.json).

  actif        tout couper d'un coup (les demandes faites à la main passent toujours)
  chapitres    lire le sommaire du tome, nommer les chapitres
  confirmer    vérifier la place des chapitres avec les numéros de page imprimés (deux à trois minutes par tome)
  quand        "arrivee" : dès que le tome est rangé ; "nuit" : entre minuit et 6 h
  uniformiser  uniformiser les noirs et les blancs du nouveau tome, dans les séries où c'est demandé
  telegram     un message quand un tome a été traité

Rien d'autre ici : le travail est fait par pilote.py (file d'attente) et app.py (ce qu'on fait d'un tome).
"""
import json
import os
from pathlib import Path

DEFAUT = {"actif": True, "chapitres": True, "confirmer": True, "quand": "arrivee", "uniformiser": True, "telegram": True}
QUAND = ("arrivee", "nuit")


def valider(d) -> dict:
    """Réglage complet et propre d'après ce qu'on a lu ou reçu (une valeur absente ou fausse prend sa valeur par défaut)."""
    d = d if isinstance(d, dict) else {}
    out = {}
    for cle, defaut in DEFAUT.items():
        v = d.get(cle, defaut)
        if cle == "quand":
            out[cle] = v if v in QUAND else defaut
        else:
            out[cle] = bool(v) if isinstance(v, (bool, int)) else defaut
    return out


def lire(fichier) -> dict:
    try:
        return valider(json.loads(Path(fichier).read_text(encoding="utf-8")))
    except (OSError, ValueError):
        return dict(DEFAUT)


def ecrire(fichier, d) -> dict:
    propre = valider(d)
    fichier = Path(fichier)
    tmp = fichier.with_suffix(".tmp")
    tmp.write_text(json.dumps(propre, ensure_ascii=False, indent=2), encoding="utf-8")
    os.replace(tmp, fichier)
    return propre


def phrase(r) -> str:
    """Le réglage dit en une phrase (page des réglages, journal)."""
    if not r["actif"]:
        return "Automatisations coupées : rien n'est fait tout seul."
    quoi = []
    if r["chapitres"]:
        quoi.append("chapitres lus et nommés" + (", place vérifiée avec les numéros de page" if r["confirmer"] else ""))
    if r["uniformiser"]:
        quoi.append("noirs et blancs uniformisés dans les séries où tu l'as demandé")
    if not quoi:
        return "Automatisations allumées, mais aucun travail n'est choisi."
    return ("Dès qu'un tome arrive : " if r["quand"] == "arrivee" else "La nuit (minuit–6 h), pour chaque tome arrivé : ") + " ; ".join(quoi) + "."
