"""Plage horaire des lectures de fond (sommaires relus, préparation automatique) : de minuit à 6 h, heure de Paris.

Hors de la plage, ces lectures attendent sans rien perdre et reprennent toutes seules. Les lectures lancées à la main
(fiche d'un tome, « Lire le sommaire », préparation demandée) ne passent jamais par ici : elles restent immédiates."""
import datetime
import time
import zoneinfo

HEURE_DEBUT = 0                                  # minuit
HEURE_FIN = 6                                    # 6 h du matin (exclu)
FUSEAU = zoneinfo.ZoneInfo("Europe/Paris")


def dans_la_plage(maintenant=None) -> bool:
    """Vrai si l'heure (à Paris) tombe entre HEURE_DEBUT et HEURE_FIN."""
    if maintenant is None:
        maintenant = datetime.datetime.now(FUSEAU)
    heure = maintenant.astimezone(FUSEAU).hour
    return HEURE_DEBUT <= heure < HEURE_FIN


def attendre_la_plage(pas=300, arret=None) -> bool:
    """Bloque tant qu'on est hors de la plage (vérifie toutes les `pas` secondes). Renvoie False si `arret()` devient vrai."""
    while not dans_la_plage():
        if arret and arret():
            return False
        time.sleep(pas)
    return True
