"""
Lire la présentation d'un torrent : ce que l'équipe qui l'a mis en ligne a écrit sur la page du tracker (HTML, BBCode, Markdown ou
texte brut) et dans son NFO. Toujours les mêmes deux étapes, pour tous les trackers et pour les NFO des archives :

1. `en_texte` : n'importe quel format → du texte simple, une ligne par ligne, sans images ni mise en forme ;
2. `analyser` : le texte → ce qu'il dit (titre, auteur, éditeur, parution, genre, langue, format, pages, résolution, qualité, source,
   ISBN, résumé), reconnu à ses étiquettes (« Auteur : », « Éditeur (FR) ........: », « Résumé : », « Tome 01 -- ISBN : 978… »).

Rien ici n'accède à Internet ni aux fichiers. Le texte vient d'un inconnu : il n'est jamais affiché comme du HTML, et seules les
étiquettes connues sont lues (une ligne « machin : truc » quelconque ne devient pas une information).
"""
import html
import re
from html.parser import HTMLParser

import correspondance

MAX_TEXTE = 30000

# ---------------------------------------------------------------- 1. Du format d'origine au texte simple


class _LecteurHtml(HTMLParser):
    BLOCS = {"p", "div", "ul", "ol", "tr", "table", "h1", "h2", "h3", "h4", "h5", "h6", "blockquote", "pre", "section", "article", "hr"}
    IGNORES = {"script", "style", "head", "title", "noscript", "svg", "template", "iframe"}

    def __init__(self):
        super().__init__(convert_charrefs=True)
        self.morceaux, self.ignore, self.pre = [], 0, 0

    def handle_starttag(self, tag, attrs):
        if tag in self.IGNORES:
            self.ignore += 1
        elif tag == "br":
            self.morceaux.append("\n")
        elif tag == "li":
            self.morceaux.append("\n• ")
        elif tag in self.BLOCS:
            self.morceaux.append("\n")
            if tag == "pre":
                self.pre += 1

    def handle_endtag(self, tag):
        if tag in self.IGNORES:
            self.ignore = max(0, self.ignore - 1)
        elif tag in self.BLOCS or tag == "li":
            self.morceaux.append("\n")
            if tag == "pre":
                self.pre = max(0, self.pre - 1)

    def handle_data(self, data):
        if not self.ignore:
            self.morceaux.append(data if self.pre else re.sub(r"\s+", " ", data))


def _html_en_texte(source: str) -> str:
    lecteur = _LecteurHtml()
    try:
        lecteur.feed(source)
        lecteur.close()
    except Exception:                                          # HTML cassé : on garde ce qui a été lu
        pass
    return "".join(lecteur.morceaux)


_BALISES_BBCODE = (r"b|i|u|s|strike|center|left|right|justify|size|color|font|quote|spoiler|code|list|table|tr|td|th|sub|sup|align|indent|"
                   r"h[1-6]|pre|nfo|mod|hide|box|youtube|video|flash")


def _bbcode_en_texte(source: str) -> str:
    """BBCode des trackers. Seules les balises connues sont retirées : « [CBZ] », « [Digital-1500] » ou « [@équipe] » dans un nom
    de fichier restent du texte."""
    t = re.sub(r"\[img[^\]]*\].*?\[/img\]", "", source, flags=re.S | re.I)
    t = re.sub(r"\[url=[^\]]*\](.*?)\[/url\]", r"\1", t, flags=re.S | re.I)
    t = re.sub(r"\[url\](.*?)\[/url\]", r"\1", t, flags=re.S | re.I)
    t = re.sub(r"\[\*\]", "\n• ", t)
    t = re.sub(r"\[(?:br|hr)\s*/?\]", "\n", t, flags=re.I)
    return re.sub(r"\[/?(?:%s)(?:[= ][^\]]*)?\]" % _BALISES_BBCODE, "", t, flags=re.I)


def _markdown_en_texte(source: str) -> str:
    t = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", source)
    t = re.sub(r"\[([^\]]+)\]\([^)]*\)", r"\1", t)
    t = re.sub(r"^\s{0,3}#{1,6}\s*", "", t, flags=re.M)
    t = re.sub(r"(\*\*|__|`)", "", t)
    t = re.sub(r"^\s{0,3}>\s?", "", t, flags=re.M)
    return re.sub(r"^\s*[-*+]\s+", "• ", t, flags=re.M)


