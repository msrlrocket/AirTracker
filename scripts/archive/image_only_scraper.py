#!/usr/bin/env python3
"""Image-only scraper to re-populate all military aircraft images"""

import json
import requests
import time
import random
import re
import os
from PIL import Image
from io import BytesIO
from datetime import datetime
from bs4 import BeautifulSoup
from urllib.parse import urljoin, urlparse

class ImageOnlyScraper:
    def __init__(self, zipline_url, zipline_token, folder_id="cmg5jdflb000s01mvpjgckdvk", debug=False):
        self.zipline_url = zipline_url
        self.zipline_token = zipline_token
        self.folder_id = folder_id
        self.debug = debug
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/91.0.4472.124 Safari/537.36'
        })
        self.request_count = 0
        self.start_time = time.time()

    def log(self, message):
        """Print debug message if debug mode is enabled"""
        if self.debug:
            print(f"🔍 {message}")

    def polite_delay(self, delay_type="default"):
        """Implement rate limiting with polite delays"""
        delays = {
            "search": 3.0,    # Longer delay for Military.com searches
            "image": 1.5,     # Medium delay for image downloads
            "upload": 1.0,    # Short delay for Zipline uploads
            "default": 2.0
        }

        delay = delays.get(delay_type, delays["default"])
        actual_delay = delay + random.uniform(0, 0.5)

        self.request_count += 1
        elapsed = time.time() - self.start_time
        rate = (self.request_count / elapsed * 60) if elapsed > 0 else 0

        self.log(f"💤 Polite delay: {actual_delay:.1f}s ({delay_type}) | Requests: {self.request_count} | Rate: {rate:.1f}/min")
        time.sleep(actual_delay)

    def search_military_com_for_aircraft(self, aircraft_name):
        """Search Military.com for a specific aircraft"""
        try:
            # Clean aircraft name for search
            search_name = re.sub(r'[^\w\s-]', '', aircraft_name)
            search_name = re.sub(r'\s+', ' ', search_name).strip()

            # Try direct Military.com search first
            search_url = f"https://www.military.com/equipment/military-aircraft"
            self.log(f"Searching Military.com for: {search_name}")

            self.polite_delay("search")
            response = self.session.get(search_url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Look for links that match the aircraft name
            aircraft_links = []
            for link in soup.find_all('a', href=True):
                href = link.get('href', '')
                link_text = link.get_text(strip=True).lower()

                if '/equipment/' in href and any(word in link_text for word in search_name.lower().split()):
                    full_url = urljoin(search_url, href)
                    aircraft_links.append(full_url)

            # Also try searching by aircraft model/nickname
            model_terms = self.extract_aircraft_identifiers(aircraft_name)
            for term in model_terms:
                term_lower = term.lower()
                for link in soup.find_all('a', href=True):
                    href = link.get('href', '')
                    link_text = link.get_text(strip=True).lower()

                    if '/equipment/' in href and term_lower in link_text:
                        full_url = urljoin(search_url, href)
                        if full_url not in aircraft_links:
                            aircraft_links.append(full_url)

            self.log(f"Found {len(aircraft_links)} potential aircraft pages")
            return aircraft_links[:3]  # Limit to first 3 matches

        except Exception as e:
            self.log(f"Error searching for {aircraft_name}: {e}")
            return []

    def extract_aircraft_identifiers(self, aircraft_name):
        """Extract key identifiers from aircraft name for search"""
        identifiers = []

        # Common aircraft designations
        designations = re.findall(r'[A-Z]{1,2}-?\d+[A-Z]*', aircraft_name)
        identifiers.extend(designations)

        # Common nicknames
        nicknames = [
            'warthog', 'thunderbolt', 'eagle', 'hornet', 'raptor', 'lightning',
            'apache', 'cobra', 'viper', 'chinook', 'black hawk', 'seahawk',
            'hercules', 'galaxy', 'globemaster', 'stratofortress', 'lancer',
            'spirit', 'osprey', 'predator', 'reaper', 'global hawk'
        ]

        name_lower = aircraft_name.lower()
        for nickname in nicknames:
            if nickname in name_lower:
                identifiers.append(nickname)

        # Manufacturer names
        manufacturers = ['boeing', 'lockheed', 'northrop', 'grumman', 'bell', 'sikorsky', 'mcdonnell', 'douglas']
        for mfg in manufacturers:
            if mfg in name_lower:
                identifiers.append(mfg)

        return identifiers

    def scrape_images_from_page(self, url, aircraft_name):
        """Scrape images from a Military.com aircraft page"""
        try:
            self.log(f"Scraping images from: {url}")
            self.polite_delay("search")

            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            images = []

            # Look for high-quality images
            img_tags = soup.find_all('img', src=True)

            for img in img_tags:
                src = img.get('src')
                if not src:
                    continue

                # Convert relative URLs to absolute
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = urljoin(url, src)

                # Filter for actual aircraft images
                if self.is_valid_aircraft_image(src, aircraft_name):
                    width = img.get('width', 0)
                    height = img.get('height', 0)
                    alt_text = img.get('alt', '')

                    try:
                        width = int(width) if width else 0
                        height = int(height) if height else 0
                    except:
                        width = height = 0

                    images.append({
                        'url': src,
                        'width': width,
                        'height': height,
                        'alt_text': alt_text,
                        'source_page': url
                    })

            # Sort by image size (prefer larger images)
            images.sort(key=lambda x: x['width'] * x['height'], reverse=True)
            self.log(f"Found {len(images)} valid aircraft images")

            return images[:2]  # Return top 2 images

        except Exception as e:
            self.log(f"Error scraping {url}: {e}")
            return []

    def is_valid_aircraft_image(self, img_url, aircraft_name):
        """Check if an image URL appears to be a valid aircraft photo"""
        img_url_lower = img_url.lower()
        aircraft_lower = aircraft_name.lower()

        # Skip obvious non-aircraft images
        skip_patterns = [
            'logo', 'icon', 'banner', 'ad', 'advertisement', 'social',
            'facebook', 'twitter', 'youtube', 'thumbnail', 'avatar',
            'profile', 'button', 'arrow', 'search', 'menu', 'header',
            'footer', 'sidebar', 'widget', 'badge', 'flag', 'generic'
        ]

        if any(pattern in img_url_lower for pattern in skip_patterns):
            return False

        # Must be from Military.com images or known aircraft photo sites
        valid_domains = [
            'military.com/sites/default/files',
            'images.military.com',
            'cdn.military.com'
        ]

        if not any(domain in img_url_lower for domain in valid_domains):
            return False

        # Check for minimum reasonable dimensions in URL (if specified)
        if re.search(r'(\d+)x(\d+)', img_url):
            match = re.search(r'(\d+)x(\d+)', img_url)
            if match:
                w, h = int(match.group(1)), int(match.group(2))
                if w < 200 or h < 150:  # Too small
                    return False

        # Look for aircraft-related keywords in the URL
        aircraft_indicators = [
            'aircraft', 'plane', 'fighter', 'bomber', 'helicopter', 'jet',
            'military', 'aviation', 'air-force', 'navy', 'marines'
        ]

        # Extract aircraft model from name for URL matching
        model_match = re.search(r'([A-Z]{1,2}-?\d+[A-Z]*)', aircraft_name)
        if model_match:
            aircraft_indicators.append(model_match.group(1).lower().replace('-', ''))

        return any(indicator in img_url_lower for indicator in aircraft_indicators)

    def download_and_process_image(self, image_url, aircraft_name):
        """Download image and create both original and ESP32-optimized versions"""
        try:
            self.log(f"Downloading image: {image_url}")
            self.polite_delay("image")

            response = self.session.get(image_url, timeout=30)
            response.raise_for_status()

            # Open and process the image
            original_image = Image.open(BytesIO(response.content))

            # Convert to RGB if necessary
            if original_image.mode in ('RGBA', 'LA', 'P'):
                original_image = original_image.convert('RGB')

            # Create high-resolution version (1200x800)
            original_resized = original_image.copy()
            original_resized.thumbnail((1200, 800), Image.Resampling.LANCZOS)

            # Create ESP32-optimized version (96x72, 24-bit BMP)
            esp32_image = original_image.copy()
            esp32_image.thumbnail((96, 72), Image.Resampling.LANCZOS)

            # Save to memory
            original_bytes = BytesIO()
            original_resized.save(original_bytes, format='JPEG', quality=90, optimize=True)
            original_bytes.seek(0)

            esp32_bytes = BytesIO()
            esp32_image.save(esp32_bytes, format='BMP')
            esp32_bytes.seek(0)

            return original_bytes, esp32_bytes, original_resized.size

        except Exception as e:
            self.log(f"Error processing image {image_url}: {e}")
            return None, None, None

    def upload_to_zipline(self, image_data, filename, is_bmp=False):
        """Upload image to Zipline and return the URL"""
        try:
            self.log(f"Uploading to Zipline: {filename}")
            self.polite_delay("upload")

            upload_url = f"{self.zipline_url}/api/upload"

            files = {
                'file': (filename, image_data, 'image/bmp' if is_bmp else 'image/jpeg')
            }

            data = {
                'folder': self.folder_id,
                'expires': '',
                'password': '',
                'maxViews': '',
                'zeroWidth': 'false'
            }

            headers = {
                'Authorization': self.zipline_token
            }

            response = requests.post(upload_url, files=files, data=data, headers=headers, timeout=60)
            response.raise_for_status()

            result = response.json()

            if 'files' in result and len(result['files']) > 0:
                uploaded_file = result['files'][0]
                return uploaded_file.get('url', '')
            else:
                self.log(f"Upload failed: {result}")
                return None

        except Exception as e:
            self.log(f"Upload error for {filename}: {e}")
            return None

    def scrape_aircraft_images(self, aircraft_name):
        """Complete image scraping pipeline for one aircraft"""
        self.log(f"Starting image scraping for: {aircraft_name}")

        # Search for aircraft pages
        aircraft_pages = self.search_military_com_for_aircraft(aircraft_name)

        if not aircraft_pages:
            self.log(f"No pages found for {aircraft_name}")
            return None

        # Try each page until we find good images
        for page_url in aircraft_pages:
            images = self.scrape_images_from_page(page_url, aircraft_name)

            if images:
                # Try to process the best image
                best_image = images[0]
                original_bytes, esp32_bytes, size = self.download_and_process_image(
                    best_image['url'], aircraft_name
                )

                if original_bytes and esp32_bytes:
                    # Create safe filenames
                    safe_name = re.sub(r'[^\w\s-]', '', aircraft_name).replace(' ', '_')

                    # Upload both versions
                    original_filename = f"{safe_name}_original.jpg"
                    esp32_filename = f"{safe_name}_esp32.bmp"

                    original_url = self.upload_to_zipline(original_bytes, original_filename, False)
                    esp32_url = self.upload_to_zipline(esp32_bytes, esp32_filename, True)

                    if original_url and esp32_url:
                        return {
                            "original_url": best_image['url'],
                            "zipline_url": original_url,
                            "zipline_esp32_url": esp32_url,
                            "width": size[0] if size else best_image['width'],
                            "height": size[1] if size else best_image['height'],
                            "esp32_width": 96,
                            "esp32_height": 72,
                            "alt_text": best_image['alt_text'],
                            "source_page": best_image['source_page'],
                            "processed_at": datetime.now().isoformat()
                        }

        return None

    def process_all_aircraft(self):
        """Process all 122 aircraft in the dataset"""
        print("🚁 Starting complete image re-scraping for all military aircraft...")

        # Load current dataset
        with open('../mqtt/unified/datasets/military_aircraft_final.json', 'r') as f:
            data = json.load(f)

        print(f"📊 Processing {len(data['aircraft'])} aircraft...")

        successful_updates = 0
        failed_aircraft = []

        for i, aircraft in enumerate(data['aircraft'], 1):
            print(f"\n🔍 Processing {i}/{len(data['aircraft'])}: {aircraft['name']}")

            # Scrape images for this aircraft
            image_data = self.scrape_aircraft_images(aircraft['name'])

            if image_data:
                aircraft['images'] = [image_data]
                successful_updates += 1
                print(f"  ✅ Images updated successfully")
                print(f"    Original: {image_data['zipline_url']}")
                print(f"    ESP32: {image_data['zipline_esp32_url']}")
            else:
                failed_aircraft.append(aircraft['name'])
                aircraft['images'] = []
                print(f"  ❌ Failed to find/process images")

            # Save progress periodically
            if i % 10 == 0:
                print(f"💾 Saving progress... ({i}/{len(data['aircraft'])})")
                self.save_dataset(data, successful_updates, len(data['aircraft']))

        # Final save
        self.save_dataset(data, successful_updates, len(data['aircraft']))

        print(f"\n✅ Image scraping completed!")
        print(f"📊 Successfully updated: {successful_updates}/{len(data['aircraft'])} aircraft")
        print(f"📊 Success rate: {successful_updates/len(data['aircraft'])*100:.1f}%")

        if failed_aircraft:
            print(f"\n❌ Failed aircraft ({len(failed_aircraft)}):")
            for name in failed_aircraft[:10]:  # Show first 10
                print(f"  • {name}")
            if len(failed_aircraft) > 10:
                print(f"  ... and {len(failed_aircraft) - 10} more")

        if successful_updates == len(data['aircraft']):
            print(f"\n🎉 100% IMAGE COVERAGE ACHIEVED! 🎉")
            print(f"All {len(data['aircraft'])} military aircraft now have fresh images!")

    def save_dataset(self, data, successful_count, total_count):
        """Save the dataset with current progress"""
        # Update metadata
        data['metadata']['aircraft_with_images'] = successful_count
        data['metadata']['last_updated'] = datetime.now().isoformat()
        data['metadata']['version'] = '1.6'
        data['metadata']['image_completion'] = f"{successful_count}/{total_count} ({successful_count/total_count*100:.1f}%)"

        # Save updated dataset
        with open('../mqtt/unified/datasets/military_aircraft_final.json', 'w') as f:
            json.dump(data, f, indent=2)

        # Update JSONL too
        with open('../mqtt/unified/datasets/military_aircraft_final.jsonl', 'w') as f:
            for aircraft in data['aircraft']:
                f.write(json.dumps(aircraft) + '\n')

def main():
    import os

    zipline_url = os.getenv('ZIPLINE_URL', 'https://zip.spacegeese.com')
    zipline_token = os.getenv('ZIPLINE_TOKEN')

    if not zipline_token:
        print("❌ ZIPLINE_TOKEN environment variable not set")
        return

    scraper = ImageOnlyScraper(zipline_url, zipline_token, debug=True)
    scraper.process_all_aircraft()

if __name__ == '__main__':
    main()