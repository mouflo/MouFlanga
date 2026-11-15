# MouFlanga : ce qui reste, en tâches simples

Liste écrite le 15/11/2026, à la fin de la refonte « tout automatique ». Chaque tâche est petite, indépendante, et peut être
faite par un modèle moins puissant. Les tâches difficiles sont à part, tout en bas : ne pas les donner à un petit modèle.

## Règles à respecter pour chaque tâche
- Lire `/opt/CLAUDE.md` et `/opt/mouflanga/CLAUDE.md` d'abord. Tout en français.
- Une tâche = un commit. Tests avant de pousser : `cd /opt/mouflanga && venv/bin/python -m unittest discover -s tests`.
- Jamais d'écriture dans `data/` ni dans la bibliothèque pendant un essai (dossier jetable, `MOUFLANGA_TEST=1`).
- Ne pas toucher au kit partagé (`ui/mou-ui.*`, `ui/mou-settings.*`, `fs_browser.py`).
- Regarder la page à 390 px de large (Chromium du serveur) avant de dire que c'est fait.
- Avant `systemctl restart mouflanga` : `curl -s http://127.0.0.1:5002/api/occupe` doit dire `false`, et
  `/api/automatisations` ne doit pas avoir de tome en cours.
- Ajouter une ligne en tête de « ## [Non publié] » dans `CHANGELOG.md`.

## A. Textes et libellés (très facile)
1. **Onglet 🧲 Torrents, phrase d'introduction** (`templates/telecharger.html`) : « Recherche dans tes indexeurs Prowlarr… catégorie
   « mouflanga » » est du jargon. La remplacer par une phrase simple (« Cherche un manga ; le tome choisi se télécharge et se range
   tout seul dans ta bibliothèque. »).
2. **Mot « profil » dans les messages** : depuis « ✨ Mes préférences », les messages qui disent « Profil : « … » » ou « Aucun profil
   pour cette série » (`ui/torrents.js` vers la ligne 124, messages Telegram de `suivi.py`, fiche d'une série dans `ui/mouflanga.js`)
   doivent dire « Règle : … » / « Tes préférences ». Chercher avec `grep -n "rofil" ui/*.js suivi.py app.py`. Ne changer que les
   textes affichés, pas les noms de variables ni les clés JSON.
3. **`/opt/mouflanga/CLAUDE.md`** dit encore « déploiement automatique par cron (chaque nuit à 5 h) » : c'est faux depuis le
   03/11/2026. Corriger la phrase (plus de déploiement automatique, redémarrage à la main après un push).
4. **README** : ajouter un paragraphe sur 🤖 Automatisations, ✨ Mes préférences et la grille de couvertures des tomes
   (le texte est déjà dans `CHANGELOG.md`, il suffit de le résumer).

## B. Petits défauts d'affichage (facile)
5. **Onglet 🧲 Torrents : « Comparé à ta bibliothèque » écrit deux fois** à 390 px (une bulle par-dessus la ligne). Trouver d'où
   vient la seconde (`ui/torrents.js`, fonction qui affiche les résultats ; chercher « Comparé à ta bibliothèque ») et n'en garder qu'une.
6. **Lecteur plein écran** (`templates/lecteur.html`) : pas de lien direct vers l'accueil (seulement « ← Retour » vers la série).
   Ajouter un petit bouton 🏠 dans sa barre du haut. Ne pas ajouter l'en-tête du kit (le lecteur doit rester plein écran).
7. **Édition de chaque tome dans la liste des tomes** : la fiche dit « 📖 T1–T12 Édition originale · T13–T35 autre édition » en une
   ligne (`s.edition.editions_tomes`) ; afficher aussi une petite marque sur chaque tome « autre édition » dans la grille `.tcarte`
   et dans la liste (`ui/mouflanga.js`).
8. **Pages jamais revues à 390 px depuis la refonte** : `/importer`, `/verification`, `/couvertures`, `/couvertures/lot`,
   `/decouper`, `/historique-allegement`, ⚙️ Réglages. Pour chacune : pas de défilement horizontal, boutons d'au moins 44 px de haut,
   champs en 16 px. Corriger seulement le CSS de la page.
9. **Panneau ✨ → 🎨 Uniformité, bouton « 🤖 Tout faire d'un coup »** : l'API est testée mais le panneau n'a jamais été regardé dans
   un navigateur. Le regarder à 390 px sur données jetables et corriger ce qui dépasse.
10. **Captures d'écran** (`docs/screenshots`) : à refaire (accueil, fiche avec la grille de couvertures, ✨ Mes préférences,
    Télécharger → Torrents, ⚙️ Réglages → 🤖 Automatisations), sur données de démonstration, jamais sur la vraie bibliothèque.

## C. Petites fonctions (facile à moyen)
11. **Onglet 🧪 Essayer de la page Règles** : ajouter en tête la même phrase « ⭐ Tes préférences : … » que sur la page Télécharger
    (`regles_simples.phrase`, déjà passée au gabarit sous le nom `phrase_simple`).
12. **Bouton « Revenir à mes anciennes règles »** sur ✨ Mes préférences : désactive le profil `simple` et réactive les profils
    généraux que `regles_simples.enregistrer` avait désactivés (il faut d'abord noter leurs identifiants dans le profil simple,
    champ à ajouter, par exemple `desactives`). Avec un test dans `tests/test_regles_simples.py`.
13. **Garde-fou « autre découpage »** : `mon_edition.nb_pages` ne compte pas les pages d'un `.cbr`. Les compter avec `bsdtar -tf`
    (déjà utilisé ailleurs dans l'appli), avec un test.
14. **Fichier `deploy.sh`** : il ne sert plus (déploiement automatique supprimé le 03/11/2026). Le retirer du dépôt et des
    documents qui en parlent (`README.md`, `INSTALL.md`), après avoir vérifié qu'aucun code ne l'appelle (`grep -rn deploy.sh`).

## D. À faire par l'utilisatrice (rien à coder)
- Enregistrer ✨ Mes préférences (page Règles) : tant que ce n'est pas fait, ses anciennes règles servent.
- ⚙️ Réglages → 🤖 Automatisations → « Rattraper ma bibliothèque » (environ 9 nuits de travail).
- Cocher « Uniformiser aussi les prochains tomes » dans les séries où elle le veut.
- Remplir ✏️ Mon édition pour Rave (18 tomes, adresse de la page Glénat du tome 1).

## Difficile : à garder pour le modèle le plus capable
- **Téléchargement 100 % automatique des remplacements** (scan → officiel) par série : touche à `suivi.py`,
  `auto_telechargement.py`, `torrents.py`, garde-fous d'édition, corbeille ; une erreur remplace de bons tomes.
- **Édition devinée sans lien d'éditeur** (ISBN → BnF) : règles de fer de `docs/identification.md`.
- **Fiabilité des chapitres** au-delà de 92 % (`chapitres_auto.py`, `sommaire.py`) : chaque changement se mesure sur le banc
  `outils/banc_sommaires.py`, plafond mémoire obligatoire.
- Fait le 16/11/2026 : séries suivies renommées (`suivi._recaler`), chapitre en double entre deux tomes signalé (`chapitres_auto._doublons_entre_tomes`).
