# Identification des séries : comment ça marche, pourquoi c'est fait comme ça

Écrit le 22/10/2026 après la refonte de toute la recherche sur Internet (statut, titres des tomes, chapitres, ISBN, résumés). À lire
avant de toucher à `tomes.py`, `identification.py`, `reseau.py`, `bnf.py`, `googlebooks.py`, `wikifr.py`, `notices.py` ou
`correspondance.py`.

## Les quatre règles (tout le reste en découle)

1. **Trois issues, jamais confondues** : *trouvé* (la source a répondu avec quelque chose), *rien trouvé* (elle a répondu : elle ne
   connaît pas) et *panne* (elle n'a pas répondu : réseau, quota, « patiente », page d'erreur). `reseau.py` lève `Panne` (ou `Quota`)
   pour tout ce qui n'est pas une réponse exploitable ; aucune fonction ne la transforme en « rien trouvé ».
   Seule l'issue *trouvé* écrit. *Rien trouvé* espace les essais (1, 3, 7 puis 30 jours). *Panne* ne change rien et fixe l'heure du
   prochain essai (celle que le service a donnée, sinon une heure).
2. **Rien de ce qu'on savait n'est effacé par une recherche.** On complète et on corrige ; une réponse vide, partielle ou en panne ne
   retire jamais une donnée. `tomes.oublier` n'est appelé que quand la série disparaît ou change d'identité (autre fiche AniList choisie) ;
   un renommage déplace le cache (`tomes.deplacer`). Les écritures d'une série passent toutes par `tomes.modifier` (verrou par série,
   fichier temporaire unique) : deux recherches qui finissent ensemble ne s'écrasent plus.
3. **Chaque étape dit ce qu'elle a fait**, en français, avec l'heure de reprise quand elle attend un service (écran « 🔄 Identification »,
   Journal → « Sources Internet »).
4. **Ce qui attend un service est repris tout seul** : `identification.identifier` renvoie l'heure du prochain essai, la préparation de
   fond (`prechauffage`) y remet la série dans sa file. Personne n'a à y penser.

## Les modules

