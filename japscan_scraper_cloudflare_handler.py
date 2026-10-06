#!/usr/bin/env python3
"""
Enhanced _fetch_with_browser() method with Cloudflare challenge handling.

This module provides an improved version of the _fetch_with_browser() method
that detects and bypasses Cloudflare's "Just a moment..." challenge by:
1. Loading the page
2. Detecting Cloudflare challenge in HTML
3. Waiting 10 seconds
4. Reloading the page to allow Cloudflare to verify the connection
5. Returning the final HTML

USAGE:
------
Once probe_wait_cloudflare.py confirms this approach works, replace the
_fetch_with_browser() method in JapscanScraper class with the enhanced
version from this module.

The change is minimal - just update the method in japscan_scraper.py:

    def _fetch_with_browser(self, url: str) -> str | None:
        \"\"\"Utilise Playwright pour charger une page HTML (contourne Cloudflare).\"\"\"
        browser = self._get_browser()
        if not browser:
            logger.warning(f"Playwright indisponible, utilise requests pour {url}")
            return self._fetch(url)

        try:
            page = browser.new_page()
            page.set_default_timeout(PLAYWRIGHT_TIMEOUT)

            # Masquer la présence de Playwright (anti-détection)
            page.add_init_script(\"\"\"
                Object.defineProperty(navigator, 'webdriver', {
                    get: () => false,
                });
            \"\"\")

            logger.info(f"Playwright: chargement {url}")
            response = page.goto(url, wait_until="networkidle")
            status = response.status if response else "Unknown"

            html = page.content()

            # Détecte et gère le challenge Cloudflare
            if "just a moment" in html.lower():
                logger.info(f"Challenge Cloudflare détecté sur {url}")
                logger.info("Attente de 10 secondes pour résolution...")
                import time
                time.sleep(10)

                logger.info("Rechargement de la page...")
                response = page.reload(wait_until="networkidle")
                status = response.status if response else "Unknown"
                html = page.content()

                if "just a moment" in html.lower():
                    logger.warning(f"Challenge Cloudflare toujours présent après attente")
                else:
                    logger.info(f"✓ Challenge Cloudflare résolu ({len(html)} chars)")
            else:
                logger.info(f"Playwright: page chargée ({len(html)} chars)")

            page.close()
            return html

        except Exception as e:
            logger.error(f"Erreur Playwright {url}: {e}")
            try:
                page.close()
            except:
                pass
            # Fallback à requests
            return self._fetch(url)
"""
