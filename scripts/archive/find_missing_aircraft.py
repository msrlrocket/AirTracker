#!/usr/bin/env python3
"""Find the 2 missing aircraft and scrape them."""

import json
import os
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import random
from datetime import datetime
from io import BytesIO
from PIL import Image
import re

def get_all_aircraft_urls():
    """Get all 112 aircraft URLs from the 27 categories."""
    categories = [
        ('Air Force Aircraft', 'https://www.military.com/equipment/air-force-aircraft'),
        ('Air Force Attack Aircraft', 'https://www.military.com/equipment/air-force-attack-aircraft'),
        ('Air Force Fighters', 'https://www.military.com/equipment/air-force-fighters'),
        ('Air Force Helicopters', 'https://www.military.com/equipment/air-force-helicopters'),
        ('Army Aircraft', 'https://www.military.com/equipment/army-aircraft'),
        ('Army Helicopters', 'https://www.military.com/equipment/army-helicopters'),
        ('Attack Aircraft', 'https://www.military.com/equipment/attack-aircraft'),
        ('Bombers', 'https://www.military.com/equipment/bombers'),
        ('Coast Guard Aircraft', 'https://www.military.com/equipment/coast-guard-aircraft'),
        ('Coast Guard Helicopters', 'https://www.military.com/equipment/coast-guard-helicopters'),
        ('Drones', 'https://www.military.com/equipment/drones'),
        ('Fighter Aircraft', 'https://www.military.com/equipment/fighter-aircraft'),
        ('Helicopters', 'https://www.military.com/equipment/helicopters'),
        ('Marine Corps Aircraft', 'https://www.military.com/equipment/marine-corps-aircraft'),
        ('Marine Corps Attack Aircraft', 'https://www.military.com/equipment/marine-corps-attack-aircraft'),
        ('Marine Corps Fighters', 'https://www.military.com/equipment/marine-corps-fighters'),
        ('Marine Corps Helicopters', 'https://www.military.com/equipment/marine-corps-helicopters'),
        ('Navy Aircraft', 'https://www.military.com/equipment/navy-aircraft'),
        ('Navy Attack Aircraft', 'https://www.military.com/equipment/navy-attack-aircraft'),
        ('Navy Fighters', 'https://www.military.com/equipment/navy-fighters'),
        ('Navy Helicopters', 'https://www.military.com/equipment/navy-helicopters'),
        ('Special Operations Aircraft', 'https://www.military.com/equipment/special-operations-aircraft'),
        ('Special Mission Aircraft', 'https://www.military.com/equipment/special-mission-aircraft'),
        ('Surveillance Aircraft', 'https://www.military.com/equipment/surveillance-aircraft'),
        ('Tanker Aircraft', 'https://www.military.com/equipment/tanker-aircraft'),
        ('Trainer Aircraft', 'https://www.military.com/equipment/trainer-aircraft'),
        ('Transport Aircraft', 'https://www.military.com/equipment/transport-aircraft')
    ]

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    })

    all_aircraft = []

    for i, (category_name, category_url) in enumerate(categories, 1):
        print(f"🗂️  Category {i}/{len(categories)}: {category_name}")

        page_num = 0
        while True:
            if page_num == 0:
                page_url = category_url
            else:
                separator = '&' if '?' in category_url else '?'
                page_url = f"{category_url}{separator}_wrapper_format=html&page={page_num}"

            try:
                response = session.get(page_url, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')

                page_aircraft_count = 0
                links = soup.find_all('a', href=True)

                for link in links:
                    href = link.get('href')
                    if not href:
                        continue

                    if href.startswith('/'):
                        href = urljoin('https://www.military.com', href)

                    if 'military.com' not in href:
                        continue

                    skip_patterns = [
                        '/equipment/air-force-', '/equipment/army-', '/equipment/navy-',
                        '/equipment/marine-corps-', '/equipment/coast-guard-',
                        '/equipment/attack-aircraft', '/equipment/bombers', '/equipment/fighters',
                        '/equipment/helicopters', '/equipment/drones', '/equipment/transport-aircraft',
                        '/equipment/tanker-aircraft', '/equipment/trainer-aircraft', '/equipment/surveillance-aircraft',
                        '/equipment/special-', '/news/', '/benefits/', '/military-life/',
                        '?page=', '&page=', '#', 'javascript:', 'mailto:'
                    ]

                    if any(pattern in href for pattern in skip_patterns):
                        continue

                    if '/equipment/' in href and href not in [item['url'] for item in all_aircraft]:
                        aircraft_name = link.get_text(strip=True)
                        if not aircraft_name:
                            aircraft_name = href.split('/')[-1].replace('-', ' ').title()

                        aircraft_info = {
                            'url': href,
                            'name': aircraft_name,
                            'source_category': category_name,
                            'source_category_url': category_url
                        }
                        all_aircraft.append(aircraft_info)
                        page_aircraft_count += 1

                # Check pagination
                has_next = False
                pagination_links = soup.find_all('a', href=True)
                for link in pagination_links:
                    href = link.get('href', '')
                    link_text = link.get_text().strip().lower()
                    if ('next' in link_text or f'page={page_num + 1}' in href):
                        has_next = True
                        break

                if page_aircraft_count == 0 or not has_next:
                    break

                page_num += 1
                time.sleep(2)

            except Exception as e:
                print(f"  ❌ Error: {e}")
                break

        time.sleep(3)

    # Remove duplicates
    unique_aircraft = {}
    for aircraft in all_aircraft:
        url = aircraft['url']
        if url not in unique_aircraft:
            unique_aircraft[url] = aircraft

    return list(unique_aircraft.values())

def main():
    # Get all discovered aircraft
    print("🔍 Discovering all aircraft URLs...")
    all_aircraft = get_all_aircraft_urls()
    discovered_urls = {aircraft['url'] for aircraft in all_aircraft}

    print(f"📊 Total discovered: {len(discovered_urls)} aircraft")

    # Get processed aircraft from progress file
    with open('military_aircraft_progress.json', 'r') as f:
        progress = json.load(f)

    processed_urls = {aircraft['url'] for aircraft in progress['aircraft']}
    print(f"📊 Total processed: {len(processed_urls)} aircraft")

    # Find missing URLs
    missing_urls = discovered_urls - processed_urls
    print(f"📊 Missing: {len(missing_urls)} aircraft")

    if missing_urls:
        print("\\n🔍 Missing aircraft URLs:")
        for i, url in enumerate(missing_urls, 1):
            print(f"  {i}. {url}")

        # Save missing URLs for manual inspection
        with open('missing_aircraft_urls.json', 'w') as f:
            json.dump(list(missing_urls), f, indent=2)

        print(f"\\n💾 Missing URLs saved to missing_aircraft_urls.json")
    else:
        print("\\n✅ No missing aircraft found!")

if __name__ == '__main__':
    main()