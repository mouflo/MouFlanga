# Historique des versions

## Remplacer par une intégrale : les tomes absents partent aussi (13 octobre 2026)
- 🧲 Quand un torrent d'intégrale (« Perfect INTEGRALE », « Perfect Édition (01-18) »…) remplace les tomes, les tomes de l'ancienne édition qu'il ne contient pas (ex. 19 à 27) vont aussi à la corbeille (30 jours). Seulement si l'intégrale annonce N tomes et les apporte tous (1 à N) ; sinon rien de plus n'est retiré.

## Aperçu d'allègement fidèle, fiche d'infos lisible (13 octobre 2026)
- 👁 L'aperçu « Après » affiche désormais exactement les octets qu'« Appliquer » écrirait. Avant, il était recompressé en qualité 88 et réduit : les différences entre 98 et 40 étaient masquées. Le détail zoomé est encodé sans perte visible.
- 📋 La fiche d'infos de la série (ℹ️) passe les libellés au-dessus de chaque valeur : plus de colonne écrasée sur téléphone.

## Chapitres par tome d'une autre édition (12 octobre 2026, soir)
- 📖 « Chapitres 1 à 4 » sur le tome 1 d'une Perfect Édition venait de la répartition de l'édition standard (Wikipédia). La plage affichée vient maintenant du sommaire lu dans le tome (ou corrigé à la main), et quand l'édition importée n'a pas le même nombre de tomes que l'édition standard (18 au lieu de 27), la répartition de Wikipédia n'est plus utilisée : le sommaire de chaque tome est lu dans le fichier.

## Chapitres écrits dans le fichier du tome, pour le partage (12 octobre 2026, soir)
- 📝 Fiche d'un tome → **Écrire dans le fichier** : les chapitres et leur page de départ sont inscrits dans le `ComicInfo.xml` du .cbz (signets standard, lus par Komga, Kavita…). Les pages sont recopiées telles quelles, l'ancien fichier va à la corbeille (30 jours). Un tome encore partagé par qBittorrent est écrit à part (échange de dossiers) : le torrent n'est pas touché.
- 📥 MouFlanga relit ces signets quand il trouve un tome reçu d'un partage : les chapitres s'affichent sans relire le sommaire.

## Chapitres d'un tome corrigeables à la main (12 octobre 2026, soir)
- ✏️ Dans la fiche d'un tome (ⓘ), le bouton **Corriger les chapitres** ouvre la liste en texte, une ligne par chapitre (« 2. La valeur de la vie »). Les liens de lecture des numéros déjà connus sont gardés. La page où commence un chapitre se règle aussi (« 2. Titre @64 », page du lecteur), avec un décalage commun pour toutes les pages. Une liste corrigée à la main n'est plus remplacée par la lecture automatique (« Relire le sommaire » demande confirmation).

## Nombre de tomes de l'édition (12 octobre 2026, soir)
- 📚 Une série importée en « Perfect Édition (01-18) » est comparée à ses **18 tomes**, plus aux 37 de l'édition standard d'AniList. Le nombre de tomes est lu dans le nom de l'archive (« (01-18) », « T01-T74 », « Intégrale 15 tomes ») même pour les séries importées avant ; « Perfect Édition » est reconnue comme mention d'édition.

## Encart « Organiser » qui revenait (12 octobre 2026, soir)
- 🧹 Un nom de série que tu as déjà choisi (ex. « Gantz ») n'est plus remis en cause parce que les fichiers du torrent s'appellent « Gantz : Perfect - Tome NN », et un tome déjà dans son dossier « Tome NN » n'est plus à déplacer à cause de son nom de fichier. L'encart ne revient donc que pour un vrai rangement à faire.

## Mises à jour visibles tout de suite (12 octobre 2026, soir)
- 📱 L'appli installée charge d'abord la version la plus récente des scripts et styles (avant : l'ancienne version s'affichait une fois de plus, il fallait recharger deux fois pour voir une nouveauté).

## Alléger : réglage manuel, aperçu en direct, accès permanent (12 octobre 2026, soir)
- 🎚 **Qualité manuelle** en plus de l'automatique : curseur 40-98 (100 = identique à l'original). L'analyse et l'allègement utilisent alors ce réglage tel quel.
- 👁 **Aperçu en direct** : le bouton « Comparer avant / après » s'ouvre sans analyse préalable, avec un choix de tome ; changer la largeur, l'éclaircissement ou le curseur recalcule l'image tout de suite (poids de la page avant → après).
- 🪶 **Ligne permanente** sous le titre de la série après une analyse (« Analyse prête : … Comparer et alléger ») : le résultat n'est plus perdu quand on ferme la fenêtre.
- 🔔 **Correction des notifications du téléphone** : la clé de l'appli n'était pas lue correctement (erreur à chaque alerte). Les téléphones dont l'abonnement avait expiré sont oubliés et doivent se réabonner avec le bouton 📱.

## Alléger : comparer avant / après (12 octobre 2026, soir)
- 👁 Après l'analyse, un bouton 👁 sur chaque tome ouvre une comparaison : la même page avant et après, avec exactement les réglages que « Appliquer » utiliserait. Boutons **Avant** / **Après** pour basculer sur place, ◀ ▶ pour changer de page, toucher l'image pour voir un détail à l'échelle réelle, et la taille de la page avant → après.

## Alléger : suivi et notification de fin (12 octobre 2026, soir)
- 🪶 Barre de progression (tomes faits / total) dans la fenêtre Alléger ; le travail tourne sur le serveur, tu peux fermer la fenêtre ou la page.
- 🔔 Une bulle « analyse prête » / « allègement terminé » apparaît à la fin si la page est ouverte, et un message Telegram + notification du téléphone arrive dans tous les cas.

## Alléger fonctionne aussi sur les tomes du torrent (12 octobre 2026, soir)
- 🪶 Les tomes encore partagés par qBittorrent (ex. « Gantz : Perfect ») sont maintenant allégés : la version légère est écrite dans un dossier voisin, puis les dossiers sont échangés (le NAS refuse de renommer le fichier, pas le dossier). Le fichier du torrent n'est jamais touché ; l'ancien dossier va à la corbeille (30 jours). La place du torrent n'est rendue qu'une fois le torrent supprimé dans qBittorrent.

