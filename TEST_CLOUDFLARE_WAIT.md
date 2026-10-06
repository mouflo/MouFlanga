# Test : Résolution du défi Cloudflare par attente

## Hypothèse
Cloudflare renvoie un défi initial "Just a moment..." qui se résout après ~10 secondes d'attente et rechargement.

## Prérequis
- Xvfb installé : `apt-get install xvfb`
- playwright-stealth installé : `pip install --break-system-packages playwright-stealth`
- Vérifier avec : `playwright install chromium` (si nécessaire)

## Lancer le test

Sur ton serveur Proxmox :

```bash
cd /opt/mouflanga
xvfb-run -a python3 probe_wait_cloudflare.py
```

## Résultat attendu

### Si SUCCÈS ✓
```
✓ SUCCÈS ! Page chargée sans Cloudflare !
✓ Titre: ...
✓ Images trouvées: N
```

L'attente + rechargement contourne Cloudflare. Prochaine étape : intégrer dans `japscan_scraper.py`

### Si ÉCHEC ✗
```
✗ Cloudflare toujours présent
```

Le défi Cloudflare persiste malgré l'attente. Prochaine étape : essayer `undetected-chromium` ou autres approches.

## Ce que fait ce test

1. Lance Playwright avec `headless=False` via Xvfb (simule un vrai navigateur)
2. Ajoute du JavaScript anti-détection pour masquer webdriver
3. Charge la page chapitre : `https://www.japscan.foo/manga/dandadan/247/`
4. Détecte "just a moment" dans le HTML (marqueur du défi Cloudflare)
5. Attend 10 secondes avec compte à rebours
6. Appelle `page.reload()` pour une nouvelle réponse
7. Vérifie si le défi Cloudflare a disparu
8. Liste les images trouvées en cas de succès

## Fichiers concernés
- **probe_wait_cloudflare.py** : La sonde de diagnostic
- **setup-xvfb.sh** : Script d'installation (déjà exécuté)
- **japscan_scraper.py** : Scraper principal (solution sera intégrée ici après validation)

## Prochaines étapes après le test

- **Si SUCCÈS** : 
  1. Mettre à jour `japscan_scraper.py` pour utiliser attente + rechargement dans `_fetch_with_browser()`
  2. Tester le pipeline complet : liste mangas → chapitres → pages
  3. Mettre à jour l'interface Flask pour supporter le wrapper xvfb-run

- **Si ÉCHEC** :
  1. Installer undetected-chromium : `pip install undetected-chromedriver`
  2. Créer `probe_undetected.py` pour tester l'approche spécialisée
  3. Évaluer d'autres solutions (services proxy, découverte API)
