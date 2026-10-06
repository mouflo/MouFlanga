#!/usr/bin/env python3
"""
Script de diagnostic pour Japscan avec Playwright.
Charge la page avec un navigateur réel pour contourner le blocage 403.
"""
from playwright.sync_api import sync_playwright
from bs4 import BeautifulSoup
import json

def probe_with_playwright():
    """Probe japscan.foo avec Playwright pour contourner 403."""

    print(f"\n{'='*70}")
    print("Probe Japscan avec Playwright (contourne 403 Forbidden)")
    print('='*70)

    try:
        with sync_playwright() as p:
            print("Lancement du navigateur Chromium...")
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.set_default_timeout(30000)

            # Essaie plusieurs endpoints
            endpoints = ["/mangas/", "/listing", "/series", "/"]

            for endpoint in endpoints:
                url = f"https://www.japscan.foo{endpoint}"
                print(f"\nEssai: {url}")

                try:
                    response = page.goto(url, wait_until="networkidle")
                    status = response.status if response else "Unknown"
                    print(f"✓ Status: {status}")

                    if status == 200:
                        html = page.content()
                        print(f"✓ Page chargée! ({len(html)} caractères)")

                        # Sauvegarde le HTML
                        filename = f"/tmp/japscan{endpoint.replace('/', '_')}.html"
                        with open(filename, "w") as f:
                            f.write(html)
                        print(f"✓ HTML sauvegardé: {filename}")

                        # Analyse avec BeautifulSoup
                        analyze_html(html, endpoint)
                        break
                except Exception as e:
                    print(f"✗ Erreur: {e}")

            browser.close()
            print("\n✓ Navigateur fermé")

    except Exception as e:
        print(f"❌ Erreur fatale: {e}")
        import traceback
        traceback.print_exc()

def analyze_html(html: str, endpoint: str):
    """Analyse le HTML pour trouver les bons sélecteurs."""
    soup = BeautifulSoup(html, "html.parser")

    print(f"\n{'='*70}")
    print(f"ANALYSE DU HTML ({endpoint})")
    print('='*70)

    # Titre de la page
    title = soup.find("title")
    if title:
        print(f"\nTitre de la page: {title.get_text()}")

    # Tous les liens
    print(f"\n{'='*70}")
    print("LIENS (premiers 30):")
    print('='*70)
    link_count = 0
    for link in soup.find_all("a"):
        href = link.get("href", "")
        text = link.get_text(strip=True)
        classes = " ".join(link.get("class", []))
        if text and len(text) > 2:
            print(f"  [{link_count}] '{text[:40]}' → {href[:50]}")
            if classes:
                print(f"       Classes: {classes}")
            link_count += 1
            if link_count >= 30:
                break

    # DIVs avec classes
    print(f"\n{'='*70}")
    print("DIVs AVEC CLASSES (premiers 20):")
    print('='*70)
    div_count = 0
    for div in soup.find_all("div"):
        classes = div.get("class", [])
        if classes:
            text_preview = div.get_text(strip=True)[:80]
            class_str = " ".join(classes)
            if text_preview:
                print(f"  [{div_count}] div.{class_str}")
                print(f"       Texte: {text_preview}")
                div_count += 1
                if div_count >= 20:
                    break

    # Test des sélecteurs courants
    print(f"\n{'='*70}")
    print("TEST DES SÉLECTEURS CSS COURANTS:")
    print('='*70)

    selectors = [
        "div.manga-item",
        "div.serie",
        "div.manga",
        "a.manga",
        "a.serie",
        ".manga-link",
        ".serie-link",
        "article",
        "div.col",
        "div.card",
        "div[class*='manga']",
        "div[class*='serie']",
        "a[href*='/manga/']",
        "a[href*='/serie/']",
        "li.manga",
        "li.serie",
        "div.item",
        "div.entry",
    ]

    for selector in selectors:
        matches = soup.select(selector)
        if matches:
            print(f"\n  ✓ Sélecteur '{selector}' → {len(matches)} matches")
            # Affiche le premier
            first = matches[0]
            text = first.get_text(strip=True)[:60]
            href = first.get("href", "")
            print(f"    Premier: '{text}'")
            if href:
                print(f"    Href: {href[:70]}")

            # Affiche les classes
            classes = first.get("class", [])
            if classes:
                print(f"    Classes: {' '.join(classes)}")

if __name__ == "__main__":
    probe_with_playwright()
