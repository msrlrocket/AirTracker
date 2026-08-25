#!/usr/bin/env python3
"""Test the scraper with a single known aircraft URL."""

from military_aircraft_scraper import MilitaryAircraftScraper
import json

def test_single_aircraft():
    """Test the MH-65 Dolphin specifically."""
    scraper = MilitaryAircraftScraper(debug=True)

    # Test the known MH-65 Dolphin URL
    test_url = "https://www.military.com/equipment/mh-65-dolphin"

    print(f"Testing single aircraft extraction: {test_url}")
    aircraft_info = scraper.extract_aircraft_info(test_url)

    if aircraft_info:
        print("\n✅ Successfully extracted aircraft info!")
        print(f"Name: {aircraft_info.get('name')}")
        print(f"Specifications: {len(aircraft_info.get('specifications', {}))}")
        print(f"Images: {len(aircraft_info.get('images', []))}")
        print(f"Description length: {len(aircraft_info.get('description', ''))}")

        # Print specifications
        print("\n📊 Specifications:")
        for key, value in aircraft_info.get('specifications', {}).items():
            print(f"  {key}: {value}")

        # Print image URLs
        print(f"\n🖼️  Images:")
        for i, image in enumerate(aircraft_info.get('images', [])[:5], 1):  # First 5 images
            # Handle both old and new image formats
            if 'original_url' in image:
                # New processed format
                print(f"  {i}. Original: {image['original_url']}")
                if image.get('original_zipline_url'):
                    print(f"     Zipline Original: {image['original_zipline_url']}")
                if image.get('esp32_bmp_zipline_url'):
                    print(f"     Zipline ESP32 BMP: {image['esp32_bmp_zipline_url']}")
                if image.get('alt_text'):
                    print(f"     Alt: {image['alt_text']}")
            else:
                # Old format
                print(f"  {i}. {image.get('url', 'No URL')}")
                if image.get('alt_text'):
                    print(f"     Alt: {image['alt_text']}")

        # Save to file
        with open('test_mh65_dolphin.json', 'w') as f:
            json.dump(aircraft_info, f, indent=2)
        print(f"\n💾 Saved detailed data to test_mh65_dolphin.json")

    else:
        print("❌ Failed to extract aircraft info")

if __name__ == "__main__":
    test_single_aircraft()