def format_probable(source: str) -> str:
    if re.search(r"<(?:p|br|div|span|b|i|strong|em|ul|li|img|a|font|pre)\b", source, re.I):
        return "html"
    if re.search(r"\[(?:b|i|u|center|img|url|size|color|quote|list|spoiler)(?:[= ][^\]]*)?\]", source, re.I):
        return "bbcode"
    if re.search(r"(?m)^\s{0,3}#{1,6}\s|\*\*[^*\n]+\*\*|!?\[[^\]]+\]\([^)]+\)", source):
        return "markdown"
    return "texte"


def en_texte(source, format: str = "") -> str:
    """Texte simple d'une présentation (format : html, bbcode, markdown, texte ; deviné s'il n'est pas donné)."""
    source = str(source or "")
    if not source.strip():
        return ""
    source = source.replace("\r\n", "\n").replace("\r", "\n")
    format = (format or "").lower()
    if format not in ("html", "bbcode", "markdown", "texte"):
        format = format_probable(source)          # « standard » (C411) et tout format inconnu : on regarde le contenu
    if format == "html":
        t = _html_en_texte(source)
    elif format == "bbcode":
        t = html.unescape(_bbcode_en_texte(source))
    elif format == "markdown":
        t = _markdown_en_texte(source)
    else:
        t = source
    if format in ("markdown", "texte") and re.search(r"&(?:#\d+|#x[0-9a-f]+|[a-z]{2,8});", t, re.I):
        t = html.unescape(t)                                   # « Oga &amp; Cie » : certains trackers rangent le texte échappé
    t = t.replace("\u00a0", " ").replace("\u200b", "").replace("\ufeff", "")
    t = "\n".join(ligne.rstrip() for ligne in t.split("\n"))
    t = re.sub(r"\n{3,}", "\n\n", t).strip()
    return t[:MAX_TEXTE]


# ---------------------------------------------------------------- 2. Du texte à ce qu'il dit

# Étiquettes reconnues : (clé, motif sur l'étiquette réduite par correspondance.simple : « Éditeur (FR) » → « editeur fr »)
_ETIQUETTES = (
    ("titre_original", r"titre original|titre vo|original title|nom original"),
    ("titre_fr", r"titre francais|titre fr|titre vf"),
    ("titre", r"titre|nom du manga|nom de la serie"),
    ("auteur", r"auteurs?(?: s)?|auteur dessinateur|auteur et dessinateur|auteur scenariste|scenariste|scenario|dessinateur|mangaka"),
    ("editeur", r"editeurs?(?: fr| vf| francais)?|maison d edition"),
    ("date", r"date de publication|date de parution|date de sortie|date sortie|parution|publie le|sortie"),
    ("annee", r"annee"),
    ("genre", r"genres?(?: s)?|categories|type(?: s)?|themes?(?: s)?"),
    ("langue", r"langues?|langue bd comics manga"),
    ("format", r"format|format fichier"),
    ("pages", r"nombre de pages|pages"),
    ("resolution", r"resolution|dimensions?|definition"),
    ("qualite", r"qualite"),
    ("source", r"source"),
    ("statut", r"statut|etat"),
    ("equipe", r"release team|team|equipe|release"),
    ("contenu", r"contenu"),
)
_MOTS_RESUME = r"synopsis|resume|description|presentation|histoire|pitch|sujet|resume de l histoire|quatrieme de couverture"
_LIGNE_ETIQUETTE = re.compile(r"^[\s\-*•·►▪▸>]*([^\W\d_][\w ()/'’&+\-]{0,38}?)[ .…_]*:[ \t]*(.*)$")
_LIGNE_TOME_ISBN = re.compile(r"(?:\btome|\bt|\bvol(?:ume)?\.?)\s*0*(\d{1,3})\b[^\n\d]{0,14}?(?:isbn\s*(?:-?13)?\s*:?\s*)?(97[89][\d\- ]{10,16})", re.I)
_ISBN_ETIQUETE = re.compile(r"\bisbn(?:[\s\-]*13)?[\s.…_]*:?[\s.…_]*(97[89][\d\- ]{10,16})", re.I)
_SEPARATEUR = re.compile(r"^[\s\-_=*~.#+<>|─-╿•·]{4,}$")
_FICHIER = re.compile(r"\.(?:cbz|cbr|zip|rar|7z|pdf|epub|nfo|jpe?g|png|webp)\s*$|^\[@", re.I)


def isbn13(c) -> str:
    """ISBN-13 sans tirets si la somme de contrôle est juste, sinon ""."""
    c = re.sub(r"\D", "", str(c or ""))[:13]
    if len(c) == 13 and c.startswith(("978", "979")) and (10 - sum(int(x) * (1 if k % 2 == 0 else 3) for k, x in enumerate(c[:12])) % 10) % 10 == int(c[12]):
        return c
    return ""


