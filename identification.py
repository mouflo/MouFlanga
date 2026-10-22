"""
Identifier une série : un seul parcours, le même quand on clique « 🔄 Relancer l'identification », quand on ouvre une fiche, quand
la préparation de fond passe ou qu'une série arrive.

Règles (elles tiennent en quatre lignes, et tout le reste du code les respecte) :
1. Une recherche a trois issues, jamais confondues : **trouvé**, **rien trouvé** (la source a répondu : elle ne connaît pas) et
   **panne** (la source n'a pas répondu : quota, réseau, refus). Seule la première écrit ; la deuxième espace les essais (1, 3,
   7, 30 jours) ; la troisième ne change rien et fixe l'heure du prochain essai.
2. Rien de ce qu'on savait n'est jamais effacé par une recherche : on complète, on corrige, on ne retire pas.
3. Chaque étape dit ce qu'elle a fait, en français, avec l'heure de la reprise quand elle attend un service.
4. Ce qui attend un service (Google Books et son quota du jour, Wikipédia qui demande de patienter…) est repris tout seul, plus
   tard (`a_reprendre`), sans que personne ait à y penser.

Les étapes dépendent les unes des autres dans cet ordre : statut (les titres d'AniList servent à chercher partout ailleurs), liste
française de Wikipédia, répartition des chapitres en tomes, fiche, puis ISBN et résumés des tomes (Wikipédia déjà lue, puis la BnF,
puis Google Books pour ce qui manque encore). La lecture des pages par OCR (ISBN) n'est qu'un dernier recours, décidé par l'appli
d'après `Bilan.extra`.
"""
import logging
import time
from collections import namedtuple

import bnf
import googlebooks
import notices
import reseau
import tomes

logger = logging.getLogger("mouflanga")

Bilan = namedtuple("Bilan", "etat detail prochain extra", defaults=({},))
ETAPES = [("statut", "Statut et résumé de la série (AniList, MangaDex, Wikipédia)"),
          ("liste_fr", "Titres, chapitres et ISBN des tomes en français (Wikipédia)"),
          ("tomes", "Répartition des chapitres en tomes (Wikipédia, MangaDex)"),
          ("fiche", "Fiche : auteurs, éditeurs, dates (AniList, Wikipédia, MangaUpdates)"),
          ("notices", "ISBN et résumés des tomes (Wikipédia, BnF, puis Google Books)")]
BNF_DUREE = 30 * 86400            # une série revue à la BnF au plus une fois par mois (sauf tome manquant ou nouveau)
CONTEXTE = lambda serie: {"tomes": set(), "edition": ""}      # remplacé par l'appli : tomes présents, édition spéciale


def heure_fr(ts: float) -> str:
    """« 9 h 05 » (heure de Paris), « demain 9 h 05 » ou « le 24/10 à 9 h 05 » pour un moment futur."""
    try:
        from zoneinfo import ZoneInfo
        from datetime import datetime
        zone = ZoneInfo("Europe/Paris")
        d, now = datetime.fromtimestamp(ts, zone), datetime.now(zone)
    except Exception:
        return time.strftime("%H:%M", time.localtime(ts))
    h = f"{d.hour} h {d.minute:02d}"
    if d.date() == now.date():
        return h
    if (d.date() - now.date()).days == 1:
        return f"demain {h}"
    return f"le {d.day:02d}/{d.month:02d} à {h}"


def _reprise(erreurs, defaut: float = 3600.0) -> float:
    """Heure du prochain essai quand un service n'a pas répondu : celle qu'il a donnée, sinon dans une heure."""
    t = max([e.reprise for e in erreurs if getattr(e, "reprise", None)] or [time.time() + defaut])
    return max(t, time.time() + 300)


def _qui(erreurs) -> str:
    return ", ".join(dict.fromkeys(e.service for e in erreurs)) or "un service"


