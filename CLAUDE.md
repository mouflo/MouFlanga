# MouFlanga : notes pour Claude Code

Lis aussi `/opt/CLAUDE.md` si présent (règles communes à toutes les applis : français partout, pas de sudo, pas de secret sur GitHub, prévenir avant un push pendant un traitement long).

## Ce que c'est
Appli Flask (bibliothèque et lecteur de mangas) + scraper Japscan. Dossier `/opt/mouflanga`, service `mouflanga.service`, déploiement automatique par cron (chaque minute). Réglages et secrets dans `data/` (`data/secrets.env`, jamais sur GitHub).

## Avant de redémarrer MouFlanga
`curl -s http://127.0.0.1:5002/api/occupe` doit répondre `"occupe": false` (import, rangement, téléchargement). deploy.sh fait la même vérification et reporte la mise à jour sinon. Ne pas se fier seulement à la présence de bsdtar/navigateur : l'écriture des tomes n'en utilise pas.

## Tests
`python -m unittest discover -s tests` (doit rester vert avant tout push). Journal : `journalctl -u mouflanga`. Le bouton « Rapport » de l'appli résume l'état (vérification Cloudflare, DNS, carte graphique, derniers événements).

## Où trouver quoi
Détails dans `docs/mouflanga-details.md` (grep sur le mot-clé) : **Bibliothèque** (suppression, couvertures, séries Japscan, génériques, comptes, demandes, édition, torrents, séries suivies, accès des autres applis, lot du 12/10/2026) · **Liste Japscan** · **Tomes** (`tomes.py`, `tomes_cbz.py`, rangement, import, statut officiel) · **Scraper Japscan** (Cloudflare, captcha à la main, pages) · **À faire / pistes**. Règles qui comptent : ne jamais contourner une protection anti-bot (Japscan, Nautiljon, Booknode, manga-sanctuary refusés), ne jamais toucher aux données d'une série à la main (corriger le code), fichiers liés à qBittorrent jamais renommés.

