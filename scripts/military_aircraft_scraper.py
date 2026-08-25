#!/usr/bin/env python3
"""
Military Aircraft Scraper for Military.com
Scrapes all military aircraft information including specifications, images, and details.

Usage:
    python3 military_aircraft_scraper.py
    python3 military_aircraft_scraper.py --output military_aircraft_data.json
    python3 military_aircraft_scraper.py --aircraft-type helicopter
    python3 military_aircraft_scraper.py --debug
"""

import argparse
import json
import os
import random
import re
import time
from datetime import datetime
from io import BytesIO
from pathlib import Path
from typing import Dict, List, Optional, Set
from urllib.parse import urljoin, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image


class MilitaryAircraftScraper:
    """Scraper for Military.com aircraft database."""

    BASE_URL = "https://www.military.com"

    # ESP32 display dimensions
    TARGET_WIDTH = 96
    TARGET_HEIGHT = 72

    def __init__(self, debug: bool = False, zipline_url: str = None, zipline_token: str = None):
        self.debug = debug
        self.scraped_urls = set()
        self.session = requests.Session()
        self.session.headers.update({
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'
        })

        # Zipline configuration
        self.zipline_url = zipline_url
        self.zipline_token = zipline_token
        self.zipline_folder_id = 'cmg5jdflb000s01mvpjgckdvk'  # Military_Aircraft folder

        # Rate limiting
        self.start_time = time.time()
        self.request_count = 0

        # Progress tracking
        self.aircraft_category_mapping = {}

        if self.zipline_url and self.zipline_token:
            self.log(f"✅ Zipline configured for Military_Aircraft folder: {self.zipline_folder_id}")
        else:
            self.log("⚠️  Zipline not configured - images will not be uploaded")

    def log(self, message: str):
        """Log message with timestamp if debug enabled."""
        if self.debug:
            timestamp = datetime.now().strftime("%H:%M:%S")
            print(f"[{timestamp}] {message}")

    def polite_delay(self, delay_type: str = "default"):
        """Add polite delay to avoid overwhelming the server."""
        delays = {
            "default": 2.0,
            "category": 3.0,
            "aircraft": 1.5,
            "image": 0.5,
            "pagination": 2.5
        }

        delay = delays.get(delay_type, 2.0)
        self.request_count += 1

        # Log rate limiting info
        elapsed = time.time() - self.start_time
        rate = self.request_count / elapsed if elapsed > 0 else 0
        self.log(f"💤 Polite delay: {delay}s ({delay_type}) | Requests: {self.request_count} | Rate: {rate:.1f}/min")

        # Add some randomness to avoid predictable patterns
        actual_delay = delay + random.uniform(0, 0.5)
        time.sleep(actual_delay)

    def download_image(self, url: str) -> Optional[bytes]:
        """Download image from URL and return bytes."""
        try:
            response = self.session.get(url, timeout=30)
            response.raise_for_status()
            return response.content
        except Exception as e:
            self.log(f"❌ Error downloading image {url}: {e}")
            return None

    def convert_to_esp32_bmp(self, image_bytes: bytes) -> Optional[bytes]:
        """Convert image to ESP32-compatible BMP format (96x72, 24-bit)."""
        try:
            with Image.open(BytesIO(image_bytes)) as img:
                # Convert to RGB if necessary
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                # Resize maintaining aspect ratio
                img.thumbnail((self.TARGET_WIDTH, self.TARGET_HEIGHT), Image.Resampling.LANCZOS)

                # Create new image with exact dimensions (center the resized image)
                final_img = Image.new('RGB', (self.TARGET_WIDTH, self.TARGET_HEIGHT), (0, 0, 0))
                paste_x = (self.TARGET_WIDTH - img.width) // 2
                paste_y = (self.TARGET_HEIGHT - img.height) // 2
                final_img.paste(img, (paste_x, paste_y))

                # Save as BMP
                output = BytesIO()
                final_img.save(output, format='BMP')
                return output.getvalue()

        except Exception as e:
            self.log(f"❌ Error converting image to ESP32 BMP: {e}")
            return None

    def upload_to_zipline(self, image_bytes: bytes, filename: str) -> Optional[str]:
        """Upload image to Zipline and return the URL."""
        if not self.zipline_url or not self.zipline_token:
            return None

        try:
            files = {'file': (filename, image_bytes)}
            data = {'folderId': self.zipline_folder_id}
            headers = {'Authorization': self.zipline_token}

            response = requests.post(
                f"{self.zipline_url}/api/upload",
                files=files,
                data=data,
                headers=headers,
                timeout=30
            )
            response.raise_for_status()

            result = response.json()
            return result.get('url', result.get('files', [{}])[0].get('url'))

        except Exception as e:
            self.log(f"❌ Error uploading {filename} to Zipline: {e}")
            return None

    def process_aircraft_images(self, soup: BeautifulSoup, aircraft_name: str) -> List[Dict]:
        """Extract and process images from aircraft page."""
        images = []

        # Find all images on the page
        img_tags = soup.find_all('img')
        processed_count = 0

        for img in img_tags:
            if processed_count >= 3:  # Limit to 3 images per aircraft
                break

            src = img.get('src')
            if not src:
                continue

            # Convert relative URLs to absolute
            if src.startswith('//'):
                src = 'https:' + src
            elif src.startswith('/'):
                src = urljoin(self.BASE_URL, src)

            # Skip small images, thumbnails, and icons
            width = img.get('width')
            height = img.get('height')
            if width and height:
                try:
                    if int(width) < 300 or int(height) < 200:
                        continue
                except (ValueError, TypeError):
                    pass

            # Skip if URL contains thumbnail indicators or invalid formats
            skip_indicators = ['thumb', 'icon', 'logo', 'badge', '.svg', 'data:', 'search-arrow', 'placeholder']
            if any(indicator in src.lower() for indicator in skip_indicators):
                continue

            # Download original image
            self.log(f"  📸 Processing image: {src}")
            original_bytes = self.download_image(src)
            if not original_bytes:
                continue

            # Get image metadata
            try:
                with Image.open(BytesIO(original_bytes)) as pil_img:
                    img_width, img_height = pil_img.size
            except:
                img_width, img_height = 0, 0

            # Skip small images
            if img_width < 300 or img_height < 200:
                continue

            # Upload original image to Zipline
            safe_aircraft_name = re.sub(r'[^\w\-]', '_', aircraft_name)
            original_filename = f"military_{safe_aircraft_name}_{processed_count + 1}_original.jpg"
            original_zipline_url = self.upload_to_zipline(original_bytes, original_filename)

            # Convert to ESP32 BMP format
            esp32_bmp_bytes = self.convert_to_esp32_bmp(original_bytes)
            esp32_zipline_url = None
            if esp32_bmp_bytes:
                esp32_filename = f"military_{safe_aircraft_name}_{processed_count + 1}_esp32.bmp"
                esp32_zipline_url = self.upload_to_zipline(esp32_bmp_bytes, esp32_filename)

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
            self.polite_delay("image")

        self.log(f"  ✅ Processed {len(images)} images for {aircraft_name}")
        return images

    def extract_specifications(self, soup: BeautifulSoup) -> Dict[str, str]:
        """Extract aircraft specifications from the page."""
        specs = {}

        # Look for specification tables
        spec_tables = soup.find_all(['table', 'dl', 'div'], class_=re.compile(r'spec|detail|info'))

        for table in spec_tables:
            # Try different table formats
            rows = table.find_all(['tr', 'dt', 'div'])
            for row in rows:
                # Handle table rows
                if row.name == 'tr':
                    cells = row.find_all(['td', 'th'])
                    if len(cells) >= 2:
                        key = cells[0].get_text(strip=True)
                        value = cells[1].get_text(strip=True)
                        if key and value:
                            specs[key] = value

                # Handle definition lists
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

    def extract_aircraft_from_category(self, category_url: str, category_name: str) -> List[Dict]:
        """Extract all individual aircraft URLs from a category page with pagination."""
        aircraft_list = []
        page_num = 0

        while True:
            # Construct paginated URL
            if page_num == 0:
                page_url = category_url
            else:
                separator = '&' if '?' in category_url else '?'
                page_url = f"{category_url}{separator}_wrapper_format=html&page={page_num}"

            self.log(f"  📄 Scraping page {page_num + 1}: {page_url}")

            try:
                response = self.session.get(page_url, timeout=30)
                response.raise_for_status()
                soup = BeautifulSoup(response.content, 'html.parser')

                # Find aircraft links on this page
                page_aircraft_count = 0
                links = soup.find_all('a', href=True)

                for link in links:
                    href = link.get('href')
                    if not href:
                        continue

                    # Convert relative URLs to absolute
                    if href.startswith('/'):
                        href = urljoin(self.BASE_URL, href)

                    # Skip if not from military.com domain
                    if 'military.com' not in href:
                        continue

                    # Skip category pages and non-aircraft pages
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

                    # Only include equipment pages that look like individual aircraft
                    if '/equipment/' in href and href not in [item['url'] for item in aircraft_list]:
                        # Extract aircraft name from URL or link text
                        aircraft_name = link.get_text(strip=True)
                        if not aircraft_name:
                            # Extract from URL
                            aircraft_name = href.split('/')[-1].replace('-', ' ').title()

                        aircraft_info = {
                            'url': href,
                            'name': aircraft_name,
                            'source_category': category_name,
                            'source_category_url': category_url
                        }
                        aircraft_list.append(aircraft_info)
                        page_aircraft_count += 1

                self.log(f"    Found {page_aircraft_count} aircraft on page {page_num + 1}")

                # Check if there's a "Next" button or more pages
                has_next = False
                pagination_links = soup.find_all('a', href=True)
                for link in pagination_links:
                    href = link.get('href', '')
                    link_text = link.get_text().strip().lower()

                    # Check for "next" or page numbers higher than current
                    if ('next' in link_text or f'page={page_num + 1}' in href):
                        has_next = True
                        break

                # If no aircraft found on this page or no next button, we're done
                if page_aircraft_count == 0 or not has_next:
                    break

                page_num += 1
                self.polite_delay("pagination")

            except requests.RequestException as e:
                self.log(f"  ❌ Failed to fetch page {page_num + 1} of {category_url}: {e}")
                break

        self.log(f"  ✅ Category complete: {len(aircraft_list)} total aircraft found")
        return aircraft_list

    def get_all_aircraft_urls(self) -> List[Dict]:
        """Get all aircraft URLs from the 27 predefined categories."""
        self.log("🎯 Using predefined list of 27 military aircraft categories")

        # Complete list of 27 category URLs
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

        self.log(f"Processing all {len(categories)} predefined categories")

        all_aircraft = []
        category_counts = {}

        for i, (category_name, category_url) in enumerate(categories, 1):
            self.log(f"🗂️  Category {i}/{len(categories)}: {category_name}")

            # Extract all aircraft from this category
            category_aircraft = self.extract_aircraft_from_category(category_url, category_name)
            all_aircraft.extend(category_aircraft)

            category_counts[category_name] = len(category_aircraft)
            self.log(f"  ✅ {category_name}: {len(category_aircraft)} aircraft found")

            self.polite_delay("category")

        # Show summary
        print(f"\n📊 Aircraft found by category:")
        total_discovered = 0
        for category, count in sorted(category_counts.items()):
            print(f"   📂 {category}: {count} aircraft")
            total_discovered += count
        print(f"   📊 Total discovered: {total_discovered} aircraft")

        self.log(f"🎯 TOTAL AIRCRAFT DISCOVERED: {total_discovered} across all {len(categories)} categories")

        # Remove duplicates and create URL mapping
        unique_aircraft = {}
        for aircraft in all_aircraft:
            url = aircraft['url']
            if url not in unique_aircraft:
                unique_aircraft[url] = aircraft
                self.aircraft_category_mapping[url] = {
                    'source_category': aircraft['source_category'],
                    'source_category_url': aircraft['source_category_url']
                }

        aircraft_urls = list(unique_aircraft.keys())
        self.log(f"📋 {len(aircraft_urls)} unique aircraft URLs after deduplication")

        return aircraft_urls

    def extract_aircraft_info(self, url: str) -> Optional[Dict]:
        """Extract detailed information from a single aircraft page."""
        if url in self.scraped_urls:
            self.log(f"Skipping already scraped URL: {url}")
            return None

        try:
            self.log(f"🛩️  Scraping aircraft: {url}")
            response = self.session.get(url, timeout=30)
            response.raise_for_status()

            soup = BeautifulSoup(response.content, 'html.parser')

            # Extract aircraft name from title or heading
            aircraft_name = "Unknown Aircraft"
            title_tag = soup.find('title')
            if title_tag:
                aircraft_name = title_tag.get_text().split('|')[0].strip()

            # Also try h1 tags
            h1_tags = soup.find_all('h1')
            for h1 in h1_tags:
                text = h1.get_text(strip=True)
                if text and len(text) < 100:  # Reasonable title length
                    aircraft_name = text
                    break

            # Clean up aircraft name
            aircraft_name = re.sub(r'\s+', ' ', aircraft_name).strip()

            self.log(f"  📝 Aircraft name: {aircraft_name}")

            # Extract specifications
            specifications = self.extract_specifications(soup)

            # Process images
            images = self.process_aircraft_images(soup, aircraft_name)

            # Extract description
            description = ""
            # Try to find main content area
            content_areas = soup.find_all(['div', 'section'], class_=re.compile(r'content|body|article|main'))
            for area in content_areas:
                paragraphs = area.find_all('p')
                if paragraphs:
                    description = ' '.join([p.get_text(strip=True) for p in paragraphs[:2]])
                    break

            if not description:
                # Fallback to any paragraph
                paragraphs = soup.find_all('p')
                if paragraphs:
                    description = paragraphs[0].get_text(strip=True)

            # Get category info
            category_info = self.aircraft_category_mapping.get(url, {})

            aircraft_data = {
                'name': aircraft_name,
                'url': url,
                'scraped_at': datetime.now().isoformat(),
                'specifications': specifications,
                'images': images,
                'description': description,
                'aliases': [],  # Could be expanded to extract alternate names
                'category': category_info.get('source_category', 'Unknown')
            }

            self.scraped_urls.add(url)
            return aircraft_data

        except requests.RequestException as e:
            self.log(f"❌ Failed to fetch {url}: {e}")
            return None
        except Exception as e:
            self.log(f"❌ Error processing {url}: {e}")
            return None

    def scrape_all_aircraft(self, aircraft_type_filter: str = None) -> Dict:
        """Main method to scrape all aircraft data."""
        self.log("Starting military aircraft scraping...")

        # Get all aircraft URLs
        aircraft_urls = self.get_all_aircraft_urls()

        if not aircraft_urls:
            self.log("No aircraft URLs found!")
            return {"error": "No aircraft URLs found"}

        # Filter by aircraft type if specified
        if aircraft_type_filter:
            filtered_urls = []
            filter_lower = aircraft_type_filter.lower()
            for url in aircraft_urls:
                category_info = self.aircraft_category_mapping.get(url, {})
                category = category_info.get('source_category', '').lower()
                if filter_lower in category or filter_lower in url.lower():
                    filtered_urls.append(url)
            aircraft_urls = filtered_urls
            self.log(f"Filtered to {len(aircraft_urls)} aircraft matching '{aircraft_type_filter}'")

        # Organize by categories for structured output
        categories = {}
        aircraft_list = []
        total_processed = 0

        self.log(f"🚀 Processing {len(aircraft_urls)} aircraft...")

        for i, url in enumerate(aircraft_urls, 1):
            self.log(f"Progress: {i}/{len(aircraft_urls)} ({(i/len(aircraft_urls)*100):.1f}%)")

            aircraft_data = self.extract_aircraft_info(url)
            if aircraft_data:
                # Add to main list
                aircraft_list.append(aircraft_data)

                # Organize by category
                category = aircraft_data.get('category', 'Unknown')
                if category not in categories:
                    categories[category] = {
                        'description': f"Aircraft from {category} category page",
                        'aircraft': [],
                        'total_aircraft': 0
                    }

                categories[category]['aircraft'].append(aircraft_data)
                categories[category]['total_aircraft'] = len(categories[category]['aircraft'])

                total_processed += 1

                # Save progress periodically
                if total_processed % 10 == 0:
                    self.save_progress_file(categories, aircraft_list, total_processed, len(aircraft_urls))

            self.polite_delay("aircraft")

        self.log(f"✅ Scraping complete! Processed {total_processed} aircraft successfully.")

        return {
            'scraped_at': datetime.now().isoformat(),
            'source': 'Military.com',
            'total_aircraft_discovered': len(aircraft_urls),
            'total_aircraft_processed': total_processed,
            'categories': categories,
            'aircraft': aircraft_list
        }

    def save_progress_file(self, categories: Dict, aircraft_list: List, processed: int, total: int):
        """Save progress to a temporary file."""
        try:
            progress_data = {
                'scraped_at': datetime.now().isoformat(),
                'source': 'Military.com',
                'progress': f"{processed}/{total} ({(processed/total*100):.1f}%)",
                'total_aircraft_discovered': total,
                'total_aircraft_processed': processed,
                'categories': categories,
                'aircraft': aircraft_list
            }

            progress_file = '../mqtt/unified/datasets/military_aircraft_progress.json'
            with open(progress_file, 'w') as f:
                json.dump(progress_data, f, indent=2)

            self.log(f"💾 Progress saved: {processed}/{total} aircraft")
        except Exception as e:
            self.log(f"❌ Error saving progress: {e}")