def _panne(erreurs, ce_qui_reste: str) -> Bilan:
    reprise = _reprise(erreurs)
    return Bilan("panne", f"{_qui(erreurs)} n'a pas répondu : {ce_qui_reste} Nouvel essai {heure_fr(reprise)}.", reprise)


# ---------------------------------------------------------------- Les étapes (chacune rend un Bilan)

_RESUME_LANGUE = {"fr": "en français", "en": "en anglais"}
_STATUTS = {"FINISHED": "terminée", "RELEASING": "en cours", "HIATUS": "en pause", "CANCELLED": "arrêtée", "NOT_YET_RELEASED": "pas encore sortie"}


def _tome_max(serie: str):
    """Le plus grand tome qu'on a : il départage les fiches AniList voisines (« Kenichi » en 61 tomes n'est pas « Kenichi Tantei Chou » en 2)."""
    return max({int(t) for t in CONTEXTE(serie).get("tomes") or ()} or {0}) or None


def etape_statut(serie: str, forcer: bool = False) -> Bilan:
    st, etat, pannes = tomes.statut_officiel_bilan(serie, tome_max=_tome_max(serie), forcer=forcer)
    brut = (tomes._charger(serie) or {}).get("statut_officiel") or {}
    if etat == "panne":
        return _panne(pannes, "rien n'est modifié.")
    resume = " · résumé " + (_RESUME_LANGUE.get(brut.get("resume_langue"), "trouvé") if brut.get("resume") else "introuvable")
    if st:
        vol = f" · {st['volumes']} tome(s) annoncés" if st.get("volumes") else ""
        detail = f"{_STATUTS.get(st.get('statut'), st.get('statut') or '?')}{vol}{resume}"
    else:
        detail = "pas trouvée sur AniList" + resume
    if etat == "partiel":
        reprise = time.time() + 3600
        return Bilan("partiel", f"{detail} · un service du résumé n'a pas répondu, nouvel essai {heure_fr(reprise)}", reprise)
    if etat == "deja":
        return Bilan("deja", detail, None)
    return Bilan("ok" if st else "vide", detail, None if st else time.time() + tomes.attente_essai(brut.get("essais")))


def etape_liste_fr(serie: str, forcer: bool = False, tome_max=None) -> Bilan:
    titres, etat, pannes = tomes.titres_tomes_bilan(serie, forcer=forcer, tome_max=tome_max or _tome_max(serie))
    brut = (tomes._charger(serie) or {}).get("titres_tomes") or {}
    details = brut.get("details") or {}
    if etat == "panne":
        return _panne(pannes, "rien n'est modifié.")
    if not details and not titres:
        return Bilan("vide", "Wikipédia ne donne pas la liste des volumes de cette série", time.time() + tomes.attente_essai(brut.get("essais")))
    chap = sum(len(d.get("chapitres") or []) for d in details.values())
    isbn = sum(1 for d in details.values() if d.get("isbn"))
    detail = f"{len(details) or len(titres)} tome(s)" + (f", {chap} titre(s) de chapitres" if chap else "") + (f", {isbn} ISBN" if isbn else "")
    if etat == "partiel":
        reprise = _reprise(pannes)
        return Bilan("partiel", f"{detail} · {_qui(pannes)} n'a pas répondu partout, nouvel essai {heure_fr(reprise)}", reprise)
    return Bilan("deja" if etat == "deja" else "ok", detail, None)


def etape_tomes(serie: str, forcer: bool = False) -> Bilan:
    info, etat, pannes = tomes.chercher_bilan(serie, forcer=forcer)
    garde = tomes._charger(serie) or {}
    if etat == "panne":
        return _panne(pannes, "rien n'est modifié.")
    if not info:
        return Bilan("vide", "aucune liste de tomes trouvée (les tomes locaux restent affichés)", time.time() + tomes.attente_essai(garde.get("essais")))
    nb = len({t for t in (info.get("tomes") or {}).values() if t is not None})
    detail = f"{nb} tome(s), {len(info.get('tomes') or {})} chapitre(s) répartis · source : {info.get('source') or '?'}"
    if etat == "partiel":
        reprise = _reprise(pannes)
        return Bilan("partiel", f"{detail} (provisoire : {_qui(pannes)} n'a pas répondu, nouvel essai {heure_fr(reprise)})", reprise)
    return Bilan(etat, detail, None)


