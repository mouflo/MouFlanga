# MouFlanga : notes pour Claude Code

Lis aussi `/opt/CLAUDE.md` si présent (règles communes à toutes les applis : français partout, pas de sudo, pas de secret sur GitHub, prévenir avant un push pendant un traitement long).

## Ce que c'est
Appli Flask (bibliothèque et lecteur de mangas) + scraper Japscan. Dossier `/opt/mouflanga`, service `mouflanga.service`, déploiement automatique par cron (chaque minute). Réglages et secrets dans `data/` (`data/secrets.env`, jamais sur GitHub).

## Tests
`python -m unittest discover -s tests` (doit rester vert avant tout push). Journal : `journalctl -u mouflanga`. Le bouton « Rapport » de l'appli résume l'état (vérification Cloudflare, DNS, carte graphique, derniers événements).

## Le scraper Japscan (`japscan_scraper.py`)
- Navigateur au choix dans ⚙ Réglages : Chrome (Patchright, profil `data/navigateur`) ou Camoufox (Firefox, profil `data/navigateur-firefox`), sous écran virtuel Xvfb ; clics réels avec xdotool.
- Cloudflare impose une vérification interactive : la page `/verification` montre le navigateur du serveur (capture) et relaie clics, défilement et glisser du doigt ; alerte Telegram.
- `brunhild.challenges.cloudflare.com` n'existe qu'en IPv6 et le serveur n'a pas d'IPv6 : redirection vers IPv4 (option du navigateur ou ligne `# MouFlanga-cloudflare` dans `/etc/hosts`). AdGuard Home (DNS 192.168.1.139) doit laisser passer les domaines Cloudflare.
- Fiche série : le site cache la vraie liste de chapitres sous des leurres (liens `d-none`, faux « Chapitre 000001 » invisibles par `clip-path`). On ne lit que les éléments réellement visibles (`_JS_ZONES_VISIBLES`) ; l'adresse d'un chapitre est `/manga/<série>/<numéro>/`.
- Lecteur : un captcha d'images (tranches à remettre en ordre en glissant) peut s'afficher avant les pages ; détecté par le contenu de la page (Camoufox cache les variables `window`), résolu **à la main** par l'utilisateur. Ne pas chercher à le résoudre automatiquement.
- Pages : capturées sur le réseau (images de `c4.japscan.foo`), rangées dans l'ordre où le lecteur les demande (les noms de fichiers n'ont pas d'ordre). L'exactitude de cet ordre est à confirmer avec le rapport (ligne « arrivée(s) dans un autre ordre »).
- Un seul navigateur sert à tout un téléchargement ; arrêt automatique après 3 chapitres de suite sans page ; onglet « En cours » avec bouton Annuler.
- Liste des mangas gardée 6 h (`data/mangas-japscan.json`), chapitres 1 h en mémoire.

## À faire / pistes
- Confirmer l'ordre des pages dans les CBZ ; comprendre quand le site redemande un captcha (le rapport note la « mémoire du site »).
- Utiliser la puce graphique Intel Iris Xe du conteneur (`/dev/dri`) : le rapport a une section « Carte graphique » ; Xvfb n'utilise aucune carte graphique, il faudrait changer d'affichage.
- Mettre à jour les captures d'écran du README pour la grosse mise à jour Japscan.
