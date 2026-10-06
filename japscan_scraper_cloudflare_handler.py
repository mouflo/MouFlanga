#!/usr/bin/env python3
"""
Méthode _fetch_with_browser() améliorée avec gestion du défi Cloudflare.

Ce module fournit une version améliorée de la méthode _fetch_with_browser()
qui détecte et contourne le défi "Just a moment..." de Cloudflare en :
1. Chargeant la page
2. Détectant le défi Cloudflare dans le HTML
3. Attendant 10 secondes
4. Rechargeant la page pour permettre à Cloudflare de vérifier la connexion
5. Retournant le HTML final

UTILISATION :
-------------
Une fois que probe_wait_cloudflare.py confirme que cette approche fonctionne,
remplace la méthode _fetch_with_browser() dans la classe JapscanScraper par
la version améliorée de ce module.

Le changement est minimal - juste mettre à jour la méthode dans japscan_scraper.py :

    def _fetch_with_browser(self, url: str) -> str | None:
        \"\"\"Utilise Playwright pour charger une page HTML (contourne Cloudflare).\"\"\"
        navigateur = self._get_browser()
        if not navigateur:
            logger.warning(f"Playwright indisponible, utilise requests pour {url}")
            return self._fetch(url)

        try:
            page = navigateur.new_page()
            page.set_default_timeout(PLAYWRIGHT_TIMEOUT)

            # Masquer la présence de Playwright (anti-détection)
            page.add_init_script(\"\"\"
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false,
                });
            \"\"\")

            logger.info(f"Playwright : chargement {url}")
            response = page.goto(url, wait_until="networkidle")
            statut = response.status if response else "Inconnu"

            html = page.content()

            # Détecte et gère le défi Cloudflare
            if "just a moment" in html.lower():
                logger.info(f"Défi Cloudflare détecté sur {url}")
                logger.info("Attente de 10 secondes pour résolution...")
                import time
                time.sleep(10)

                logger.info("Rechargement de la page...")
                response = page.reload(wait_until="networkidle")
                statut = response.status if response else "Inconnu"
                html = page.content()

                if "just a moment" in html.lower():
                    logger.warning(f"Défi Cloudflare toujours présent après attente")
                else:
                    logger.info(f"✓ Défi Cloudflare résolu ({len(html)} caractères)")
            else:
                logger.info(f"Playwright : page chargée ({len(html)} caractères)")

            page.close()
            return html

        except Exception as e:
            logger.error(f"Erreur Playwright {url} : {e}")
            try:
                page.close()
            except:
                pass
            # Fallback vers requests
            return self._fetch(url)
"""
