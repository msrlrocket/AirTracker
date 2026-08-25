#!/usr/bin/env python3
"""Complete the missing 2 aircraft and update the final dataset."""

import json
import os
import sys
import requests
from bs4 import BeautifulSoup
from urllib.parse import urljoin
import time
import random
from datetime import datetime
from io import BytesIO
from PIL import Image
import re

def download_image(session, url):
    """Download image from URL and return bytes."""
    try:
        response = session.get(url, timeout=30)
        response.raise_for_status()
        return response.content
    except Exception as e:
        print(f"❌ Error downloading image {url}: {e}")
        return None

def convert_to_esp32_bmp(image_bytes):
    """Convert image to ESP32-compatible BMP format (96x72, 24-bit)."""
    try:
        with Image.open(BytesIO(image_bytes)) as img:
            if img.mode != 'RGB':
                img = img.convert('RGB')

            img.thumbnail((96, 72), Image.Resampling.LANCZOS)
            final_img = Image.new('RGB', (96, 72), (0, 0, 0))
            paste_x = (96 - img.width) // 2
            paste_y = (72 - img.height) // 2
            final_img.paste(img, (paste_x, paste_y))

            output = BytesIO()
            final_img.save(output, format='BMP')
            return output.getvalue()
    except Exception as e:
        print(f"❌ Error converting image to ESP32 BMP: {e}")
        return None

def upload_to_zipline(image_bytes, filename, zipline_url, zipline_token):
    """Upload image to Zipline and return the URL."""
    try:
        files = {'file': (filename, image_bytes)}
        data = {'folderId': 'cmg5jdflb000s01mvpjgckdvk'}
        headers = {'Authorization': zipline_token}

        response = requests.post(
            f"{zipline_url}/api/upload",
            files=files,
            data=data,
            headers=headers,
            timeout=30
        )
        response.raise_for_status()

        result = response.json()
        return result.get('url', result.get('files', [{}])[0].get('url'))
    except Exception as e:
        print(f"❌ Error uploading {filename} to Zipline: {e}")
        return None

def process_aircraft_images(session, soup, aircraft_name, zipline_url, zipline_token):
    """Extract and process images from aircraft page."""
    images = []
    img_tags = soup.find_all('img')
    processed_count = 0

    for img in img_tags:
        if processed_count >= 3:
            break

        src = img.get('src')
        if not src:
            continue

        if src.startswith('//'):
            src = 'https:' + src
        elif src.startswith('/'):
            src = urljoin('https://www.military.com', src)

        # Skip invalid image types
        skip_indicators = ['thumb', 'icon', 'logo', 'badge', '.svg', 'data:', 'search-arrow', 'placeholder']
        if any(indicator in src.lower() for indicator in skip_indicators):
            continue

        # Check image dimensions
        width = img.get('width')
        height = img.get('height')
        if width and height:
            try:
                if int(width) < 300 or int(height) < 200:
                    continue
            except (ValueError, TypeError):
                pass

        print(f"  📸 Processing image: {src}")
        original_bytes = download_image(session, src)
        if not original_bytes:
            continue

        # Get image metadata
        try:
            with Image.open(BytesIO(original_bytes)) as pil_img:
                img_width, img_height = pil_img.size
        except:
            img_width, img_height = 0, 0

        if img_width < 300 or img_height < 200:
            continue

        # Upload original image to Zipline
        safe_aircraft_name = re.sub(r'[^\w\-]', '_', aircraft_name)
        original_filename = f"military_{safe_aircraft_name}_{processed_count + 1}_original.jpg"
        original_zipline_url = upload_to_zipline(original_bytes, original_filename, zipline_url, zipline_token)

        # Convert to ESP32 BMP format
        esp32_bmp_bytes = convert_to_esp32_bmp(original_bytes)
        esp32_zipline_url = None
        if esp32_bmp_bytes:
            esp32_filename = f"military_{safe_aircraft_name}_{processed_count + 1}_esp32.bmp"
            esp32_zipline_url = upload_to_zipline(esp32_bmp_bytes, esp32_filename, zipline_url, zipline_token)

        image_info = {
            'original_url': src,
            'original_zipline_url': original_zipline_url,
            'esp32_bmp_zipline_url': esp32_zipline_url,
            'alt_text': img.get('alt', ''),
            'title': img.get('title', ''),
            'width': img_width,
            'height': img_height,
            'processed_at': datetime.now().isoformat()
        }

        images.append(image_info)
        processed_count += 1
        time.sleep(0.5)

    print(f"  ✅ Processed {len(images)} images for {aircraft_name}")
    return images

def extract_specifications(soup):
    """Extract aircraft specifications from the page."""
    specs = {}

    # Look for specification tables
    spec_tables = soup.find_all(['table', 'dl', 'div'], class_=re.compile(r'spec|detail|info'))

    for table in spec_tables:
        rows = table.find_all(['tr', 'dt', 'div'])
        for row in rows:
            if row.name == 'tr':
                cells = row.find_all(['td', 'th'])
                if len(cells) >= 2:
                    key = cells[0].get_text(strip=True)
                    value = cells[1].get_text(strip=True)
                    if key and value:
                        specs[key] = value
            elif row.name == 'dt':
                key = row.get_text(strip=True)
                dd = row.find_next_sibling('dd')
                if dd:
                    value = dd.get_text(strip=True)
                    if key and value:
                        specs[key] = value

    # Also look for common specification patterns in text
    text_content = soup.get_text()
    spec_patterns = {
        r'Manufacturer[:\s]*([^\n]+)': 'Manufacturer',
        r'Service[:\s]*([^\n]+)': 'Service',
        r'Max Speed[:\s]*([^\n]+)': 'Max Speed',
        r'Range[:\s]*([^\n]+)': 'Range',
        r'Armament[:\s]*([^\n]+)': 'Armament',
        r'Crew[:\s]*([^\n]+)': 'Crew',
        r'Max Load[:\s]*([^\n]+)': 'Max Load'
    }

    for pattern, spec_name in spec_patterns.items():
        match = re.search(pattern, text_content, re.IGNORECASE)
        if match and spec_name not in specs:
            specs[spec_name] = match.group(1).strip()

    return specs