## Dépôt allégé (12 octobre 2026, soir)
- 🧹 Les fichiers qui servent seulement au propriétaire pour travailler avec Claude Code (script d'installation, mémos `CLAUDE.md`) ne sont plus publiés dans le dépôt : ils restent sur son serveur. Rien ne change pour l'installation ou l'utilisation de l'appli.

## Rescan des torrents, fiche avant ajout, noms mieux reconnus (12 octobre 2026, soir)
- 🔄 **Page Importer → Dossier des torrents** : relit le dossier d'arrivée des torrents (`Mouflanga.NOK`), montre le nom de série deviné pour chaque élément (modifiable) et importe ceux que tu coches avec le même traitement automatique qu'un vrai téléchargement (rangement, identification, fiche, couverture, Telegram). Une série qui a déjà ses tomes n'est jamais écrasée. Rien n'est modifié dans le dossier des torrents.
- 👆 **➕ Ajouter une série** : toucher le **nom** d'un résultat ouvre sa fiche dans MouFlanga (la série est ajoutée si besoin) : infos, poster (MouFloster ou image), bouton 🧲 Choisir un torrent.
- 🔎 Identification corrigée d'après le rescan : « NOTAG » et « HYBRID » ne deviennent plus une suite de série (« 20th Century Boys : NOTAG ») ; un titre AniList en thaï ou en japonais n'est plus choisi (« Frieren ») ; un nom d'auteur à la fin est écarté quand le titre seul est connu (« Jujutsu Kaisen Gege Akutami ») ; une seule correction ne fait plus disparaître un mot du titre partout (« Regis »).

## Favorites (12 octobre 2026, soir)
- ⭐ Une étoile sur chaque affiche de la bibliothèque : touche-la pour mettre la série en favorite (elle devient jaune), touche-la encore pour l'enlever. La série ne s'ouvre pas.
- Dans le menu **Ma lecture**, le choix **⭐ Mes favorites** n'affiche que celles-là (cumulable avec Parution et Univers).
- Les favorites sont propres à chaque compte (admin et chaque lecteur) et suivent la série si elle est renommée.

## Icône de l'appli (12 octobre 2026, soir)
- 🎨 L'icône de l'appli sur le téléphone a maintenant un fond noir plein (les coins transparents la rendaient illisible sur fond clair).
- 🔧 Le téléphone gardait l'ancienne icône dans son cache : le cache est renouvelé et les icônes sont toujours demandées au serveur d'abord.

## Correction d'affichage (12 octobre 2026, soir)
- 🔧 Fiche d'une série : le « ? » de la légende des sources est de nouveau un petit rond à côté de la pastille (il apparaissait comme un grand bloc vert en dessous).

## Sommaires stylisés lus par Claude (facultatif) (12 octobre 2026, soir)
- 🤖 📏 Règles → Sources : une clé API de Claude (facultative, payante, quelques centimes par tome) permet de lire les sommaires que la reconnaissance de texte du serveur ne lit pas (texte blanc sur noir, comme Bakuman). Sans clé, rien n'est envoyé.

## Appli sur le téléphone : lecture hors ligne et notifications (12 octobre 2026, soir)
- 📲 MouFlanga s'installe comme une appli (icône, plein écran) depuis Chrome : menu ⋮ → « Ajouter à l'écran d'accueil ».
- ⬇️ **Lire sans réseau** : dans la fenêtre ⓘ d'un tome, « Garder sur ce téléphone ». La taille et la place libre sont affichées avant de confirmer. Le bouton 📱 (en haut) liste les tomes gardés avec leur place, permet de les supprimer, et propose « effacer une fois lu ». La progression notée sans réseau part au retour du réseau.
- 🔔 **Notifications sur le téléphone**, pour l'admin comme pour chaque lecteur, chacun choisissant ses sujets dans 📱 : alertes de l'appli (admin), demande acceptée ou disponible, nouveaux tomes d'une série qu'on lit. Telegram garde toutes les alertes (historique).

## Alléger et nettoyer les tomes (12 octobre 2026, soir)
- 🪶 Menu ⋯ → **Alléger ou nettoyer les tomes** : l'appli analyse d'abord, sans rien modifier, et montre le gain par tome. Chaque tome est recompressé à la qualité la plus légère qui reste invisible à l'écran (vérifiée sur des pages d'essai). Les pages peuvent être ramenées à 1600 px (tablette) ou 1200 px (téléphone). Tu appliques ensuite à toute la série.
- 🧼 **Éclaircir le papier** des scans gris (niveaux automatiques), avec un aperçu avant/après. Les pages en couleur ne sont jamais touchées.
- Structure des tomes intacte (noms des pages, chapitres, ComicInfo). Fichiers partagés par qBittorrent jamais modifiés. Anciens fichiers à la corbeille (30 jours). Résolution et source recalculées ensuite.
- Exemple mesuré : Claymore tome 1 (240 Mo, 1920 px) → environ −28 % en 1600 px, sans différence visible.

## Découper un gros fichier en tomes (12 octobre 2026, soir)
- ✂️ Menu ⋯ → **Découper un gros fichier en tomes** : un écran avec les miniatures de toutes les pages ; tu touches la première page de chaque tome, puis « Découper ». Un fichier par tome, l'original va à la corbeille une fois tout écrit (ou reste tant que qBittorrent le partage).
- 📑 Si le fichier contient un sommaire (index.json des sites de lecture, comme Buyuden : 134 chapitres, 13 tomes), les tomes sont déjà placés et chaque tome garde ses chapitres et leurs titres.
- Les tomes déjà présents ne sont remplacés qu'après confirmation (anciens à la corbeille).

## Même équipe et hors-séries du wiki Fandom (12 octobre 2026, soir)
- ⭐ **Même équipe en priorité** : les propositions de tomes suivants mettent en tête l'équipe de la série (« PRiNTER-PapriKa+ » ≈ « TONER-Paprika »), avec l'étiquette ⭐.
- 🔁 **Remplacement automatique** : quand l'équipe de la série sort enfin un tome que tu as d'une autre équipe (1 à 3 tomes), l'appli le télécharge et remplace l'ancien tout seul (corbeille 30 jours, lu gardé). Message Telegram « NoFace696 → PapriKa ».
- 📚 **Hors-séries : fiche du wiki Fandom** de la série en premier choix (One Piece Blue, Red, Yellow) : titre complet, type (Databook…), sortie en France, éditeur, pages, petit descriptif.
- 📖 **Ordre de lecture** : « à lire après le tome 24 » sous le hors-série, et le groupe Hors-série est trié dans cet ordre (Red, Blue, Yellow).

