#!/usr/bin/env python3
"""
AirTracker Image Processor

This script downloads images from URLs, converts them to 24-bit BMP format
at 96x72 resolution for ESP32 display, uploads to Zipline, and stores
the processed URLs in memory for use by other scripts.

Usage:
    python3 image_processor.py --url "https://example.com/image.jpg"
    python3 image_processor.py --batch-file "image_urls.txt" --save-json
    python3 image_processor.py --list-processed

By default, processed URLs are stored in memory. Use --save-json to persist to file.
"""

import argparse
import json
import os
import sys
import urllib.request
import urllib.parse
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Optional, Tuple

try:
    from PIL import Image, ImageOps
    import requests
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Missing required dependency: {e}")
    print("Install with: pip install Pillow requests python-dotenv")
    sys.exit(1)

# Load environment from root .env file
root_env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
if os.path.exists(root_env_path):
    load_dotenv(root_env_path)

# Configuration
TARGET_WIDTH = 96
TARGET_HEIGHT = 72
BMP_BITS_PER_PIXEL = 24
PROCESSED_URLS_FILE = "data/processed_images.json"
TEMP_DIR = "data/temp_images"

# Global in-memory storage for processed images
_processed_images_cache = {}


class ImageProcessor:
    """Handles image download, conversion, and Zipline upload."""

    def __init__(self, zipline_config: Optional[Dict] = None, use_memory_only: bool = True):
        """Initialize with Zipline configuration."""
        self.use_memory_only = use_memory_only
        self.setup_directories()
        self.setup_zipline(zipline_config)

        # Use global in-memory cache by default, optionally load from file
        global _processed_images_cache
        self.processed_images = _processed_images_cache

        if not use_memory_only:
            # Load from file and merge with memory cache
            file_data = self.load_processed_images_from_file()
            self.processed_images.update(file_data)

    def setup_directories(self):
        """Create necessary directories."""
        os.makedirs(TEMP_DIR, exist_ok=True)
        if not self.use_memory_only:
            os.makedirs(os.path.dirname(PROCESSED_URLS_FILE), exist_ok=True)

    def setup_zipline(self, config: Optional[Dict]):
        """Configure Zipline with provided config or environment variables."""
        if config:
            self.zipline_url = config.get('url', 'https://zip.spacegeese.com')
            self.zipline_token = config['token']
            self.zipline_folder_id = config.get('folder_id')
        else:
            # Use environment variables from root .env file
            self.zipline_url = os.getenv('ZIPLINE_URL', 'https://zip.spacegeese.com')
            self.zipline_token = os.getenv('ZIPLINE_TOKEN')
            self.zipline_folder_id = os.getenv('ZIPLINE_AIRCRAFT_FOLDER_ID', 'cmfw6kozd022701mvmjz33v2j')

            if not self.zipline_token:
                print("❌ Zipline configuration missing!")
                print("Add ZIPLINE_TOKEN to root .env file")
                print("Or pass config dict to ImageProcessor()")
                sys.exit(1)

    def load_processed_images_from_file(self) -> Dict:
        """Load previously processed images from JSON file."""
        if os.path.exists(PROCESSED_URLS_FILE):
            try:
                with open(PROCESSED_URLS_FILE, 'r') as f:
                    return json.load(f)
            except (json.JSONDecodeError, IOError) as e:
                print(f"⚠️ Warning: Could not load processed images file: {e}")
        return {}

    def save_processed_images_to_file(self):
        """Save processed images to JSON file (only when explicitly requested)."""
        if self.use_memory_only:
            print("⚠️ Memory-only mode - use --save-json flag to persist to file")
            return

        try:
            os.makedirs(os.path.dirname(PROCESSED_URLS_FILE), exist_ok=True)
            with open(PROCESSED_URLS_FILE, 'w') as f:
                json.dump(self.processed_images, f, indent=2, sort_keys=True)
            print(f"💾 Saved {len(self.processed_images)} processed images to {PROCESSED_URLS_FILE}")
        except IOError as e:
            print(f"❌ Error saving processed images: {e}")

    def download_image(self, url: str) -> Optional[str]:
        """Download image from URL to temporary file."""
        try:
            print(f"📥 Downloading: {url}")

            # Create filename from URL
            parsed_url = urllib.parse.urlparse(url)
            filename = os.path.basename(parsed_url.path) or "image"
            if not any(filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.bmp', '.gif']):
                filename += ".jpg"

            temp_path = os.path.join(TEMP_DIR, f"original_{filename}")

            # Download with headers to avoid bot detection
            req = urllib.request.Request(url, headers={
                'User-Agent': 'AirTracker/1.0 (Aircraft Image Processor)'
            })

            with urllib.request.urlopen(req, timeout=30) as response:
                with open(temp_path, 'wb') as f:
                    f.write(response.read())

            print(f"✅ Downloaded to: {temp_path}")
            return temp_path

        except Exception as e:
            print(f"❌ Download failed: {e}")
            return None

    def convert_to_bmp(self, input_path: str) -> Optional[str]:
        """Convert image to 24-bit BMP at target resolution."""
        try:
            print(f"🔄 Converting to {TARGET_WIDTH}x{TARGET_HEIGHT} 24-bit BMP...")

            # Open and process image
            with Image.open(input_path) as img:
                # Convert to RGB (24-bit)
                if img.mode != 'RGB':
                    img = img.convert('RGB')

                # Resize with high-quality resampling
                # Use thumbnail to maintain aspect ratio, then pad if needed
                img.thumbnail((TARGET_WIDTH, TARGET_HEIGHT), Image.Resampling.LANCZOS)

                # Create new image with target size and center the resized image
                new_img = Image.new('RGB', (TARGET_WIDTH, TARGET_HEIGHT), (0, 0, 0))

                # Calculate position to center the image
                x = (TARGET_WIDTH - img.width) // 2
                y = (TARGET_HEIGHT - img.height) // 2
                new_img.paste(img, (x, y))

                # Save as BMP
                output_path = input_path.replace('original_', 'converted_').replace('.jpg', '.bmp').replace('.jpeg', '.bmp').replace('.png', '.bmp')
                new_img.save(output_path, 'BMP')

                print(f"✅ Converted: {output_path}")
                return output_path

        except Exception as e:
            print(f"❌ Conversion failed: {e}")
            return None

    def upload_to_zipline(self, bmp_path: str, original_url: str) -> Optional[str]:
        """Upload BMP to Zipline and return the URL."""
        try:
            print(f"☁️ Uploading to Zipline...")

            # Prepare the upload
            upload_url = f"{self.zipline_url.rstrip('/')}/api/upload"

            headers = {
                'authorization': self.zipline_token,
                'x-zipline-format': 'name'
            }

            # Add folder header for aircraft images
            if self.zipline_folder_id:
                headers['x-zipline-folder'] = self.zipline_folder_id

            # Create meaningful filename with timestamp
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            original_filename = os.path.basename(bmp_path)
            filename = f"aircraft_{timestamp}_{original_filename}"

            # File data
            files = {
                'file': (filename, open(bmp_path, 'rb'), 'image/bmp')
            }

            # Upload the file
            response = requests.post(
                upload_url,
                headers=headers,
                files=files,
                timeout=30
            )

            # Close the file
            files['file'][1].close()

            if response.status_code == 200 or response.status_code == 201:
                try:
                    result = response.json()
                    # Based on Zipline API: .files[0].url
                    zipline_url = result.get('files', [{}])[0].get('url')
                    print(f"✅ Uploaded: {zipline_url}")
                    return zipline_url
                except Exception as e:
                    print(f"❌ Couldn't parse Zipline response: {e}")
                    return None
            else:
                print(f"❌ Zipline upload failed: HTTP {response.status_code}: {response.text[:200]}")
                return None

        except requests.exceptions.Timeout:
            print(f"❌ Zipline upload timeout")
            return None
        except requests.exceptions.ConnectionError:
            print(f"❌ Zipline connection error")
            return None
        except Exception as e:
            print(f"❌ Zipline upload failed: {e}")
            return None

    def cleanup_temp_files(self, files: List[str]):
        """Remove temporary files."""
        for file_path in files:
            try:
                if os.path.exists(file_path):
                    os.remove(file_path)
            except OSError:
                pass  # Ignore cleanup errors

    def process_image(self, url: str, force: bool = False) -> Optional[str]:
        """Process a single image: download, convert, upload."""
        # Check if already processed
        if not force and url in self.processed_images:
            existing_entry = self.processed_images[url]
            print(f"⏭️ Already processed: {existing_entry['zipline_url']}")
            return existing_entry['zipline_url']

        temp_files = []

        try:
            # Download
            downloaded_path = self.download_image(url)
            if not downloaded_path:
                return None
            temp_files.append(downloaded_path)

            # Convert to BMP
            bmp_path = self.convert_to_bmp(downloaded_path)
            if not bmp_path:
                return None
            temp_files.append(bmp_path)

            # Upload to Zipline
            zipline_url = self.upload_to_zipline(bmp_path, url)
            if not zipline_url:
                return None

            # Store result
            self.processed_images[url] = {
                'zipline_url': zipline_url,
                'processed_date': datetime.now().isoformat(),
                'dimensions': f"{TARGET_WIDTH}x{TARGET_HEIGHT}",
                'format': 'BMP',
                'bits_per_pixel': BMP_BITS_PER_PIXEL
            }

            # Save to file only if not in memory-only mode
            if not self.use_memory_only:
                self.save_processed_images_to_file()
            print(f"🎉 Processing complete: {zipline_url}")
            return zipline_url

        finally:
            # Cleanup
            self.cleanup_temp_files(temp_files)

    def process_batch(self, urls: List[str], force: bool = False) -> Dict[str, Optional[str]]:
        """Process multiple images."""
        results = {}
        total = len(urls)

        for i, url in enumerate(urls, 1):
            print(f"\n📷 Processing {i}/{total}: {url}")
            result = self.process_image(url, force)
            results[url] = result

        return results

    def list_processed(self) -> Dict:
        """Return dictionary of all processed images."""
        return self.processed_images.copy()

    def get_zipline_url(self, original_url: str) -> Optional[str]:
        """Get Zipline URL for a processed image."""
        entry = self.processed_images.get(original_url)
        return entry['zipline_url'] if entry else None


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(description="AirTracker Image Processor")
    parser.add_argument('--url', help='Single image URL to process')
    parser.add_argument('--batch-file', help='File containing URLs (one per line)')
    parser.add_argument('--list-processed', action='store_true', help='List all processed images')
    parser.add_argument('--force', action='store_true', help='Force reprocessing even if already done')
    parser.add_argument('--get-url', help='Get Zipline URL for original URL')
    parser.add_argument('--save-json', action='store_true', help='Save processed URLs to JSON file (default: memory only)')
    parser.add_argument('--load-json', action='store_true', help='Load existing URLs from JSON file into memory')

    args = parser.parse_args()

    if not any([args.url, args.batch_file, args.list_processed, args.get_url]):
        parser.print_help()
        sys.exit(1)

    # Initialize processor (memory-only unless --save-json specified)
    use_memory_only = not args.save_json
    processor = ImageProcessor(use_memory_only=use_memory_only)

    # Optionally load existing data from JSON into memory
    if args.load_json:
        file_data = processor.load_processed_images_from_file()
        processor.processed_images.update(file_data)
        print(f"📂 Loaded {len(file_data)} images from {PROCESSED_URLS_FILE} into memory")

    if args.list_processed:
        processed = processor.list_processed()
        if processed:
            print(f"\n📋 {len(processed)} processed images:")
            for original_url, data in processed.items():
                print(f"  Original: {original_url}")
                print(f"  Zipline: {data['zipline_url']}")
                print(f"  Date: {data['processed_date']}")
                print()
        else:
            print("📋 No processed images found.")

    elif args.get_url:
        zipline_url = processor.get_zipline_url(args.get_url)
        if zipline_url:
            print(zipline_url)
        else:
            print(f"❌ No processed image found for: {args.get_url}")
            sys.exit(1)

    elif args.url:
        result = processor.process_image(args.url, args.force)
        if result:
            print(f"\n🎯 Final Zipline URL: {result}")
        else:
            print("\n❌ Processing failed")
            sys.exit(1)

    elif args.batch_file:
        if not os.path.exists(args.batch_file):
            print(f"❌ Batch file not found: {args.batch_file}")
            sys.exit(1)

        with open(args.batch_file, 'r') as f:
            urls = [line.strip() for line in f if line.strip() and not line.startswith('#')]

        if not urls:
            print(f"❌ No URLs found in: {args.batch_file}")
            sys.exit(1)

        print(f"📦 Processing {len(urls)} images from {args.batch_file}")
        results = processor.process_batch(urls, args.force)

        # Summary
        successful = sum(1 for result in results.values() if result)
        print(f"\n📊 Summary: {successful}/{len(urls)} images processed successfully")


if __name__ == '__main__':
    main()