def etape_fiche(serie: str, forcer: bool = False) -> Bilan:
    f, etat, pannes = tomes.fiche_bilan(serie, forcer=forcer)
    sources = ", ".join(f.get("sources") or []) or "aucune"
    detail = f"sources qui ont répondu : {sources}" + (f" · éditeur : {f['editeur_fr']}" if f.get("editeur_fr") else "")
    if etat == "partiel":
        reprise = _reprise(pannes)
        return Bilan("partiel", f"{detail} · {_qui(pannes)} n'a pas répondu, nouvel essai {heure_fr(reprise)}", reprise)
    if etat == "vide":
        return Bilan("vide", "aucune source ne connaît cette série", time.time() + tomes.attente_essai(f.get("essais")))
    return Bilan(etat, detail, None)


def _compte(serie: str, voulus, champ: str) -> tuple:
    """(nombre de tomes qui ont ce champ, par source) sur les tomes voulus."""
    total, par_source = 0, {}
    if champ == "isbn":
        obs = notices.observations(serie)
        trouves = {t: notices.isbn_du_tome(obs.get(str(t)) or {}) for t in voulus}
        for t, (i, sources, _) in trouves.items():
            if i:
                total += 1
                par_source[sources[0]] = par_source.get(sources[0], 0) + 1
        return total, par_source
    for t, (texte, libelle) in notices.resumes_de(serie, voulus).items():
        if texte:
            total += 1
            cle = next((s for s in notices.SOURCES if notices.LIBELLES[s] == libelle), "?")
            par_source[cle] = par_source.get(cle, 0) + 1
    return total, par_source


def _ordre(par_source: dict) -> str:
    return ", ".join(f"{notices.LIBELLES.get(s, s)} {n}" for s, n in par_source.items())


def _etat_recherche(serie: str, source: str) -> dict:
    return ((tomes._charger(serie) or {}).get("recherches") or {}).get(source) or {}


