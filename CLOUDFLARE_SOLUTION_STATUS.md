# Solution Cloudflare - État actuel

## Vue d'ensemble
Le scraper Japscan est bloqué par le défi "Just a moment..." de Cloudflare sur les pages de chapitres individuelles (URLs comme `/manga/dandadan/247/`). On teste une approche attente + rechargement pour le contourner.

## Architecture actuelle

```
Flux des requêtes (Actuel) :
├─ Liste mangas (/) → ✓ Fonctionne (543 trouvés)
├─ Liste chapitres (/manga/x) → ✗ 403 Bloqué par Cloudflare
└─ Pages chapitres (/manga/x/chapitres/y) → ✗ 403 Bloqué par Cloudflare

Pile de protection Cloudflare :
├─ Détection headless=True → 403 Forbidden
├─ Détection webdriver Playwright → 403 Forbidden
└─ Défi "Just a moment..." → blocage temporaire
```

## Approche de solution : Attendre & Recharger

**Hypothèse** : Cloudflare renvoie un défi initial qui se résout après attente et rechargement.

**Implémentation** : Trois phases

### Phase 1 : Test de diagnostic (En cours)
- **Fichier** : `probe_wait_cloudflare.py` ✓ Créé et poussé
- **État** : En attente du déploiement auto et exécution
- **Localisation serveur** : `/opt/mouflanga/probe_wait_cloudflare.py`
- **Comment le lancer** : 
  ```bash
  cd /opt/mouflanga && xvfb-run -a python3 probe_wait_cloudflare.py
  ```
- **Ce qu'il fait** :
  1. Lance le navigateur avec `headless=False` via Xvfb
  2. Ajoute du JavaScript anti-détection
  3. Charge la page chapitre
  4. Détecte le défi "just a moment"
  5. Attend 10 secondes
  6. Recharge la page
  7. Vérifie si le défi a disparu
  8. Liste les images en cas de succès

### Phase 2 : Intégration (Prête à déployer)
- **Fichier** : `japscan_scraper_cloudflare_handler.py` ✓ Créé et poussé
- **État** : En attente du succès de la Phase 1 pour activation
- **À faire** : Une fois que `probe_wait_cloudflare.py` réussit :
  1. Copier la méthode améliorée `_fetch_with_browser()` de ce fichier
  2. Remplacer la méthode dans `japscan_scraper.py`
  3. Mettre à jour le lancement du navigateur pour utiliser `headless=False + Xvfb`
  4. Re-tester le pipeline complet

### Phase 3 : Déploiement en production
- Mettre à jour l'interface Flask pour wrapper les appels avec `xvfb-run`
- Tester le flux complet : liste mangas → obtenir chapitres → télécharger pages
- Créer les fichiers CBR avec succès

## Fichiers engagés

| Fichier | État | Objectif |
|---------|------|---------|
| `probe_wait_cloudflare.py` | Poussé | Test de diagnostic pour l'approche attente + rechargement |
| `TEST_CLOUDFLARE_WAIT.md` | Poussé | Guide de test avec résultats attendus |
| `japscan_scraper_cloudflare_handler.py` | Poussé | Méthode améliorée prête pour intégration |
| `setup-xvfb.sh` | Déjà sur serveur | Installeur Xvfb + dépendances |

## État de l'infrastructure

- ✓ Xvfb installé sur serveur
- ✓ playwright-stealth installé
- ✓ Binaires Chromium présents
- ✓ Toutes dépendances satisfaites
- ⏳ En attente des résultats du test `probe_wait_cloudflare.py`

## Ce qui se passe ensuite

### Si le test RÉUSSIT ✓
1. On a la solution !
2. Intégrer `japscan_scraper_cloudflare_handler.py` dans le scraper principal
3. Mettre à jour la stratégie de lancement dans `_get_browser()` pour utiliser headless=False + Xvfb
4. Relancer `test_scraper.py` pour valider le pipeline complet
5. Mettre à jour l'interface Flask si nécessaire
6. Marquer comme résolu

### Si le test ÉCHOUE ✗
1. L'attente + rechargement ne fonctionne pas
2. Essayer l'alternative : `undetected-chromium`
3. Créer `probe_undetected.py` pour tester
4. Considérer : services proxy, découverte d'API, ou approches manuelles

## Calendrier des tests

- **T+0** : Déploiement auto du serveur `probe_wait_cloudflare.py` (dans ~5 minutes)
- **T+5m** : Tu peux lancer le test manuellement ou attendre cron
- **T+15m** : Les résultats doivent être disponibles

## Comment surveiller le déploiement auto

Le serveur vérifie GitHub toutes les quelques minutes via cron. Tu peux :
1. Attendre le déploiement auto (passif)
2. Pull manuel : `cd /opt/mouflanga && git pull origin main`
3. Lancer les tests immédiatement après le pull

## Blocages actuels

Aucun - toute l'infrastructure de diagnostic est en place. Juste besoin d'exécuter le test.

## Notes

- Tous les fichiers sonde utilisent `xvfb-run -a python3 <script>` pour fournir un affichage X virtuel
- La logique attente + rechargement est non-bloquante (simple `time.sleep(10)`)
- Fallback vers `requests` en cas d'échec Playwright (maintient la robustesse)
- Options de lancement du navigateur adaptées à l'environnement Linux headless

## Commandes pour l'exécution serveur

```bash
# Surveiller le déploiement auto
watch -n 5 'ls -la /opt/mouflanga/ | grep probe_wait'

# Pull latest
cd /opt/mouflanga && git pull origin main

# Lancer le test de diagnostic
xvfb-run -a python3 probe_wait_cloudflare.py

# Voir les logs du test
cat /opt/mouflanga/logs/*.log  # si logging configuré

# Test pipeline complet (après intégration)
xvfb-run -a python3 test_scraper.py
```

## Arbre de décision

```
Résultat du test ?
├─ SUCCÈS (images trouvées, pas de défi CF)
│  └─ Intégrer cloudflare_handler dans le scraper
│     └─ Mettre à jour _get_browser() pour headless=False + Xvfb
│        └─ Re-tester le pipeline complet
│           └─ PRÊT POUR LA PRODUCTION ✓
│
└─ ÉCHEC (défi CF persiste)
   └─ Essayer l'approche undetected-chromium
      ├─ Créer probe_undetected.py
      ├─ Test : pip install undetected-chromedriver
      └─ Si ça marche : intégrer, sinon chercher alternatives
```