| Fichier | Rôle |
|---|---|
| `reseau.py` | Un seul client Internet : rythme par service (AniList 0,8 s, Wikipédia 0,6 s, BnF 5 s…), nouvelles tentatives, pauses gardées dans `data/reseau.json` (elles survivent à un redémarrage), compteur du jour de Google Books (le quota se remet à zéro à minuit, heure du Pacifique = 9 h en France) avec réserve de 150 requêtes pour les demandes faites à la main. `reseau.get/post/anilist` rendent une `Reponse` (statut 2xx ou 404) ou lèvent `Panne`. |
| `correspondance.py` | « Ce titre est-il celui de cette série ? » pour toutes les sources : écritures voisines (Kamuy/Kamui, Kenichi/Ken-Ichi, Ø), titre français plus long (« Red eyes sword : Akame ga Kill ! »), séries dérivées refusées (Zero, saison 2, Shin, New…), noms courts stricts (« The Breaker » n'est pas « Wind Breaker »), éditions spéciales (Perfect, Deluxe) distinguées. |
| `wikifr.py` | Wikipédia en français : trouver la page de la série, lire la liste des volumes (modèle `TomeBD` : titres, dates, **ISBN français**, résumés, chapitres sous toutes leurs formes de numérotation), section d'une série dans une page partagée (Akame ga Kill / Zero). |
| `bnf.py` | Catalogue de la BnF (API SRU, UNIMARC) : ISBN, numéro, éditeur, pages et **résumé** de chaque tome français. |
| `googlebooks.py` | Google Books : une recherche pour toute la série au lieu d'une par tome (Google rend en fait 20 résultats par page : la page suivante reprend là où l'autre s'arrête, et on s'arrête dès qu'une page ne parle plus de la série) ; ISBN, résumé, éditeur. Google omet parfois le numéro du tome (« Air Gear » tout court) : l'ISBN, déjà connu par Wikipédia ou la BnF, le donne. En dernier recours (quota 1 000/jour). |
| `notices.py` | Ce qu'Internet dit de chaque tome, **source par source** (`notices` dans `data/tomes/<série>.json`) ; choix à la lecture : deux sources d'accord pour l'ISBN, sinon Wikipédia > BnF > Google ; résumé Wikipédia > BnF > Google sans la présentation de la série répétée. |
| `presentation.py` | Lire la présentation d'un torrent ou un NFO (HTML, BBCode, Markdown, texte) : titre, auteur, éditeur, parution, genre, pages, résolution, qualité, ISBN par tome, résumé. Sert aux NFO des archives (`edition.analyser_nfo`) et aux pages des trackers (`page_tracker.py`). |
| `identification.py` | Le parcours : statut → liste française de Wikipédia → répartition en tomes → fiche → ISBN et résumés. Rend un `Bilan(etat, detail, prochain, extra)` par étape. `a_reprendre()` liste les séries dont une étape attend. |
| `tomes.py` | Les recherches elles-mêmes (AniList, MangaDex, Wikipédia anglais, MangaUpdates), le stockage (`modifier`, `_charger`) et les anciennes fonctions publiques (`chercher`, `statut_officiel`, `fiche`, `titres_tomes`…), toutes passées sur `reseau`. |

## Le parcours (`identification.identifier`)

1. **statut** : AniList (fiche choisie, indice des fichiers, ou recherche par le nom puis par le nom d'origine de MangaUpdates) + résumé de la
   série. Résumé : MangaDex (français) > Wikipédia (français) > MangaUpdates > AniList (anglais). Un meilleur résumé n'est jamais remplacé par un moins bon ;
   un résumé seulement anglais est recherché à nouveau chaque mois ; un service qui n'avait pas répondu fait refaire l'étape dans l'heure. AniList donne aussi les
   **synonymes** (le titre français s'y trouve souvent) : ils servent à reconnaître la série partout ailleurs.
2. **liste_fr** : liste des volumes de Wikipédia en français (titres des tomes, chapitres, dates, ISBN, résumés). Pages trouvées par les noms sûrs (dossier, AniList,
   synonymes), puis par les liens de l'article, puis — pour « Série : Suite » — dans la page de la série mère (section de la suite, jamais la page entière).
3. **tomes** : répartition des chapitres en tomes : Wikipédia anglais, puis la liste française, puis MangaDex (qui complète aussi). Si seule MangaDex a répondu parce
   que Wikipédia n'a pas répondu, la répartition est *provisoire* (refaite dans l'heure).
4. **fiche** : dates, auteurs, genres, éditeurs (AniList, Wikipédia, MangaUpdates, Google Books). Un champ n'est jamais remplacé par du vide.
5. **notices** : ISBN et résumés des tomes présents. Wikipédia (déjà lue), puis la **BnF** (sans quota), puis **Google Books** seulement pour ce qui manque encore
   (une recherche de série puis quelques tomes un à un ; un tome cherché sans succès n'est pas redemandé avant un mois).
6. (dans l'appli) **rangement** des chapitres, puis **ISBN lus dans les pages** : dernier recours, seulement pour les tomes qu'aucune source Internet n'a *et* quand
   toutes ont répondu (`Bilan.extra["attente"]` faux). Si Google Books attend son quota, l'appli attend aussi plutôt que de lire les pages.

## Séries suivies encore vides

Une série ajoutée avec ➕ mais sans tome n'a pas de fichier d'où deviner sa fiche : la fiche AniList choisie à l'ajout (`suivi[nom].anilist`) sert d'identité (`app._anilist_choisi`, derrière « 🔎 Choisir la fiche »).
La préparation de fond (`prechauffage`) lui fait faire les étapes `statut` (synopsis, noms français, synonymes) et `fiche` ; les synonymes servent ensuite à reconnaître ses torrents
(`lecture_pages.est_la_serie`). Quand elle reçoit ses premiers fichiers, elle suit le parcours complet.

## Sources : utilisées et refusées

Utilisées (API ouvertes ou documentées, rythme respecté, `User-Agent` qui nous identifie) : AniList, Wikipédia (en, fr), MangaDex, MangaUpdates, BnF
(catalogue.bnf.fr/api/SRU : licence ouverte, robots.txt : délai de 5 s respecté), Google Books (clé de l'utilisatrice).

Examinées et **refusées** (ne pas relancer sans nouvelle raison) :
- Manga-News : protégé par Cloudflare (« Just a moment… ») : on ne contourne jamais une protection anti-robot.
- Bédéthèque et Livraddict : leur robots.txt interdit expressément ClaudeBot / Claude-Web / anthropic-ai.
- Nautiljon, Booknode, manga-sanctuary.com : refusés depuis octobre 2026 (anti-robot, robots.txt).
- Decitre (403), Babelio (conditions d'usage), Leslibraires.fr et Placedeslibraires.fr (leur robots.txt interdit la recherche).
- Mangacollec : pas d'API publique documentée ni d'autorisation explicite.
- Open Library : autorisé, mais presque aucun tome français (1 ISBN sur 6 essayés, aucun résumé) : pas retenu.

## Ce qui est gardé où

`data/tomes/<série>.json` : `statut_officiel` (AniList + résumé : `resume`, `resume_langue`, `resume_source`, `synonymes`), `tomes`/`titres`/`source` (répartition),
`fiche`, `titres_tomes` (`titres`, `details` par volume : titre, sortie, `isbn`, `resume`, `chapitres`, `numeros`, `couverture`), `notices` (par tome puis par source),
`resumes_tomes` (anciens résumés Google, toujours lus), `recherches` (par étape : état, détail, `prochain`), `edition_differente`.
`data/reseau.json` : pauses et compteur du jour des services. Les ISBN, résumés et sommaires saisis à la main ou lus dans les tomes restent dans
`<série>/.mouflanga-infos.json` et passent toujours devant Internet.

## Changer ou ajouter quelque chose

- **Un nouveau service** : l'ajouter dans `reseau.SERVICES` (rythme, quota), écrire un module qui ne parle à Internet que par `reseau.get/post` et lève `Panne` telle quelle,
  rendre des notices `{tome, isbn, resume, titre, editeur, date, pages}` à `notices.enregistrer(serie, "<source>", …)`, ajouter la source à `notices.SOURCES` (ordre de confiance)
  et dans `identification.etape_notices`.
- **Une règle de reconnaissance de titre** : dans `correspondance.py`, avec un cas dans `tests/test_correspondance.py` (cas réel).
- **Un nouveau format de liste de chapitres sur Wikipédia** : `wikifr.ligne_de_chapitre`, avec la ligne réelle dans `tests/test_wikifr.py`.
- **Toujours** : un test avec `tests/faux_internet.py` (faux Internet à partir de vraies réponses) ; `tests/test_identification_parcours.py` vérifie qu'aucune
  panne, aucun quota, aucune réponse au hasard ne fait perdre une donnée.

## Retrouver pourquoi quelque chose manque

Journal → section « Sources Internet de l'identification » (pauses, requêtes du jour, dernières pannes, séries en attente) ; écran
« 🔄 Identification » d'une série (une ligne par étape) ; `data/tomes/<série>.json` → `recherches` (état et `prochain` de chaque étape).