## Fiches, sources, hors-séries et choix retenus (12 octobre 2026, soir)
- 🔁 **Fusion : « Remplacer toute la série »** : l'ancienne série part entière à la corbeille et l'autre prend sa place (cas Gantz → Gantz Perfect). « Remplacer les tomes en double » ne remplace que les mêmes numéros.
- 🔎 **Choisir la fiche (AniList)** dans le menu ⋯ : tu cherches avec d'autres mots (titre japonais, anglais, auteur), tu vois les couvertures, l'année, le statut et le nombre de tomes, puis tu choisis. La fiche retenue sert partout (statut, tomes, résumé, éditeur…). Tu peux revenir à la recherche automatique.
- 🎨 **Sources en couleur** : Scantrad (rouge), Scan 🥇 (jaune), Scan 🥈 (orange), Digital (vert), « ? » quand l'appli doute. Un petit « ? » ouvre la légende. « Corriger la source » propose ces choix au lieu d'un champ libre.
- 📎 **Rattacher comme hors-série** : un artbook ou databook rangé comme une série à part (Artbook Kenshin) peut rejoindre sa série mère dans le groupe Hors-série. L'appli le propose toute seule quand le nom ressemble à une série existante.
- 🧠 **Choix retenus** : dans Télécharger, « Toujours faire ce choix pour cette série » applique ensuite tout seul remplacer, ajouter les manquants ou ne rien faire. Les règles se suppriment dans ⚙️ Réglages → Général.
- ⚠️ **Nom proche** : envoyer un torrent vers « Breaker » alors que « CØDE BREAKER » existe fait demander dans quelle série le ranger.
- 📄 **ComicInfo.xml plus complet** dans les tomes fabriqués par l'appli : auteur, dessinateur, éditeur, année, nombre de tomes, genres, lien AniList (seulement pour une série identifiée).

## Torrents : vraie copie dans MouFlanga (12 octobre 2026)
- 📋 Les fichiers d'un torrent sont maintenant **copiés** dans la série, au lieu d'être un lien physique vers le fichier de qBittorrent. Ils sont indépendants du torrent : on peut les renommer, les déplacer ou fusionner la série tout de suite.
- Réglage dans ⚙️ Réglages → Connexions → Torrents (coché par défaut). Décoché : lien physique, sans place en plus sur le NAS, mais fichiers bloqués tant que qBittorrent les partage.
- Effacer le torrent et ses fichiers dans qBittorrent ne touche jamais les fichiers de MouFlanga, avec un lien comme avec une copie.

## Fusion de deux séries : choix (12 octobre 2026)
- 🔀 Renommer une série avec le nom d'une série déjà là ouvre une fenêtre de choix au lieu d'un simple OK/Annuler :
  - ➕ ajouter seulement les tomes manquants ;
  - ♻️ tout remplacer (les tomes en double de la série d'arrivée vont à la corbeille, l'état « lu » est gardé) ;
  - ✋ ne rien faire.
- La fenêtre indique les tomes de chaque série et ceux qu'elles ont en commun. Elle prévient quand ce sont deux éditions différentes, et quand les fichiers sont encore partagés par qBittorrent : la fusion est alors refusée avec une explication, au lieu d'une erreur.

## Ré-identification et éditions spéciales (12 octobre 2026)
- 🔄 À la fin d'une ré-identification, la page de la série se recharge toute seule avec les nouvelles infos, même si tu as fermé la fenêtre d'avancement.
- 📚 Éditions spéciales (Perfect, Deluxe, Édition de luxe, Kanzenban…) :
  - Une autre édition d'une série déjà là a son propre dossier, par exemple « Gantz : Perfect Édition » à côté de « Gantz ».
  - Ces séries sont identifiées sous le titre de base : « Gantz : Perfect » est cherchée comme « Gantz », pas comme « Perfect ».
- 🧠 Mémoire des noms : retirer « Édition de luxe » une fois (Cat's Eye) ne fait plus disparaître « Édition » ni les tirets des noms des archives suivantes. C'est ce qui avait transformé « Gantz - Perfect Édition » en « Gantz : Perfect ».

## Sommaire des tomes, résumés et rangement automatique (12 octobre 2026)
- 🔍 **Sommaire lu dans le tome** : pour un tome complet sans liste de chapitres en français, l'appli lit ses premières pages (OCR, tesseract) et trouve la page « Sommaire ». Les chapitres apparaissent dans ⓘ et chacun ouvre le tome à la bonne page. La lecture se lance toute seule à l'ouverture de ⓘ, en arrière-plan, et prend environ une minute. Le bouton « 🔍 Relire le sommaire du tome » la refait. Les sommaires très stylisés (texte blanc sur fond noir, comme Bakuman) restent illisibles.
- 📖 **Résumé du tome** dans ⓘ : celui de Wikipédia, ou sinon la notice Google Books en français.
- 📝 **Résumés de série plus fiables** : une série inconnue d'AniList sous son nom français (« Prisonnier Riku ») est retrouvée par son nom d'origine via MangaUpdates (« Shuujin Riku »). Sans AniList, le résumé vient de Wikipédia, sinon de MangaUpdates. Une série sans résumé est réessayée chaque jour au lieu d'une fois par semaine. Les résumés qui enchaînaient ceux des suites (The Breaker) s'arrêtent à la série.
- 📚 **Tomes de The Breaker** : MangaDex ne prend plus une autre série au titre proche. Un chapitre rangé dans le mauvais tome d'après une ancienne répartition change de tome au rangement suivant.
- 🔄 **Ré-identification complète** : statut et résumé d'abord, puis tomes, fiche et **rangement des chapitres dans leurs tomes**. Chaque étape est affichée.
- 🤖 **Automatique** : une série qui a des chapitres « Hors tome » est re-cherchée tous les 3 jours, en arrière-plan, puis rangée toute seule.
- ✕ **Fiche grisée supprimable** : une série ajoutée (📥 Recherchée) mais encore vide a un bouton ✕ pour retirer sa fiche. Aucun fichier n'est touché.

## Provenance des tomes (9 octobre 2026)
- 🏷 La fenêtre ⓘ d'un tome indique sa **provenance** : l'équipe de scan (lue dans le nom d'origine, ex. « PRiNTER-PapriKa+ ») et l'origine (torrent, rangement).
- Elle est notée au rangement et à l'import d'un torrent, puis ne change plus toute seule.
- ✏️ **Noter la provenance** : tu peux saisir l'équipe et l'origine à la main ; cette note ne sera jamais remplacée automatiquement.

## Lien d'une page pour identifier un hors-série (9 octobre 2026)
- 🔗 Dans la fenêtre 🔎 d'un hors-série, colle le lien d'une page (Glénat, éditeur, boutique) : l'appli lit le titre, l'auteur, l'année et l'éditeur, et tu valides le résultat comme les autres.
- Une page qui refuse la lecture automatique (protection anti-robot) ne déclenche rien : l'appli te le dit et tu saisis les infos à la main.

## Corrections (12 octobre 2026)
- 🗑 Supprimer un hors-série ne plante plus (il est traité comme un fichier entier).
- 🏷 Hors-série : bouton « Renommer » dans la fenêtre 🔎 (change seulement le titre affiché).
- 🚪 Déconnexion possible pour les comptes lecteurs.
- 🔒 Les boutons réservés à l'admin (relance d'identification, couvertures des tomes, univers, identification des hors-série, provenance, couverture) sont cachés aux lecteurs.

## Identification des hors-série (9 octobre 2026)
- 🔎 Chaque hors-série a un bouton 🔎 : l'appli cherche sur AniList, MangaDex et Google Books (avec le nom de la série et de l'auteur), et tu choisis le bon résultat dans la liste.
- ✏️ Si rien ne convient : saisie à la main (titre, année, auteur, lien). « Retirer l'identification » revient au nom du fichier.
- Le titre identifié remplace le nom du fichier dans la liste ; le fichier, lui, n'est jamais renommé.