def _cle_etiquette(etiquette: str) -> str:
    s = correspondance.simple(etiquette)
    for cle, motif in _ETIQUETTES:
        if re.fullmatch(motif, s):
            return cle
    return "resume" if re.fullmatch(_MOTS_RESUME, s) else ""


def _est_separateur(ligne: str) -> bool:
    return bool(_SEPARATEUR.match(ligne))


def _est_intertitre(ligne: str) -> bool:
    """Ligne qui en ouvre une autre partie : « CONTENU », « Informations Importantes : », « Tome 01 (Scan) », « Liste des fichiers »."""
    s = ligne.strip(" *-•·►▪▸=#:")
    if not s or len(s) > 45 or len(s.split()) > 6:
        return False
    if re.match(r"(?i)tomes?\s*0*\d+\b", s) and not re.search(r"[.!?…]$", s):
        return True
    if ligne.rstrip().endswith(":"):
        return True
    lettres = [c for c in s if c.isalpha()]
    return bool(lettres) and all(c.isupper() for c in lettres) and len(lettres) >= 4


def _mots_francais(texte: str) -> tuple:
    mots = re.findall(r"[a-zàâçéèêëîïôûùüÿœ]+", re.sub(r"\b[ldjmnst]['’]", "le ", texte.lower()))
    fr = sum(m in _FR for m in mots)
    en = sum(m in _EN for m in mots)
    return fr, en


_FR = {"le", "la", "les", "des", "du", "de", "un", "une", "et", "est", "dans", "pour", "qui", "que", "ne", "pas", "se", "sur", "avec", "son",
       "sa", "ses", "au", "aux", "il", "elle", "ils", "ce", "cette", "mais", "ou", "où", "par", "plus", "en", "à"}
_EN = {"the", "and", "of", "to", "is", "in", "that", "it", "with", "for", "as", "his", "her", "was", "are", "from", "this", "by", "on", "at",
       "who", "but", "he", "she", "they", "their", "be", "has", "have"}


def langue_du_texte(texte: str) -> str:
    """« fr » ou « en » d'après les petits mots, "" si le texte est trop court pour savoir."""
    fr, en = _mots_francais(texte)
    if fr + en < 4:
        return ""
    return "en" if en > fr * 1.5 else "fr"


def _paragraphes(lignes: list) -> list:
    """Groupes de lignes séparés par des lignes vides ; chaque groupe est une liste de lignes."""
    out, cour = [], []
    for ligne in lignes:
        if ligne.strip():
            cour.append(ligne.strip())
        elif cour:
            out.append(cour)
            cour = []
    if cour:
        out.append(cour)
    return out


def _propre_resume(lignes: list) -> str:
    t = " ".join(x.strip(" •") for x in lignes if x.strip())
    t = re.sub(r"\s+", " ", t).strip()
    return t[:3000]


def _resume_sous_intertitre(lignes: list, debut: int) -> str:
    """Texte qui suit un intertitre « Résumé : » : jusqu'à la prochaine étiquette ou le prochain intertitre ; une ligne vide ne
    coupe pas tant que la suite est encore du texte."""
    morceau, i, vides = [], debut, 0
    while i < len(lignes):
        ligne = lignes[i].strip()
        if not ligne:
            vides += 1
            if vides > 2 or (morceau and vides > 1):
                break
        else:
            m = _LIGNE_ETIQUETTE.match(ligne)
            if (m and _cle_etiquette(m.group(1)) and _cle_etiquette(m.group(1)) != "resume") or _est_intertitre(ligne) or _FICHIER.search(ligne):
                break
            vides = 0
            morceau.append(ligne)
        i += 1
    return _propre_resume(morceau)