def scrape_aircraft(url, session, zipline_url, zipline_token):
    """Scrape a single aircraft."""
    try:
        print(f"🛩️  Scraping aircraft: {url}")
        response = session.get(url, timeout=30)
        response.raise_for_status()

        soup = BeautifulSoup(response.content, 'html.parser')

        # Extract aircraft name
        aircraft_name = "Unknown Aircraft"
        title_tag = soup.find('title')
        if title_tag:
            aircraft_name = title_tag.get_text().split('|')[0].strip()

        h1_tags = soup.find_all('h1')
        for h1 in h1_tags:
            text = h1.get_text(strip=True)
            if text and len(text) < 100:
                aircraft_name = text
                break

        aircraft_name = re.sub(r'\s+', ' ', aircraft_name).strip()
        print(f"  📝 Aircraft name: {aircraft_name}")

        # Extract specifications
        specifications = extract_specifications(soup)

        # Process images
        images = process_aircraft_images(session, soup, aircraft_name, zipline_url, zipline_token)

        # Extract description
        description = ""
        content_areas = soup.find_all(['div', 'section'], class_=re.compile(r'content|body|article|main'))
        for area in content_areas:
            paragraphs = area.find_all('p')
            if paragraphs:
                description = ' '.join([p.get_text(strip=True) for p in paragraphs[:2]])
                break

        if not description:
            paragraphs = soup.find_all('p')
            if paragraphs:
                description = paragraphs[0].get_text(strip=True)

        # Determine category based on URL characteristics
        category = "Unknown"
        if 'greyhound' in url:
            category = "Navy Aircraft"
        elif 'stinger' in url or 'ac-130' in url:
            category = "Air Force Aircraft"

        aircraft_data = {
            'name': aircraft_name,
            'url': url,
            'scraped_at': datetime.now().isoformat(),
            'specifications': specifications,
            'images': images,
            'description': description,
            'aliases': [],
            'category': category
        }

        return aircraft_data

    except Exception as e:
        print(f"❌ Error processing {url}: {e}")
        return None

def main():
    # Configuration
    zipline_url = os.getenv('ZIPLINE_URL', 'https://zip.spacegeese.com')
    zipline_token = os.getenv('ZIPLINE_TOKEN')

    if not zipline_token:
        print("❌ ZIPLINE_TOKEN environment variable not set")
        sys.exit(1)

    missing_urls = [
        'https://www.military.com/equipment/c-2a-greyhound',
        'https://www.military.com/equipment/ac-130w-stinger-ii'
    ]

    session = requests.Session()
    session.headers.update({
        'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
    })

    print("🔧 Scraping missing aircraft...")

    new_aircraft = []
    for url in missing_urls:
        aircraft_data = scrape_aircraft(url, session, zipline_url, zipline_token)
        if aircraft_data:
            new_aircraft.append(aircraft_data)
        time.sleep(2)

    # Load existing progress data
    with open('military_aircraft_progress.json', 'r') as f:
        progress_data = json.load(f)

    print(f"\\n📊 Adding {len(new_aircraft)} aircraft to dataset...")

    # Add new aircraft to the main list
    progress_data['aircraft'].extend(new_aircraft)

    # Add to categories
    for aircraft in new_aircraft:
        category = aircraft['category']
        if category not in progress_data['categories']:
            progress_data['categories'][category] = {
                'description': f"Aircraft from {category} category page",
                'aircraft': [],
                'total_aircraft': 0
            }

        progress_data['categories'][category]['aircraft'].append(aircraft)
        progress_data['categories'][category]['total_aircraft'] = len(progress_data['categories'][category]['aircraft'])

    # Update metadata
    progress_data['total_aircraft_processed'] = len(progress_data['aircraft'])
    progress_data['progress'] = f"{progress_data['total_aircraft_processed']}/{progress_data['total_aircraft_discovered']} (100.0%)"
    progress_data['scraped_at'] = datetime.now().isoformat()

    # Save updated dataset as complete file
    with open('../mqtt/unified/datasets/military_aircraft_complete.json', 'w') as f:
        json.dump(progress_data, f, indent=2)

    print(f"\\n✅ Complete! Updated dataset saved:")
    print(f"📊 Total aircraft: {progress_data['total_aircraft_processed']}/{progress_data['total_aircraft_discovered']} (100%)")
    print(f"📁 Saved to: military_aircraft_complete.json")

    # Show what we added
    print(f"\\n🆕 Added aircraft:")
    for aircraft in new_aircraft:
        print(f"  • {aircraft['name']} ({aircraft['category']})")
        print(f"    Images: {len(aircraft['images'])}")
        print(f"    Specs: {len(aircraft['specifications'])}")

if __name__ == '__main__':
    main()