## Hors-série regroupés (9 octobre 2026)
- 📚 Les hors-série d'une série (HS, Data Book, artbook, one-shot) sont regroupés dans un groupe « Hors-série » en haut de la liste des chapitres, repliable comme un tome. Exemple : One Piece (Blue, Red, Yellow).

## Rapidité et retour (9 octobre 2026)
- ⚡ La bibliothèque s'ouvre plus vite (environ 0,8 s au lieu de 2,2 s) : le cache de lecture des fichiers de tome ne se vide plus à chaque ouverture.
- ↩️ Sur la page des couvertures, « Retour à la série » ramène à la fiche de la série, pas au menu principal.

## Couvertures des tomes (9 octobre 2026)
- 🖼 ⋯ → **Couvertures des tomes** : une page montre, tome par tome, la couverture actuelle et celles trouvées sur MangaDex (en bonne résolution, français en premier).
- Remplacement **une par une** ou **toutes d'un coup** (les anciennes sont gardées). « Retirer le remplacement » revient à la première page du fichier.
- 📷 **Mon image** : envoyer une photo ou une image depuis le téléphone pour un tome précis.
- Le fichier CBZ de chaque tome n'est jamais modifié : les images sont rangées dans « <série>/.couvertures/ ».

## Univers (9 octobre 2026)
- 🌌 Plusieurs œuvres peuvent être regroupées dans un **univers** (ex. Seven Deadly Sins : la série principale, Four Knights, Seven Days, Original Sin, HS). Chaque série garde son dossier, sa fiche et sa progression.
- ⋯ → **🌌 Univers de la série** : nom de l'univers, rang de lecture (1, 2, 3…), description facultative (gardée une fois).
- Filtre **🌌 Univers** dans la bibliothèque, tri **Univers (ordre de lecture)**, et recherche par nom d'univers.
- La fiche ⓘ indique l'univers, le rang de la série et les autres œuvres, dans l'ordre de lecture.

## JoJo et éditeurs (9 octobre 2026)
- 📚 JoJo's Bizarre Adventure : le nombre de tomes attendu est celui de la série complète (131), pas celui de la 8e partie retenue par AniList (27).
- 🏢 L'éditeur de la fiche n'affiche plus les dates entre parenthèses (« J'ai lu · Tonkam »).

## Avancement de la ré-identification (9 octobre 2026)
- 🔄 Relancer l'identification ouvre une fenêtre qui suit chaque étape en direct : cache, tomes, statut AniList, fiche (sources qui ont répondu, éditeur trouvé). Une étape en erreur est signalée sans bloquer les autres ; on peut fermer la fenêtre, le travail continue.

## Sources à la ré-identification et clé Google Books (9 octobre 2026)
- 🔄 Relancer l'identification interroge aussi **MangaUpdates** (éditeurs, auteurs, nombre de volumes) et **Google Books** (éditeur et auteur d'une édition française, plus grand numéro de tome trouvé). La fiche ⓘ indique les sources consultées.
- 🔑 Réglages → **📏 Règles de recherche → 🔑 Sources** : saisie de la clé API Google Books, bouton « Tester » qui la vérifie auprès de Google avant d'enregistrer, et « Retirer la clé ». La clé n'est jamais réaffichée en entier.

## Doublons : ne rien faire (9 octobre 2026)
- 🚫 Troisième choix « Ne rien faire » sur une demande « déjà présent » (Télécharger) : la demande est fermée et ne revient plus.
- 🔕 Une notification n'est envoyée que pour un doublon nouveau ; les doublons refusés ou dont le fichier a disparu ne sont plus signalés.

## Règles de recherche et sources (9 octobre 2026)
- 📏 **Règles de recherche** (menu de la bibliothèque, administrateur) : deux onglets comme dans Sonarr.
  - 🧾 **Profils de version** : un profil refuse les torrents qui ne contiennent pas un de ses mots (« doit contenir »), ou qui contiennent un mot interdit (« ne doit pas contenir »). Il peut se limiter à certaines séries et fixer une taille maximale en Go.
  - 🏷 **Formats personnalisés** : des mots qui ajoutent ou retirent des points ; les torrents avec le plus de points sont proposés en premier.
