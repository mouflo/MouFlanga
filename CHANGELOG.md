# Historique des versions

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