def etape_notices(serie: str, forcer: bool = False) -> Bilan:
    """ISBN et résumés des tomes présents : Wikipédia (déjà lue à l'étape précédente), puis la BnF (catalogue officiel, sans quota),
    puis Google Books seulement pour ce qui manque encore (1 000 requêtes par jour).
    `extra['isbn_manquants']` : les tomes toujours sans ISBN ; `extra['attente']` : une source n'a pas encore répondu (Google et son
    quota du jour, par exemple) : l'appli attend avant de se rabattre, en dernier recours, sur l'ISBN imprimé dans le tome."""
    ctx = CONTEXTE(serie)
    voulus = {int(t) for t in ctx.get("tomes") or ()}
    edition = ctx.get("edition") or ""
    differente = bool(ctx.get("edition_differente"))

    def noter_edition(brut):
        if bool(brut.get("edition_differente")) == differente:
            return False
        brut["edition_differente"] = differente
    tomes.modifier(serie, noter_edition)
    if not voulus:
        return Bilan("deja", "aucun tome à renseigner", None, {"isbn_manquants": [], "attente": False})
    if differente and not edition:
        return Bilan("deja", "édition particulière (Perfect, Deluxe…) dont le nom n'est pas connu : les ISBN et résumés de l'édition "
                             "standard ne valent pas ici", None, {"isbn_manquants": sorted(voulus), "attente": False})
    fortes, faibles, autres = tomes.noms_de_recherche(serie)
    noms = [n for n in fortes if n]
    pannes = []

    def manque():
        return set(notices.manquants(serie, voulus, "isbn")) | set(notices.manquants(serie, voulus, "resume"))

    # 1. la BnF : jamais interrogée, ou il manque des choses et ça fait un mois, ou des tomes qu'elle n'a jamais vus sont arrivés
    bnf_avant = _etat_recherche(serie, "bnf")
    connus_bnf = {int(t) for t in (bnf_avant.get("tomes") or [])} | {int(t) for t in (bnf_avant.get("absents") or [])}
    if forcer or not bnf_avant or (manque() and (time.time() - bnf_avant.get("date", 0) > BNF_DUREE or voulus - connus_bnf)):
        try:
            trouves = bnf.chercher(noms, autres_series=autres, edition=edition, voulus=voulus)
            notices.enregistrer(serie, "bnf", trouves)

            def noter_bnf(brut):
                brut.setdefault("recherches", {})["bnf"] = {"date": time.time(), "tomes": sorted(trouves), "absents": sorted(voulus - set(trouves))}
            tomes.modifier(serie, noter_bnf)
        except reseau.Panne as e:
            pannes.append(e)
    # 2. Google Books : ce qu'il manque encore, une recherche de toute la série puis quelques tomes un à un
    google_utilisable = bool(googlebooks.cle())
    g_avant = _etat_recherche(serie, "google")
    essayes = {int(t): ts for t, ts in (g_avant.get("tomes_essayes") or {}).items()}
    a_chercher = {t for t in manque() if forcer or time.time() - essayes.get(t, 0) > 30 * 86400}
    if a_chercher and google_utilisable:
        try:
            isbn_tomes = {c: int(t) for t, c in notices.isbn_web(serie).items()}        # Google omet parfois le numéro : l'ISBN, connu, le dit
            trouves = googlebooks.chercher_serie(noms, edition=edition, autres=autres, voulus=a_chercher, isbn_tomes=isbn_tomes)
            notices.enregistrer(serie, "google", trouves)
            restants = a_chercher - set(trouves)
            for t in (sorted(restants)[:googlebooks.PAR_TOME_MAX] if trouves else []):       # Google ne connaît pas la série : inutile d'insister tome par tome
                n = googlebooks.chercher_tome(noms, t, edition=edition, autres=autres, isbn_tomes=isbn_tomes)
                if n:
                    notices.enregistrer(serie, "google", {t: n})
            for t in restants:
                essayes[t] = time.time()                              # cherché et pas trouvé : pas avant un mois

            def noter_google(brut):
                brut.setdefault("recherches", {})["google"] = {"date": time.time(), "tomes_essayes": {str(t): ts for t, ts in essayes.items()}}
            tomes.modifier(serie, noter_google)
        except reseau.Panne as e:                                      # quota atteint, Google injoignable…
            pannes.append(e)
    # Une série dont le résumé n'est qu'en anglais prend en français celui de son plus petit tome (qui la présente)
    if (((tomes._charger(serie) or {}).get("statut_officiel") or {}).get("resume_langue")) not in ("fr", None):
        premier = min(voulus)
        texte, libelle = notices.resume_du_tome(serie, premier)
        if texte and tomes.resume_de_serie_depuis_le_tome(serie, texte, "Tome 1"):
            logger.info("Résumé de la série %s : celui du tome %s en français (%s)", serie, premier, libelle)
    isbn_ok, isbn_src = _compte(serie, voulus, "isbn")
    resume_ok, resume_src = _compte(serie, voulus, "resume")
    detail = (f"ISBN {isbn_ok}/{len(voulus)}" + (f" ({_ordre(isbn_src)})" if isbn_src else "")
              + f" · résumés {resume_ok}/{len(voulus)}" + (f" ({_ordre(resume_src)})" if resume_src else ""))
    extra = {"isbn_manquants": sorted(set(notices.manquants(serie, voulus, "isbn"))), "attente": bool(pannes)}
    if pannes:
        reprise = _reprise(pannes)
        return Bilan("panne" if not (isbn_ok or resume_ok) else "partiel",
                     f"{detail} · {_qui(pannes)} n'a pas répondu : le reste viendra tout seul, nouvel essai {heure_fr(reprise)}", reprise, extra)
    if not google_utilisable and notices.manquants(serie, voulus, "resume"):
        detail += " · pas de clé Google Books (⚙️ Réglages) : seuls Wikipédia et la BnF donnent des résumés"
    if isbn_ok or resume_ok:
        return Bilan("ok", detail, None, extra)
    return Bilan("vide", detail, time.time() + tomes.attente_essai(None), extra)


