#!/usr/bin/env python3
"""Browser-based image scraper that simulates real browser behavior to get Wikipedia images"""

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
from urllib.parse import urljoin, urlparse, quote

class BrowserImageScraper:
    def __init__(self, zipline_url, zipline_token, folder_id="cmg5jdflb000s01mvpjgckdvk", debug=False):
        self.zipline_url = zipline_url
        self.zipline_token = zipline_token
        self.folder_id = folder_id
        self.debug = debug
        self.session = requests.Session()

        # Simulate a real browser with proper headers
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,image/apng,*/*;q=0.8',
            'Accept-Language': 'en-US,en;q=0.9',
            'Accept-Encoding': 'gzip, deflate, br',
            'DNT': '1',
            'Connection': 'keep-alive',
            'Upgrade-Insecure-Requests': '1',
            'Sec-Fetch-Dest': 'document',
            'Sec-Fetch-Mode': 'navigate',
            'Sec-Fetch-Site': 'none',
            'Sec-Fetch-User': '?1',
            'Cache-Control': 'max-age=0'
        })

    def log(self, message):
        """Print debug message if debug mode is enabled"""
        if self.debug:
            print(f"🔍 {message}")

    def search_wikipedia_for_aircraft(self, aircraft_name):
        """Search Wikipedia for aircraft and find the article page"""
        try:
            # Clean the aircraft name for Wikipedia search
            search_name = aircraft_name.replace(" ", "_")

            # Try direct Wikipedia page first
            wiki_urls = [
                f"https://en.wikipedia.org/wiki/{quote(search_name)}",
                f"https://en.wikipedia.org/wiki/{quote(aircraft_name)}",
            ]

            # Also try common aircraft name variations
            if "Thunderbolt" in aircraft_name:
                wiki_urls.append("https://en.wikipedia.org/wiki/Fairchild_Republic_A-10_Thunderbolt_II")
            if "Raptor" in aircraft_name:
                wiki_urls.append("https://en.wikipedia.org/wiki/Lockheed_Martin_F-22_Raptor")
            if "Lightning" in aircraft_name:
                wiki_urls.append("https://en.wikipedia.org/wiki/Lockheed_Martin_F-35_Lightning_II")
            if "Apache" in aircraft_name:
                wiki_urls.append("https://en.wikipedia.org/wiki/Boeing_AH-64_Apache")
            if "Black Hawk" in aircraft_name:
                wiki_urls.append("https://en.wikipedia.org/wiki/Sikorsky_UH-60_Black_Hawk")
            if "Chinook" in aircraft_name:
                wiki_urls.append("https://en.wikipedia.org/wiki/Boeing_CH-47_Chinook")
            if "Hercules" in aircraft_name:
                wiki_urls.append("https://en.wikipedia.org/wiki/Lockheed_C-130_Hercules")
            if "Galaxy" in aircraft_name:
                wiki_urls.append("https://en.wikipedia.org/wiki/Lockheed_C-5_Galaxy")
            if "Globemaster" in aircraft_name:
                wiki_urls.append("https://en.wikipedia.org/wiki/Boeing_C-17_Globemaster_III")
            if "Osprey" in aircraft_name:
                wiki_urls.append("https://en.wikipedia.org/wiki/Bell_Boeing_V-22_Osprey")

            for url in wiki_urls[:3]:  # Try max 3 URLs
                self.log(f"Trying Wikipedia URL: {url}")
                time.sleep(random.uniform(1, 2))  # Rate limiting

                try:
                    response = self.session.get(url, timeout=30)
                    if response.status_code == 200:
                        self.log(f"Found Wikipedia page: {url}")
                        return url
                except Exception as e:
                    self.log(f"Error accessing {url}: {e}")
                    continue

            # If direct URLs don't work, try Wikipedia search
            search_url = f"https://en.wikipedia.org/w/api.php"
            params = {
                'action': 'query',
                'format': 'json',
                'list': 'search',
                'srsearch': aircraft_name,
                'srlimit': 3
            }

            time.sleep(random.uniform(1, 2))
            response = self.session.get(search_url, params=params, timeout=30)
            if response.status_code == 200:
                data = response.json()
                if 'query' in data and 'search' in data['query']:
                    for result in data['query']['search']:
                        title = result['title']
                        page_url = f"https://en.wikipedia.org/wiki/{quote(title.replace(' ', '_'))}"
                        self.log(f"Found search result: {page_url}")
                        return page_url

            return None

        except Exception as e:
            self.log(f"Error searching Wikipedia for {aircraft_name}: {e}")
            return None

    def extract_images_from_wikipedia(self, wiki_url, aircraft_name):
        """Extract high-quality images from a Wikipedia page"""
        try:
            self.log(f"Extracting images from: {wiki_url}")
            time.sleep(random.uniform(2, 3))  # Be polite

            response = self.session.get(wiki_url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')
            images = []

            # Look for images in the infobox and main article
            img_candidates = []

            # Priority 1: Infobox images (usually the main aircraft photo)
            infobox = soup.find('table', class_='infobox')
            if infobox:
                infobox_imgs = infobox.find_all('img')
                for img in infobox_imgs:
                    if img.get('src'):
                        img_candidates.append(('infobox', img))

            # Priority 2: Gallery images
            galleries = soup.find_all('li', class_='gallerybox')
            for gallery in galleries[:3]:  # Max 3 gallery images
                img = gallery.find('img')
                if img and img.get('src'):
                    img_candidates.append(('gallery', img))

            # Priority 3: Other article images
            article_imgs = soup.find_all('img')
            for img in article_imgs[:5]:  # Max 5 other images
                if img.get('src'):
                    img_candidates.append(('article', img))

            # Process candidates
            for img_type, img in img_candidates:
                src = img.get('src')
                if not src:
                    continue

                # Convert to full URL
                if src.startswith('//'):
                    src = 'https:' + src
                elif src.startswith('/'):
                    src = 'https://en.wikipedia.org' + src

                # Skip tiny images and icons
                if any(skip in src.lower() for skip in ['icon', 'logo', 'commons-logo', 'edit-icon']):
                    continue

                # Get larger version of thumbnails
                if '/thumb/' in src and src.endswith('.jpg'):
                    # Try to get a larger version
                    original_src = src
                    if '/thumb/' in src:
                        # Extract original image URL
                        parts = src.split('/thumb/')
                        if len(parts) == 2:
                            before_thumb = parts[0]
                            after_thumb = parts[1]
                            # Extract filename (everything after last /)
                            filename_part = after_thumb.split('/')[-1]
                            # Remove size prefix (like "300px-")
                            if filename_part.startswith(('300px-', '250px-', '200px-', '400px-', '500px-')):
                                filename = filename_part.split('-', 1)[-1]
                                src = before_thumb + '/' + filename

                # Validate this looks like an aircraft image
                if self.is_aircraft_image_url(src, aircraft_name):
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
                        'source_page': wiki_url,
                        'type': img_type,
                        'priority': 1 if img_type == 'infobox' else 2 if img_type == 'gallery' else 3
                    })

            # Sort by priority and size
            images.sort(key=lambda x: (x['priority'], -(x['width'] * x['height'])))

            self.log(f"Found {len(images)} potential aircraft images")
            return images[:3]  # Return top 3

        except Exception as e:
            self.log(f"Error extracting images from {wiki_url}: {e}")
            return []

    def is_aircraft_image_url(self, img_url, aircraft_name):
        """Check if an image URL appears to be a valid aircraft photo"""
        img_url_lower = img_url.lower()

        # Skip obvious non-aircraft images
        skip_patterns = [
            'commons-logo', 'wikimedia-logo', 'edit-icon', 'folder', 'question_book',
            'ambox', 'crystal', 'gnome', 'nuvola', 'button', 'arrow', 'flag',
            'map', 'symbol', 'badge', 'ribbon', 'medal', 'star', 'cross'
        ]

        if any(pattern in img_url_lower for pattern in skip_patterns):
            return False

        # Must be from Wikipedia/Wikimedia
        if not any(domain in img_url_lower for domain in ['wikimedia.org', 'wikipedia.org']):
            return False

        # Must be a reasonable image format
        if not any(fmt in img_url_lower for fmt in ['.jpg', '.jpeg', '.png']):
            return False

        # Look for aircraft-related terms
        aircraft_terms = [
            'aircraft', 'plane', 'fighter', 'bomber', 'helicopter', 'chopper',
            'jet', 'military', 'aviation', 'air', 'flight', 'wing'
        ]

        # Extract potential aircraft designation from name
        designations = re.findall(r'[A-Z]{1,2}-?\d+[A-Z]*', aircraft_name)
        for designation in designations:
            aircraft_terms.append(designation.lower().replace('-', ''))

        return any(term in img_url_lower for term in aircraft_terms) or 'upload.wikimedia.org' in img_url_lower

    def download_and_process_image(self, image_url, aircraft_name):
        """Download image and create both original and ESP32-optimized versions"""
        try:
            self.log(f"Downloading image: {image_url}")
            time.sleep(random.uniform(1, 2))  # Rate limiting

            # Use image-specific headers
            headers = {
                'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
                'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
                'Referer': 'https://en.wikipedia.org/',
            }

            response = self.session.get(image_url, headers=headers, timeout=30)
            response.raise_for_status()

            # Validate it's actually an image
            content_type = response.headers.get('content-type', '')
            if not content_type.startswith('image/'):
                self.log(f"Not an image: {content_type}")
                return None, None

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

            return original_bytes, esp32_bytes

        except Exception as e:
            self.log(f"Error processing image {image_url}: {e}")
            return None, None

    def upload_to_zipline(self, image_data, filename, is_bmp=False):
        """Upload image to Zipline and return the URL"""
        try:
            self.log(f"Uploading to Zipline: {filename}")
            time.sleep(random.uniform(0.5, 1.0))  # Short delay for uploads

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
        self.log(f"Starting browser-based scraping for: {aircraft_name}")

        # Find Wikipedia page
        wiki_url = self.search_wikipedia_for_aircraft(aircraft_name)
        if not wiki_url:
            self.log(f"No Wikipedia page found for {aircraft_name}")
            return None

        # Extract images from the page
        images = self.extract_images_from_wikipedia(wiki_url, aircraft_name)
        if not images:
            self.log(f"No suitable images found for {aircraft_name}")
            return None

        # Try to download and process the best image
        for image_info in images:
            original_bytes, esp32_bytes = self.download_and_process_image(
                image_info['url'], aircraft_name
            )

            if original_bytes and esp32_bytes:
                # Create safe filenames
                safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', aircraft_name)

                # Upload both versions
                original_filename = f"{safe_name}_original.jpg"
                esp32_filename = f"{safe_name}_esp32.bmp"

                original_url = self.upload_to_zipline(original_bytes, original_filename, False)
                esp32_url = self.upload_to_zipline(esp32_bytes, esp32_filename, True)

                if original_url and esp32_url:
                    return {
                        "original_url": image_info['url'],
                        "zipline_url": original_url,
                        "zipline_esp32_url": esp32_url,
                        "width": 1200,
                        "height": 800,
                        "esp32_width": 96,
                        "esp32_height": 72,
                        "alt_text": image_info['alt_text'],
                        "source_page": wiki_url,
                        "processed_at": datetime.now().isoformat(),
                        "source": "Wikipedia (browser-based)"
                    }

        return None

    def process_all_aircraft(self):
        """Process all 122 aircraft in the dataset"""
        print("🌐 Starting browser-based image scraping for all military aircraft...")

        # Load current dataset
        with open('../mqtt/unified/datasets/military_aircraft_final.json', 'r') as f:
            data = json.load(f)

        print(f"📊 Processing {len(data['aircraft'])} aircraft...")

        successful_updates = 0
        failed_aircraft = []

        for i, aircraft in enumerate(data['aircraft'], 1):
            print(f"\n🔍 Processing {i}/{len(data['aircraft'])}: {aircraft['name']}")

            # Skip if already has images (in case of restart)
            if aircraft.get('images') and len(aircraft.get('images', [])) > 0:
                print(f"  ⏭️ Already has images, skipping...")
                successful_updates += 1
                continue

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
            if i % 5 == 0:  # Save every 5 aircraft
                print(f"💾 Saving progress... ({i}/{len(data['aircraft'])})")
                self.save_dataset(data, successful_updates, len(data['aircraft']))

            # Be extra polite with timing
            time.sleep(random.uniform(3, 5))

        # Final save
        self.save_dataset(data, successful_updates, len(data['aircraft']))

        print(f"\n✅ Browser-based image scraping completed!")
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
            print(f"All {len(data['aircraft'])} military aircraft now have fresh Wikipedia images!")

    def save_dataset(self, data, successful_count, total_count):
        """Save the dataset with current progress"""
        # Update metadata
        data['metadata']['aircraft_with_images'] = successful_count
        data['metadata']['last_updated'] = datetime.now().isoformat()
        data['metadata']['version'] = '1.9'
        data['metadata']['image_completion'] = f"{successful_count}/{total_count} ({successful_count/total_count*100:.1f}%)"
        data['metadata']['image_source'] = "Wikipedia (browser-based scraping)"

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

    scraper = BrowserImageScraper(zipline_url, zipline_token, debug=True)
    scraper.process_all_aircraft()

if __name__ == '__main__':
    main()