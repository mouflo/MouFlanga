# Historique des versions

## Choix du navigateur : Chrome ou Camoufox
- Nouveau panneau « 🧭 Navigateur du scraper » dans ⚙️ Réglages : Google Chrome (par défaut) ou Camoufox (Firefox anti-détection, profil séparé), avec un bouton pour télécharger Camoufox ; si Camoufox ne démarre pas, retour automatique à Chrome
- Chrome : les adresses *.challenges.cloudflare.com sont redirigées vers IPv4 (le serveur n'a pas d'IPv6 et `brunhild.challenges.cloudflare.com` n'existe qu'en IPv6) ; avec Camoufox, la même redirection est écrite dans /etc/hosts si le serveur en a le droit
- Après la vérification, l'appli attend la vraie fiche série (page « Loading… ») avant de chercher les chapitres
- Rapport : historique des échecs réseau du défi, empreinte du navigateur, test DNS et test IPv6

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
