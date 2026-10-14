"""Mentions d'édition spéciale d'un manga (une seule liste, partagée par tomes.py et edition.py).

Japon : kanzenban (« complète », grand format), aizōban (« collection chérie »), shinsōban (« nouvelle présentation »),
bunko (poche, plus de pages par tome), wideban (grand format). France / Europe : Perfect, Deluxe, Ultimate, Collector,
Colossale, Prestige, Maximum, Big, Intégrale, Omnibus, « 2 en 1 / 3 en 1 »…
Les mots courants (double, originale, prestige, big…) ne comptent qu'avec le mot « édition » devant (ou en fin de titre pour
double / originale) : « Big Order », « Master Keaton » ne sont pas des éditions.
"""
import re

FORTS = r"perfect|ultimate|deluxe|collector|kanzenban|aiz[oō]ban|shins[oō]ban|bunko|wideban|colossale|colossal|cultissime"
FAIBLES = (r"prestige|originale|double|triple|limit[ée]e|sp[ée]ciale|anniversaire|int[ée]grale|remasteris[ée]e|remastered|couleur|"
           r"ultime|maximum|big|essentielle|grand\s+format|r[ée]serve|num[ée]rot[ée]e|cartonn[ée]e|ma[iî]tre|master|coffret|"
           r"poche|reli[ée]e|anglaise|fran[cç]aise|japonaise")
MULTIPLE = r"\d{1,2}\s*(?:en|in)\s*1"

_CORPS = (rf"(?:[ée]dition\s+(?:de\s+)?)?(?:{FORTS})(?:\s+[ée]dition)?"
          rf"|[ée]dition\s+(?:de\s+)?(?:luxe|{FAIBLES})"
          rf"|de\s+luxe|{MULTIPLE}")

# n'importe où dans le nom
MENTION = re.compile(rf"\b(?:{_CORPS})\b", re.I)
# fin du nom d'un dossier : « Gantz : Perfect », « Gantz - Édition colossale », « Dragon Ball (Double) »
FIN = re.compile(rf"\s*[-–:,(]?\s*\b(?:{_CORPS}|originale|double)\b\s*\)?\s*$", re.I)