def _resume_sans_intertitre(lignes: list) -> str:
    """Pas d'intertitre : le ou les paragraphes de vrai texte (des phrases, pas des étiquettes ni des noms de fichiers) qui se suivent."""
    retenus, dernier = [], None
    for k, par in enumerate(_paragraphes(lignes)):
        texte = " ".join(par)
        nb_mots = len(texte.split())
        phrases = sum(1 for x in par if len(x.split()) >= 5)
        etiquettes = sum(1 for x in par if (_LIGNE_ETIQUETTE.match(x) and _cle_etiquette(_LIGNE_ETIQUETTE.match(x).group(1))))
        liste = sum(1 for x in par if x.startswith("•") or _FICHIER.search(x))
        bon = nb_mots >= 20 and phrases >= max(1, len(par) // 2) and etiquettes == 0 and liste * 2 <= len(par)
        if bon and (dernier is None or k == dernier + 1):
            retenus.append(texte)
            dernier = k
        elif retenus:
            break
    return _propre_resume(retenus)


def analyser(texte: str, deviner_resume: bool = True) -> dict:
    """Ce que dit une présentation ou un NFO (en texte simple, voir `en_texte`). Seules les clés trouvées sont rendues :
    titre, titre_original, titre_fr, auteur, editeur, date, genre, langue, format, pages (nombre), resolution, qualite (Digital / Scan),
    source, statut, equipe, isbn ({tome: ISBN-13 valide}), isbn_unique (un ISBN sans tome), synopsis, synopsis_langue.
    deviner_resume : sans intertitre « Résumé / Synopsis / Description », le paragraphe de vrai texte d'une page de tracker est pris pour le
    résumé ; faux pour un NFO de fichier, où seul un résumé annoncé par son intertitre compte (le reste est du texte de release)."""
    texte = str(texte or "").replace("\r\n", "\n").replace("\r", "\n")
    lignes = []
    for ligne in texte.split("\n"):
        ligne = re.sub(r"[─-╿]", " ", ligne) if re.search(r"[─-╿]", ligne) else ligne     # cadres des NFO (╔═══╗ ║ ║)
        ligne = ligne.strip()
        lignes.append("" if _est_separateur(ligne) else ligne)
    out, resume_trouve = {}, ""
    i = 0
    while i < len(lignes):
        ligne = lignes[i]
        m = _LIGNE_ETIQUETTE.match(ligne) if ligne else None
        cle = _cle_etiquette(m.group(1)) if m else ""
        if not cle and ligne:                                    # intertitre sans « : » (« Synopsis », « DESCRIPTION »)
            seul = correspondance.simple(re.sub(r"[\W_]+$", "", ligne.strip(" *-•·►▪▸=#:")))
            if re.fullmatch(_MOTS_RESUME, seul):
                cle = "resume"
                m = None
        if cle == "resume":
            valeur = (m.group(2).strip() if m else "")
            suite = _resume_sous_intertitre(lignes, i + 1)
            t = (valeur + " " + suite).strip() if valeur else suite
            if len(t.split()) >= 8 and len(t) > len(resume_trouve):
                resume_trouve = t
        elif cle and m:
            valeur = m.group(2).strip(" \t*_")
            if valeur and cle not in out:
                out[cle] = valeur[:200]
        i += 1
    if not resume_trouve and deviner_resume:
        resume_trouve = _resume_sans_intertitre(lignes)
    plein = "\n".join(lignes)
    isbn = {}
    for m in _LIGNE_TOME_ISBN.finditer(plein):
        c = isbn13(m.group(2))
        if c:
            isbn.setdefault(str(int(m.group(1))), c)
    uniques = [c for c in dict.fromkeys(isbn13(m.group(1)) for m in _ISBN_ETIQUETE.finditer(plein)) if c and c not in isbn.values()]
    if isbn:
        out["isbn"] = isbn
    if uniques:
        out["isbn_unique"] = uniques[0]
    _normaliser(out)
    if resume_trouve and len(resume_trouve.split()) >= 8:
        out["synopsis"] = resume_trouve
        out["synopsis_langue"] = langue_du_texte(resume_trouve) or "fr"
    return {k: v for k, v in out.items() if v not in ("", None, {}, [])}


def _normaliser(out: dict):
    """Valeurs utilisables : nombre de pages, résolution « 1499x2250 », qualité Digital / Scan, titres de série sans la mention de tome."""
    if "pages" in out:
        m = re.search(r"\d{1,5}", out["pages"])
        out["pages"] = int(m.group(0)) if m else None
    for cle in ("resolution",):
        if cle in out:
            m = re.search(r"(\d{3,5})\s*[x×]\s*(\d{3,5})", out[cle])
            out[cle] = f"{m.group(1)}x{m.group(2)}" if m else None
    if "annee" in out:
        if not out.get("date"):
            out["date"] = out["annee"]
        del out["annee"]
    brut = " ".join(str(out.get(k, "")) for k in ("qualite", "source")).lower()
    if re.search(r"num[ée]rique|digital|web|epub|ebook|e-book", brut) and not re.search(r"\bscan", str(out.get("qualite", "")).lower()):
        out["qualite"] = "Digital"
    elif re.search(r"\bscan", brut):
        out["qualite"] = "Scan"
    else:
        out.pop("qualite", None)
    if out.get("langue"):
        out["langue"] = out["langue"][:40]
    if out.get("genre") and correspondance.simple(out["genre"]) in ("manga", "mangas", "bd", "livre", "livres", "ebook", "comics", "bande dessinee"):
        del out["genre"]                                      # le type de livre, pas le genre de l'histoire (« Genre : Manga » chez C411)
