#!/usr/bin/env python3
"""
Diagnostic script to probe Japscan and find correct selectors.
Run this on your server to discover the actual HTML structure.
"""
import requests
from bs4 import BeautifulSoup
import json

def probe_listing():
    """Probe the japscan listing page and show HTML structure."""
    url = "https://www.japscan.foo/listing"

    print(f"\n{'='*70}")
    print(f"Probing: {url}")
    print('='*70)

    try:
        resp = requests.get(url, timeout=10)
        print(f"Status: {resp.status_code}")
        print(f"Final URL: {resp.url}")
        print(f"Content length: {len(resp.text)} chars")

        soup = BeautifulSoup(resp.text, "html.parser")

        # Show page title
        title = soup.find("title")
        if title:
            print(f"\nPage title: {title.get_text()}")

        # Save full HTML for inspection
        with open("/tmp/japscan_listing.html", "w") as f:
            f.write(resp.text)
        print(f"\nFull HTML saved to /tmp/japscan_listing.html")

        # Find ALL elements with text (could be mangas)
        print("\n" + "="*70)
        print("LINKS with text content (first 30):")
        print("="*70)
        link_count = 0
        for link in soup.find_all("a"):
            href = link.get("href", "")
            text = link.get_text(strip=True)
            classes = " ".join(link.get("class", []))
            if text and len(text) > 2:  # Skip empty/short links
                print(f"  Text: '{text[:50]}' | Href: '{href[:60]}' | Classes: '{classes}'")
                link_count += 1
                if link_count >= 30:
                    break

        # Find divs with specific patterns
        print("\n" + "="*70)
        print("DIVs with classes (first 20):")
        print("="*70)
        div_count = 0
        for div in soup.find_all("div"):
            classes = div.get("class", [])
            if classes:
                text_preview = div.get_text(strip=True)[:60]
                class_str = ".".join(classes)
                if text_preview:
                    print(f"  div.{class_str}: '{text_preview}'")
                    div_count += 1
                    if div_count >= 20:
                        break

        # Try common manga site patterns
        print("\n" + "="*70)
        print("Testing common CSS selectors:")
        print("="*70)

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
            "li.manga",
            "li.serie",
        ]

        for selector in selectors:
            matches = soup.select(selector)
            if matches:
                print(f"  ✓ Selector '{selector}' found {len(matches)} matches")
                # Show first match
                if matches:
                    first = matches[0]
                    text = first.get_text(strip=True)[:50]
                    href = first.get("href", "")
                    print(f"    → First: '{text}' | href: '{href}'")

    except Exception as e:
        print(f"Error: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    probe_listing()
