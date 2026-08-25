#!/usr/bin/env python3
"""Test the browser scraper with a few sample aircraft"""

import os
from browser_image_scraper import BrowserImageScraper

def test_browser_scraper():
    zipline_url = os.getenv('ZIPLINE_URL', 'https://zip.spacegeese.com')
    zipline_token = os.getenv('ZIPLINE_TOKEN')

    if not zipline_token:
        print("❌ ZIPLINE_TOKEN environment variable not set")
        return

    scraper = BrowserImageScraper(zipline_url, zipline_token, debug=True)

    # Test with a few popular aircraft
    test_aircraft = [
        "Fairchild Republic A-10 Thunderbolt II",
        "Lockheed Martin F-22 Raptor",
        "Boeing AH-64 Apache"
    ]

    print("🧪 Testing browser-based scraper with sample aircraft...")

    for aircraft_name in test_aircraft:
        print(f"\n🔍 Testing: {aircraft_name}")
        result = scraper.scrape_aircraft_images(aircraft_name)

        if result:
            print(f"  ✅ Success!")
            print(f"    Original: {result['zipline_url']}")
            print(f"    ESP32: {result['zipline_esp32_url']}")
            print(f"    Source: {result['source_page']}")
        else:
            print(f"  ❌ Failed to get images")

        print("  Waiting before next test...")
        import time
        time.sleep(5)  # Be polite

    print("\n✅ Browser scraper test completed!")

if __name__ == '__main__':
    test_browser_scraper()