def main():
    parser = argparse.ArgumentParser(description='Scrape military aircraft data from Military.com')
    parser.add_argument('--output', '-o', default='military_aircraft_data.json',
                        help='Output JSON file path')
    parser.add_argument('--debug', action='store_true',
                        help='Enable debug logging')
    parser.add_argument('--aircraft-type',
                        help='Filter by aircraft type (e.g., "helicopter", "fighter")')

    args = parser.parse_args()

    # Get Zipline configuration from environment
    zipline_url = os.getenv('ZIPLINE_URL')
    zipline_token = os.getenv('ZIPLINE_TOKEN')

    print("🎖️  Military Aircraft Scraper for Military.com")
    print("=" * 50)

    try:
        scraper = MilitaryAircraftScraper(
            debug=args.debug,
            zipline_url=zipline_url,
            zipline_token=zipline_token
        )

        aircraft_data = scraper.scrape_all_aircraft(args.aircraft_type)

        # Save final results
        output_path = Path(args.output)
        output_path.parent.mkdir(parents=True, exist_ok=True)

        with open(output_path, 'w') as f:
            json.dump(aircraft_data, f, indent=2)

        print(f"\n✅ Scraping completed successfully!")
        print(f"📊 Total aircraft processed: {aircraft_data.get('total_aircraft_processed', 0)}")
        print(f"📁 Data saved to: {output_path}")

        if aircraft_data.get('categories'):
            print(f"📂 Categories collected: {len(aircraft_data['categories'])}")

    except KeyboardInterrupt:
        print("\n⚠️ Scraping interrupted by user")
    except Exception as e:
        print(f"\n❌ Error during scraping: {e}")
        if args.debug:
            import traceback
            traceback.print_exc()


if __name__ == '__main__':
    main()