_FONCTIONS = {"statut": etape_statut, "liste_fr": etape_liste_fr, "tomes": etape_tomes, "fiche": etape_fiche, "notices": etape_notices}


# ---------------------------------------------------------------- Le parcours

def noter(serie: str, bloc: str, b: Bilan):
    """Garde l'issue de l'étape (pour l'écran, les reprises et le Journal). N'écrit que si quelque chose a changé."""
    def appliquer(brut):
        r = brut.setdefault("recherches", {})
        avant = r.get(bloc) or {}
        nouveau = {"etat": b.etat, "detail": b.detail[:300]}
        if b.prochain:
            nouveau["prochain"] = b.prochain
        if b.etat == "deja" or (avant.get("etat"), avant.get("detail"), avant.get("prochain")) == (nouveau["etat"], nouveau["detail"], nouveau.get("prochain")):
            return False
        r[bloc] = {**{k: v for k, v in avant.items() if k not in ("etat", "detail", "prochain", "date")}, **nouveau, "date": time.time()}
    tomes.modifier(serie, appliquer)


def identifier(serie: str, *, forcer: bool = False, etapes=None, rapport=None) -> dict:
    """Fait toutes les étapes (ou celles demandées), dans l'ordre. `rapport(clé, état, détail)` est appelé au début (« en_cours ») et
    à la fin de chacune. Une étape qui plante ne bloque pas les suivantes. Rend {clé: Bilan}."""
    rapport = rapport or (lambda *a: None)
    bilans = {}
    for cle, _ in ETAPES:
        if etapes is not None and cle not in etapes:
            continue
        rapport(cle, "en_cours", "")
        try:
            b = _FONCTIONS[cle](serie, forcer)
        except Exception as e:                                     # une étape qui plante ne bloque pas les autres
            logger.warning("Identification de « %s » (%s) : %s %s", serie, cle, e.__class__.__name__, e)
            b = Bilan("echec", f"erreur : {e.__class__.__name__}", time.time() + 3600)
        noter(serie, cle, b)
        bilans[cle] = b
        rapport(cle, {"deja": "ok", "ok": "ok", "vide": "vide", "partiel": "reprise", "panne": "reprise"}.get(b.etat, "echec"), b.detail)
    return bilans


def a_reprendre(series, maintenant: float = None) -> list:
    """Parmi ces séries, celles qui ont une étape à refaire : un service n'avait pas répondu et son heure de reprise est passée, ou
    une recherche sans résultat est à retenter. Les plus en retard d'abord."""
    maintenant = maintenant or time.time()
    dues = []
    for s in series:
        rech = (tomes._charger(s) or {}).get("recherches") or {}
        retards = [r["prochain"] for r in rech.values() if r.get("prochain") and r["prochain"] <= maintenant
                   and r.get("etat") in ("panne", "partiel", "vide", "echec")]
        if retards:
            dues.append((min(retards), s))
    return [s for _, s in sorted(dues)]


def jamais_faites(series) -> list:
    """Séries dont aucune étape n'a jamais été notée (bibliothèque d'avant ce parcours, série qui vient d'arriver)."""
    return [s for s in series if not (tomes._charger(s) or {}).get("recherches")]
