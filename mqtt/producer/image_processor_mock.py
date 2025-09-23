#!/usr/bin/env python3
"""
Mock version of image processor for testing without Cloudinary credentials
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
    from dotenv import load_dotenv
except ImportError as e:
    print(f"Missing required dependency: {e}")
    print("Install with: pip install Pillow python-dotenv")
    sys.exit(1)

# Load environment from root .env file
root_env_path = os.path.join(os.path.dirname(__file__), '..', '..', '.env')
if os.path.exists(root_env_path):
    load_dotenv(root_env_path)

# Configuration
TARGET_WIDTH = 96
TARGET_HEIGHT = 72
BMP_BITS_PER_PIXEL = 24
TEMP_DIR = "data/temp_images"

# Global in-memory storage for processed images
_processed_images_cache = {}

def mock_cloudinary_upload(bmp_path: str, original_url: str) -> str:
    """Mock Cloudinary upload that returns a fake URL."""
    timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
    filename = os.path.basename(bmp_path)
    # Return a fake Cloudinary URL
    return f"https://res.cloudinary.com/airtracker/image/upload/v1234567890/airtracker/aircraft_{timestamp}_{filename.replace('.bmp', '')}.bmp"

def download_image(url: str) -> Optional[str]:
    """Download image from URL to temporary file."""
    try:
        print(f"📥 Downloading: {url}")

        # Create filename from URL
        parsed_url = urllib.parse.urlparse(url)
        filename = os.path.basename(parsed_url.path) or "image"
        if not any(filename.lower().endswith(ext) for ext in ['.jpg', '.jpeg', '.png', '.bmp', '.gif']):
            filename += ".jpg"

        os.makedirs(TEMP_DIR, exist_ok=True)
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

def convert_to_bmp(input_path: str) -> Optional[str]:
    """Convert image to 24-bit BMP at target resolution."""
    try:
        print(f"🔄 Converting to {TARGET_WIDTH}x{TARGET_HEIGHT} 24-bit BMP...")

        # Open and process image
        with Image.open(input_path) as img:
            # Convert to RGB (24-bit)
            if img.mode != 'RGB':
                img = img.convert('RGB')

            # Resize with high-quality resampling
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

def process_image_mock(url: str) -> Optional[str]:
    """Process a single image with mock Cloudinary upload."""
    temp_files = []

    try:
        # Download
        downloaded_path = download_image(url)
        if not downloaded_path:
            return None
        temp_files.append(downloaded_path)

        # Convert to BMP
        bmp_path = convert_to_bmp(downloaded_path)
        if not bmp_path:
            return None
        temp_files.append(bmp_path)

        # Mock Cloudinary upload
        print(f"☁️ Uploading to Cloudinary (MOCK)...")
        cloudinary_url = mock_cloudinary_upload(bmp_path, url)
        print(f"✅ Uploaded (MOCK): {cloudinary_url}")

        # Store result in memory
        _processed_images_cache[url] = {
            'cloudinary_url': cloudinary_url,
            'processed_date': datetime.now().isoformat(),
            'dimensions': f"{TARGET_WIDTH}x{TARGET_HEIGHT}",
            'format': 'BMP',
            'bits_per_pixel': BMP_BITS_PER_PIXEL
        }

        print(f"🎉 Processing complete: {cloudinary_url}")
        print(f"💾 Stored in memory cache: {len(_processed_images_cache)} images")
        return cloudinary_url

    finally:
        # Keep files for inspection
        print(f"📂 Temp files preserved for inspection: {temp_files}")

def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(description="AirTracker Image Processor (Mock)")
    parser.add_argument('--url', help='Single image URL to process')
    parser.add_argument('--list-processed', action='store_true', help='List all processed images')

    args = parser.parse_args()

    if args.url:
        result = process_image_mock(args.url)
        if result:
            print(f"\n🎯 Final Cloudinary URL (MOCK): {result}")
        else:
            print("\n❌ Processing failed")
            sys.exit(1)

    elif args.list_processed:
        if _processed_images_cache:
            print(f"\n📋 {len(_processed_images_cache)} processed images in memory:")
            for original_url, data in _processed_images_cache.items():
                print(f"  Original: {original_url}")
                print(f"  Cloudinary: {data['cloudinary_url']}")
                print(f"  Date: {data['processed_date']}")
                print()
        else:
            print("📋 No processed images found in memory.")

    else:
        parser.print_help()

if __name__ == '__main__':
    main()