- 🔤 Tri et recherche par **auteur** et **éditeur** dans la bibliothèque (d'après la fiche de la série).
- ➕ **Ajouter une série** : la recherche interroge aussi **MangaDex** (dont les mangas français) et **MangaUpdates**. Les sources sans réponse sont signalées.
- ✏️ **Saisir un manga à la main** quand il n'est trouvé nulle part : titre, auteur, éditeur et lien vers le site qui le décrit (affiché dans la fiche ⓘ).

## Connexion et liens Telegram (9 octobre 2026)
- 🔗 Un lien ouvert depuis Telegram (« …/#Série ») ouvre bien la fiche demandée après la connexion : le #fragment est reporté dans la page de connexion.

## Lot 1 : identification, éditions, Telegram, bandeau (9 octobre 2026)
- 🔤 Ø traité comme O dans la reconnaissance des noms ; une réécriture (« Code » → « CØDE ») n'apprend plus un mot à retirer.
- 🏷 Les mentions « Édition de luxe », « deluxe », « collector »… sont retirées du nom de la série et affichées sur la fiche.
- 📚 Les doublons d'un rangement à la main gardent le bon chemin après renommage ; une tâche dont les fichiers ont disparu passe en erreur.
- 🔔 Bandeau « N choix à faire » dans la bibliothèque (administrateur).
- 📖 Titres de chapitres cliquables dans la fenêtre ⓘ d'un tome ; accolades parasites retirées.
- 📨 Telegram : noms de torrents sans points (plus de liens faux), lien « Ouvrir dans MouFlanga » explicite.
- 🚫 Plus de propositions de torrents pour une série complète ou déjà en cours de téléchargement.

## Renommage sur dossier seul (9 octobre 2026)
- ✏️ Renommer une série dont les fichiers viennent d'un torrent : seul le dossier est renommé (le NAS refuse de renommer les fichiers partagés avec qBittorrent). Les fichiers gardent leur nom, la progression de lecture suit.

## Relance de l'identification (9 octobre 2026)
- 🔄 **Relancer l'identification** dans le menu ⋯ : efface le cache de la série et refait la recherche (tomes, statut, fiche) avec le nom actuel.
- ✏️ Un renommage relance l'identification tout seul.

## Résolution refaite après remplacement (9 octobre 2026)
- 🔍 Quand des tomes sont remplacés (à la main ou par un torrent), l'analyse de résolution et de source de la fiche est refaite à l'ouverture suivante.

## Choix avant remplacement (8 octobre 2026)
- ❓ **Tomes déjà présents** : un torrent ou un rangement à la main qui contient des tomes déjà là ne remplace plus rien tout seul. La tâche passe « À valider » dans Télécharger, avec deux boutons : remplacer tous les tomes (confirmation, anciens tomes à la corbeille 30 jours) ou ajouter seulement les manquants.
- 🔔 Rappel Telegram à l'arrivée d'une tâche à valider, puis une fois par jour tant qu'il n'y a pas de choix.
- 🗂 Bouton Organiser : les tomes en double sont signalés au lieu d'être laissés en silence.
- ✖ Case « Remplacer les tomes déjà présents » du formulaire de torrent supprimée (remplacée par ce choix).

## Retouches du 7 octobre 2026 (soir)
- ⓘ **Fenêtre d'un tome** : la couverture du tome (première page de son fichier, toucher = grand format) à gauche, titre et sortie en France à droite, titres des chapitres dessous ; plus de résumé (trop long). Les titres français passent avant les titres anglais (« titres en anglais » seulement en dernier recours) ; l'apostrophe doublée (« L''Immortel ») est corrigée.
- ⓘ **Vert ou gris** : vert quand des titres de chapitres existent pour le tome, gris sinon (la fenêtre s'ouvre quand même, avec la couverture).
- 📐 **Couverture de la fiche en taille fixe** (120 × 180) d'une série à l'autre ; titre limité à 3 lignes (complet au toucher) ; ligne d'état raccourcie (« En cours · 15 tomes sortis ») ; source de l'édition avec « ? » orange (devinée) ou « ✓ » vert (sûre).
- ‹ › **Flèches entre séries** : elles parcourent toute la bibliothèque dans l'ordre du tri choisi, même si on est arrivé par une lettre, un filtre ou une recherche.
- 🛡️ **Vérification Japscan** : bandeau « Le site attend ta vérification » et pastille ⚠️ sur « Télécharger » sur toutes les pages ; une fois la vérification passée, retour automatique à la page où tu étais (même si tu l'as ouverte depuis l'alerte Telegram : la dernière page vue est retenue).
- 🛡️ **Captcha Japscan** : la vue de la page Vérification défile toute seule jusqu'au bloc du captcha, bouton « Valider l'ordre » compris.
- 🔍 **Recherche tolérante** : les lettres doublées sont ignorées (« Belzébub » trouve « Beelzebub »).
- 🗑 **Suppression d'une série** : elle n'est plus suivie non plus (avant, elle restait affichée en grisé « Recherchée »).

## 2.0 — Lecteurs, torrents et séries suivies (7 octobre 2026)
- 👥 **Comptes lecteurs** (⚙️ Réglages → Comptes) : lecture seule, vérifiée par le serveur ; progression séparée pour chacun
- 📮 **Demandes de mangas** par les lecteurs (recherche AniList) ; l'admin accepte ou refuse ; Telegram et rappels réglables tant qu'une demande attend
- 🧲 **Torrents** : recherche dans Prowlarr (badges FR, Digital, Intégrale, tomes), envoi à qBittorrent (catégorie « mouflanga » créée toute seule, dossiers NOK → OK comme Radarr/Sonarr), import automatique à la fin, message Telegram ; aussi listés dans l'onglet « En cours »
- ➕ **Séries suivies** comme Sonarr : ajout depuis AniList (ou demande acceptée), affiche grisée « 📥 Recherchée » ; surveillance quotidienne dans Prowlarr : 🆕 tomes absents ou nouveaux, ⬆️ meilleure version (Scan/Web → Digital) ; tout reste à valider à la main, avec rappels
- ⬆️ **Remplacement par une meilleure version** : l'ancien tome va à la corbeille, la lecture reste marquée
- 🏷 **Infos de l'édition** : NFO et archive d'origine gardés à l'import ; résolution et source (Digital, Scan, Web) devinées pour chaque série, corrigeables
- 🔎 **Bibliothèque** : menus cumulables Ma lecture · Parution · Tri (A→Z, Z→A, ajoutées, lues, progression) ; « Il en manque » aussi pour les séries en cours ; ✔ série lue, ⏳ à jour en attente du prochain tome
- ⚙️ **Réglages en onglets** (Général · Dossiers · Connexions · Comptes), communs aux quatre applis
- 🎵 Générique de l'anime (MouFlopening) à écouter et à choisir depuis la fiche ; lecteur : zoom, glisser, doubles pages (entières en paysage), aide
- Noms de séries avec « : » gardés ; import des archives aux noms accentués corrigé ; diverses corrections d'affichage

## Telegram : un sujet par appli
- Alerte Telegram « redémarrage inattendu » : si l'appli a planté ou si le serveur a redémarré, un message part dès qu'elle repart (avec les dernières erreurs du journal en cas de plantage) ; case à cocher dans ⚙️ Réglages
- Messages toujours visibles : quand un message apparaît hors de l'écran après un appui (en haut ou en bas de la page), il s'affiche aussi dans une bulle en bas de l'écran (kit commun `ui/mou-ui.js`)
- ⚙️ Réglages → Alertes Telegram : champ « Sujet du groupe » (groupe Telegram à sujets) et bouton « 🔎 Détecter le groupe et le sujet » ; vide = comportement d'avant (`TELEGRAM_THREAD_ID` dans `data/secrets.env`, propre à MouFlanga)

## Tomes
- Page d'une série : résumé de l'histoire (section « Synopsis » de Wikipédia en français, sinon MangaDex, sinon AniList en anglais), appui pour tout lire ; « ✏️ Renommer la série » dans le menu « ⋯ » (dossier, fichiers de tome, progression et couverture suivent)
- Comptage clair (« 50 tomes », « 43 tomes + 12 chapitres ») ; tomes complets et tomes à chapitres affichés dans l'ordre ; tailles en Go au-delà de 1 000 Mo, Mo arrondis ; pastille « xx à lire » retirée des couvertures
- Pendant un import ou un rangement, la page de la série se met à jour sans remonter en haut et ne te ramène plus dessus si tu vas ailleurs
- Télécharger : les séries trouvées par recherche restent dans la liste ; bouton « 📚 Charger tout le catalogue » (≈ 17 000 séries, 279 pages lues posément en 20 à 30 min, en arrière-plan, gardé un mois, progression et message Telegram) ; liste très longue affichée lettre par lettre
- Import et rangement : progression détaillée sur la page de la série (étape en cours, archive n sur m, tomes écrits, barre de progression)
- Mises à jour : le déploiement automatique attend la fin d'un import, d'un rangement ou d'un téléchargement avant de redémarrer l'appli (adresse interne /api/occupe, réservée au serveur)
- Japscan : séries rangées par volumes (« Volume 22 : FIN », adresse …/volume-22/) reconnues ; un volume téléchargé devient un fichier de tome complet, marqué « déjà téléchargé » si le tome est déjà là (avant, un faux lien piégé « Chapitre 755222 » apparaissait)
- Marque sur chaque couverture : ✅ Fini (série terminée, tout est là), ⚠ Incomplet (terminée mais il manque des tomes ou chapitres), 🔄 En cours, ⏸ En pause ; statut officiel lu sur AniList en arrière-plan (gardé 7 jours) ; la page de la série dit ce qui manque
- Page « 📦 Importer » (bandeau dans la bibliothèque) : les archives .rar/.zip/.7z déposées directement dans le dossier des mangas sont proposées une série par ligne (nom modifiable, archives d'une même série regroupées, série existante complétée) ; « Tout importer » les traite une à une en arrière-plan, message Telegram à la fin
- Import plus malin (appris de 72 vraies archives) : archives et PDF rangés dans l'archive ouverts aussi ; tomes sans le mot « tome » (« MAR.07 », « jojo13 », « volume-1 »), tome écrit dans le nom des images, one-shot, chapitres sans tome rangés ensuite d'après Internet ; suite ou artbook dans la même archive = série à part ; fichiers parasites ignorés ; outil de secours « unar » pour les RAR difficiles
- Téléchargement : bouton « 🔎 Chercher … dans tout Japscan » (ou touche Entrée) pour trouver une série qui n'est pas dans les sorties récentes ; résultats gardés 1 heure
- Téléchargement, étape 1 : une seule ligne par série (la page d'accueil de Japscan donnait plusieurs liens par série, souvent nommés « Chapitre … » ou « OFFICIEL »), en liste alphabétique avec une séparation par lettre, un index des lettres et une recherche (sans tenir compte des accents) ; un appui sur un nom ouvre ses chapitres
- Import : l'extraction des archives échouait sur le NAS (il refuse de redonner aux fichiers leur propriétaire d'origine, simple avertissement pris pour une erreur) ; plus de tentative de couverture sur une archive pas encore importée
- Telegram : sujet de groupe réglable en collant le lien d'un message du sujet (sans détection) ; message clair quand le bot est déjà branché sur une autre application (webhook, ex. Jeedom) ; le sujet « Général » (n° 1) est géré
- Import des séries ajoutées à la main : les grosses archives qui regroupent plusieurs tomes (.rar, .zip, .7z) sont extraites en arrière-plan et donnent un fichier par tome (avec les chapitres quand ils sont dans des dossiers séparés) ; les PDF sont convertis (images d'origine reprises sans perte) ; les originaux vont à la corbeille
- L'appli apprend de tes choix de noms (même dossier → même nom ; mots que tu retires) et met les majuscules (« nanatsu no taizai » → « Nanatsu no Taizai ») ; réglage « Organiser tout seul » dans ⚙️ Réglages
- Série ajoutée à la main (copiée directement dans le dossier des mangas) : bandeau « 🧹 Organiser » sur sa page ; propose un nom propre (« Gintama Integrale T01-77 [FR][CBZ] » → « Gintama », modifiable), range chaque tome complet dans « Tome NN/<Série> - Tome NN.cbz » (simples déplacements) et regroupe les chapitres en tomes ; progression et couverture gardées
- Tomes complets reconnus dans les noms de fichiers (« T01 », « Tome 1 », « Vol. 1 ») : affichés « Tome 01 · chapitres 1 à 8 », tomes manquants signalés, leurs chapitres comptés comme déjà téléchargés ; un tome complet n'est jamais réécrit
- Page d'une série allégée : titre et « ▶ Reprendre » à droite de la couverture ; appui sur la couverture pour la changer (image, MouFloster, automatique) ; « ⋯ » pour tout marquer lu / non lu, ranger en tomes, supprimer ; les chapitres manquants s'affichent tout seuls en une ligne, seulement s'il en manque
- Page d'une série : un appui sur le nom d'un tome ouvre ou ferme sa liste de chapitres (nombre de chapitres et de lus affiché) ; seul le tome en cours de lecture est ouvert au départ
- La répartition des chapitres en tomes est cherchée automatiquement sur Internet : Wikipédia (listes de chapitres, plusieurs mises en page reconnues) puis MangaDex en secours ; gardée 3 jours dans `data/tomes/`
- Rangement : un dossier « Tome NN » par tome avec **un seul .cbz** qui se complète à chaque chapitre téléchargé ; les chapitres pas encore sortis en tome vont dans « Hors tome » et rejoignent leur tome dès qu'il sort ; `ComicInfo.xml` dans chaque tome (lu par Komga, Kavita…)
- Titres : ceux de Japscan, ou ceux de Wikipédia quand Japscan n'en donne pas
- Page d'une série : chapitres groupés par tome ; bouton « 📚 Ranger en tomes » pour les séries déjà téléchargées (les anciens fichiers vont à la corbeille, la progression est gardée)
- Lecteur : passe d'un chapitre à l'autre, et d'un tome à l'autre, sans recharger ; en défilement, bouton « chapitre suivant » en bas ; la position est retenue par chapitre (elle ne bouge pas quand un tome est recomplété)
- Téléchargement : l'étape des tomes n'avait aucun effet ; elle est remplacée par un récapitulatif

## Couverture créée avec MouFloster
- Téléchargement : l'étape « Confirmer les tomes » (qui n'avait aucun effet) est remplacée par un récapitulatif : nombre de chapitres, lesquels, chapitres déjà présents, dossier de rangement
- Alertes Telegram : adresse perso ET adresse locale de l'appli (deux liens dans le message : de l'extérieur et chez soi)
- Deux adresses de MouFloster dans ⚙️ Réglages : réseau local et adresse perso (proxy) ; le bouton prend l'adresse locale quand on est connecté à MouFlanga en local (192.168…), l'adresse perso sinon
- Page d'une série : bouton « 🎨 Créer avec MouFloster » (si l'adresse de MouFloster est réglée) : MouFloster s'ouvre avec la recherche déjà faite, puis propose de revenir ici une fois la couverture envoyée
- ⚙️ Réglages → MouFloster : adresse de MouFloster et **clé API** générée par l'appli (montrée une seule fois, seule son empreinte est gardée) ; les autres applis l'utilisent pour lister les séries et envoyer une couverture (`/api/externe/…`, 10 mauvais essais → blocage 10 minutes)

## Couverture au choix et chapitres manquants
- Page d'une série : bouton « 🖼 Changer la couverture » (choisir une image ou une photo du téléphone, enregistrée en `cover.jpg` dans le dossier de la série) et « ↺ Couverture automatique » pour revenir à la 1re page du 1er chapitre ; l'ancienne couverture va à la corbeille
- Page d'une série : bouton « 🔍 Chapitres manquants » (trous dans la numérotation, ex. « 4–5, 8–9 »)
- Téléchargement : les chapitres déjà dans la bibliothèque sont marqués « ✓ déjà téléchargé » et décochés ; bouton « Cocher les manquants »
- Japscan : le nom de la série ne contient plus le numéro du dernier chapitre (« Dandadan » au lieu de « Dandadan 247 ») ; l'ancien dossier est renommé tout seul au prochain téléchargement, avec la progression de lecture

## Captchas groupés (essai)
- Page « Vérification » : pendant la première passe, elle indique combien de chapitres sont mis de côté et que leurs captchas arriveront à la fin (au lieu de « aucune vérification en attente »)
- Le compteur de captchas ne compte plus que ceux qu'il faut vraiment résoudre (un chapitre mis de côté puis résolu était compté deux fois)
- Nouvelle case « Captchas groupés » dans ⚙️ Réglages → Navigateur du scraper (désactivée par défaut) : les chapitres qui demandent un captcha sont gardés pour la fin du téléchargement, avec une seule alerte Telegram, puis on les fait à la suite
- Onglet « En cours » : nombre de chapitres qui attendent un captcha (avec le lien vers la page Vérification) et, à la fin, nombre total de captchas demandés ; même chiffre dans le rapport, pour comparer les deux modes

## Mémo complet pour Claude Code
- `docs/claude-opt.md` décrit maintenant toute la suite MouFl (la personne, les règles, le serveur, les quatre applis, le kit d'interface partagé, la façon de travailler)
- Il est recopié dans `/opt/CLAUDE.md` à chaque déploiement de MouFlanga et par `scripts/installer-claude-code.sh`, pour que Claude Code lancé sur le serveur connaisse tout dès le départ

## Suppression de mangas
- Alertes Telegram : une alerte part maintenant pour chaque captcha (avant, une alerte Cloudflare faisait taire toutes les suivantes pendant 15 minutes) ; seul le rappel pour une même page reste limité à un par quart d'heure
- Bibliothèque : bouton 🗑 sur chaque chapitre et bouton « Supprimer la série », avec confirmation
- Les fichiers supprimés vont dans un dossier caché `.corbeille` du dossier des mangas (rangés par jour) et sont effacés pour de bon au bout de 30 jours : on peut encore les récupérer en cas d'erreur
- Impossible de supprimer une série pendant son téléchargement ; la progression de lecture des chapitres supprimés est effacée

## Choix du navigateur : Chrome ou Camoufox
- Nouveau panneau « 🧭 Navigateur du scraper » dans ⚙️ Réglages : Google Chrome (par défaut) ou Camoufox (Firefox anti-détection, profil séparé), avec un bouton pour télécharger Camoufox ; si Camoufox ne démarre pas, retour automatique à Chrome
- Chrome : les adresses *.challenges.cloudflare.com sont redirigées vers IPv4 (le serveur n'a pas d'IPv6 et `brunhild.challenges.cloudflare.com` n'existe qu'en IPv6) ; avec Camoufox, la même redirection est écrite dans /etc/hosts si le serveur en a le droit
- Après la vérification, l'appli attend la vraie fiche série (page « Loading… ») avant de chercher les chapitres
- Rapport : historique des échecs réseau du défi, empreinte du navigateur, test DNS et test IPv6
- Téléchargement : l'onglet « ⏳ En cours » fonctionne enfin (liste des téléchargements, avancement, chapitre en cours, bouton Annuler) et reste à jour même après un rechargement de la page ou une vérification Cloudflare
- Pages des chapitres : essai réel réussi (63 pages sur 63, dans le bon ordre de la couverture à « Fin ») ; si le lecteur reste vide juste après un captcha, le chapitre est rechargé une fois au lieu de rendre 0 page
- Tests : deux tests ne dépendent plus des réglages du serveur (jeton Telegram d'une autre appli, dossier des mangas)
- Pages des chapitres : l'appli attend maintenant que toutes les pages annoncées par le lecteur soient arrivées (elle en prenait 4 sur 63 en lisant trop tôt) et « tourne la page » si le chargement s'arrête ; pause de 20 secondes environ entre deux chapitres (réglable avec JAPSCAN_PAUSE) pour limiter les captchas
- Claude Code sur le serveur : script `scripts/installer-claude-code.sh` et mémos `CLAUDE.md` / `docs/claude-opt.md` (règles et état du projet) pour piloter les applis directement depuis le conteneur
- Rapport : section « Carte graphique » (le serveur voit-il /dev/dri, les outils graphiques présents) et rendu WebGL annoncé par le navigateur, pour préparer l'usage de la puce Intel Iris Xe
- Pages des chapitres : elles sont maintenant rangées dans l'ordre où le lecteur les demande (les noms de fichiers du site sont des suites de lettres sans ordre) ; le rapport indique le nombre de pages annoncées et capturées
- Téléchargement : un seul navigateur pour tous les chapitres (au lieu d'un par chapitre) : plus rapide, et le site garde la même session
- Captcha sur téléphone : la capture se recadre automatiquement sur le captcha (zoom), les captures s'enchaînent sans attendre, et le glissement est rejoué d'un seul geste (beaucoup plus rapide)
- Page « Vérification » : on peut maintenant glisser le doigt sur l'image du navigateur du serveur (glisser-déposer), pour remettre en ordre les tranches d'un captcha
- La liste des mangas est gardée 6 heures en mémoire (bouton « 🔄 Actualiser la liste ») et les chapitres d'une série 1 heure : après une vérification, le retour sur la page Télécharger est instantané au lieu de relancer la lecture du site
- Captcha : détection corrigée (Camoufox ne laisse pas lire les variables de la page : on lit maintenant son contenu), ce qui déclenche enfin l'alerte et la page « Vérification »
- Lecteur de chapitres : le site affiche un captcha d'images avant les pages ; l'appli le détecte, met le téléchargement en pause, t'alerte sur Telegram et te laisse le résoudre depuis la page « Vérification » (qui a maintenant des boutons pour faire défiler la page)
- Rapport : description détaillée du lecteur de chapitres (sélecteur de page, boutons, zones de dessin) et essai de passage à la page suivante, pour comprendre comment le site affiche les pages
- Téléchargement : arrêt automatique après 3 chapitres de suite sans aucune page ; lecture des pages telles qu'affichées (canvas ou grandes images) en plus de la capture réseau ; le rapport décrit ce que contient la page du lecteur
- Téléchargement : les boutons « Retour / Suivant » restent collés en bas de l'écran, même au milieu d'une longue liste ; la page recharge maintenant son code à chaque nouvelle version (le navigateur gardait l'ancien, d'où « Tout décocher » sans effet)
- Téléchargement, étape 2 : le bouton « Suivant » restait grisé tant qu'on ne touchait pas une case ; ajout de « Tout cocher », « Tout décocher » et d'une plage « du chapitre … au … », avec le nombre de chapitres sélectionnés
- Fiche série : le site cache la vraie liste sous des leurres (liens cachés, faux « Chapitre 000001 » invisibles) ; l'appli ne lit plus que les éléments réellement visibles de chaque ligne de chapitre
- Fiche série : défilement de la page avant la lecture, et rapport enrichi (familles de liens, première zone « list_chapters », requêtes de données de la page) pour trouver où se cache la liste complète des chapitres

## Vérification Cloudflare à la main et alertes Telegram
- Cloudflare impose une vérification interactive sur les fiches série que le robot ne peut pas passer seul : le téléchargement se met maintenant en pause (10 minutes maximum) et attend l'utilisateur
- Nouvelle page « Vérification » : on voit le navigateur du serveur en direct et on clique dessus (ordinateur ou téléphone) ; le téléchargement reprend dès que c'est passé
- Les clics de vérification passent par la souris de l'écran virtuel (xdotool, installé par le déploiement) : leurs coordonnées d'écran sont cohérentes, ce que le clic d'automatisation ne permet pas et que Cloudflare repère ; retour au clic d'automatisation si xdotool manque ; le scraper tente de l'installer lui-même au premier besoin (une fois par heure au plus)
- Page « Vérification » plus claire : repère vert sur l'endroit du clic, réponse de Cloudflare affichée après chaque clic (titre de la page, autorisation reçue ou non), image plus légère et rafraîchie chaque seconde
- Le rapport de l'appli garde l'historique des vérifications (demande, clics et réponses du site, réussite ou échec) pour comprendre un blocage
- Alerte Telegram envoyée au moment du blocage (une fois toutes les 15 minutes au plus), avec le lien de la page ; bandeau d'avertissement aussi sur la page Télécharger
- Si une autre appli du serveur (sous `/opt`) utilise déjà Telegram, MouFlanga reprend ses réglages tout seul, en lecture seule, sans rien modifier chez elle ; ses propres réglages restent prioritaires
- Reprise Telegram plus large : le jeton est reconnu à sa forme dans les fichiers `.env`, `.json`, `.ini` et `.yml` des autres applis (quel que soit le nom de la clé) ; si l'identifiant manque, il est détecté tout seul à l'envoi
- Le rapport de l'appli contient une section « Telegram » (où l'appli a cherché, quelles clés ont été vues, aucune valeur secrète) ; la même liste est dans ⚙️ Réglages
- Réglages Telegram dans ⚙️ : jeton du bot, détection automatique de l'identifiant, adresse de l'appli, message de test ; le jeton reste dans `data/secrets.env`, n'apparaît jamais dans les journaux et n'est jamais renvoyé à la page
- Le scraper démarre lui-même un écran virtuel (Xvfb) si le service n'en a pas, pour que le navigateur marche aussi depuis l'appli
- Navigateur du scraper : rendu WebGL logiciel et fenêtre adaptée à l'écran virtuel

## Téléchargeur de mangas (Patchright)
- Correction de l'intégration : la liste, les chapitres et le téléchargement fonctionnent de nouveau depuis l'appli (la route des chapitres acceptait GET alors que la page envoie POST)
- L'appli démarre même si Patchright n'est pas installé
- Le service tourne sous écran virtuel (`xvfb-run`) ; le déploiement installe xvfb, Chromium (Patchright) et met à jour le fichier de service
- Attente de la fin du défi Cloudflare sur chaque page ; détection des chapitres propre à la série
- Noms de dossiers et de fichiers nettoyés (plus de `/` ni de `..` venant du site) ; filtre d'images moins agressif
- Contournement de Cloudflare sur les fiches série : profil de navigateur conservé, vrai Google Chrome installé par le déploiement, passage par la page d'accueil, clic automatique sur la case de vérification, fausse identité de navigateur retirée
- Ménage : anciens scripts de test Playwright et documents obsolètes supprimés

## 1.0
- Reconstruction complète de l'appli sur la base commune de la suite MouFl : connexion par identifiant et mot de passe haché, 🩺 Journal de diagnostic, ⚙️ Réglages identiques aux autres applis, explorateur de dossiers
- Bibliothèque par série avec couvertures, recherche, tri, suivi de lecture (chapitres lus, reprise à la page exacte)
- Lecteur : une page à la fois ou défilement, sens manga ou occidental, page entière ou largeur, plein écran, clavier et toucher
- Lecture des `.cbz`, des `.cbr` en ZIP et des vrais `.cbr` en RAR (avec un outil de décompression)
- Déploiement automatique par cron (GitHub vérifié chaque minute), installation en une commande
- Sécurité : lecture seule dans le dossier des mangas, chemins piégés et liens symboliques refusés
- Retrait de l'ancien code de l'appli, qui n'était pas protégé par une connexion
