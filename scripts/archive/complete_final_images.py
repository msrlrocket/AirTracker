#!/usr/bin/env python3
"""Complete the final 2 missing aircraft images"""

import json
import requests
import re
from PIL import Image
from io import BytesIO
from datetime import datetime

def download_and_process_image(image_url, aircraft_name, zipline_url, zipline_token, folder_id):
    """Download image and create both original and ESP32-optimized versions"""
    try:
        print(f"🔍 Downloading image for {aircraft_name}: {image_url}")

        # Download image with proper headers
        headers = {
            'User-Agent': 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36',
            'Accept': 'image/avif,image/webp,image/apng,image/svg+xml,image/*,*/*;q=0.8',
            'Referer': 'https://en.wikipedia.org/' if 'wikimedia' in image_url else 'https://www.military.com/',
        }

        response = requests.get(image_url, headers=headers, timeout=30)
        response.raise_for_status()

        # Validate it's actually an image
        content_type = response.headers.get('content-type', '')
        if not content_type.startswith('image/'):
            print(f"❌ Not an image: {content_type}")
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

        # Upload both versions
        safe_name = re.sub(r'[^a-zA-Z0-9_-]', '_', aircraft_name)

        original_filename = f"{safe_name}_original.jpg"
        esp32_filename = f"{safe_name}_esp32.bmp"

        original_url = upload_to_zipline(original_bytes, original_filename, zipline_url, zipline_token, folder_id, False)
        esp32_url = upload_to_zipline(esp32_bytes, esp32_filename, zipline_url, zipline_token, folder_id, True)

        if original_url and esp32_url:
            return {
                "original_url": image_url,
                "zipline_url": original_url,
                "zipline_esp32_url": esp32_url,
                "width": original_resized.size[0],
                "height": original_resized.size[1],
                "esp32_width": 96,
                "esp32_height": 72,
                "alt_text": f"{aircraft_name} in flight",
                "source_page": "Manual addition - high quality source",
                "processed_at": datetime.now().isoformat(),
                "source": "Manual completion"
            }

        return None

    except Exception as e:
        print(f"❌ Error processing image {image_url}: {e}")
        return None

def upload_to_zipline(image_data, filename, zipline_url, zipline_token, folder_id, is_bmp=False):
    """Upload image to Zipline and return the URL"""
    try:
        print(f"📤 Uploading to Zipline: {filename}")

        upload_url = f"{zipline_url}/api/upload"

        files = {
            'file': (filename, image_data, 'image/bmp' if is_bmp else 'image/jpeg')
        }

        data = {
            'folder': folder_id,
            'expires': '',
            'password': '',
            'maxViews': '',
            'zeroWidth': 'false'
        }

        headers = {
            'Authorization': zipline_token
        }

        response = requests.post(upload_url, files=files, data=data, headers=headers, timeout=60)
        response.raise_for_status()

        result = response.json()

        if 'files' in result and len(result['files']) > 0:
            uploaded_file = result['files'][0]
            url = uploaded_file.get('url', '')
            print(f"✅ Uploaded: {url}")
            return url
        else:
            print(f"❌ Upload failed: {result}")
            return None

    except Exception as e:
        print(f"❌ Upload error for {filename}: {e}")
        return None

def main():
    import os

    zipline_url = os.getenv('ZIPLINE_URL', 'https://zip.spacegeese.com')
    zipline_token = os.getenv('ZIPLINE_TOKEN')
    folder_id = "cmg5jdflb000s01mvpjgckdvk"

    if not zipline_token:
        print("❌ ZIPLINE_TOKEN environment variable not set")
        return

    # Load current dataset
    with open('../mqtt/unified/datasets/military_aircraft_final.json', 'r') as f:
        data = json.load(f)

    # Define the missing aircraft and their image URLs
    missing_aircraft = {
        "EP-3 Ares II": "https://upload.wikimedia.org/wikipedia/commons/thumb/b/bd/U_S_-Navy-Lockheed-EP-3E-Aries-II.jpg/600px-U_S_-Navy-Lockheed-EP-3E-Aries-II.jpg",
        "VH-3D Sea King": "https://images05.military.com/sites/default/files/media/equipment/military-aircraft/vh-3d-sea-king/2014/02/vh-3d-sea-king_001.jpg"
    }

    print(f"🚁 Completing final 2 aircraft images...")

    updated_count = 0

    for aircraft in data['aircraft']:
        aircraft_name = aircraft['name']

        if aircraft_name in missing_aircraft:
            if aircraft.get('images') and len(aircraft.get('images', [])) > 0:
                print(f"⏭️ {aircraft_name} already has images, skipping...")
                continue

            print(f"\n🔍 Processing: {aircraft_name}")

            image_url = missing_aircraft[aircraft_name]
            image_data = download_and_process_image(
                image_url, aircraft_name, zipline_url, zipline_token, folder_id
            )

            if image_data:
                aircraft['images'] = [image_data]
                updated_count += 1
                print(f"✅ {aircraft_name} completed!")
                print(f"   Original: {image_data['zipline_url']}")
                print(f"   ESP32: {image_data['zipline_esp32_url']}")
            else:
                print(f"❌ Failed to process {aircraft_name}")

    # Update metadata
    data['metadata']['aircraft_with_images'] = sum(1 for a in data['aircraft'] if a.get('images') and len(a.get('images', [])) > 0)
    data['metadata']['last_updated'] = datetime.now().isoformat()
    data['metadata']['version'] = '2.0'
    data['metadata']['image_completion'] = f"{data['metadata']['aircraft_with_images']}/{len(data['aircraft'])} ({data['metadata']['aircraft_with_images']/len(data['aircraft'])*100:.1f}%)"

    if data['metadata']['aircraft_with_images'] == len(data['aircraft']):
        data['metadata']['image_status'] = "100% COMPLETE - All aircraft have verified images"

    # Save updated dataset
    with open('../mqtt/unified/datasets/military_aircraft_final.json', 'w') as f:
        json.dump(data, f, indent=2)

    # Update JSONL too
    with open('../mqtt/unified/datasets/military_aircraft_final.jsonl', 'w') as f:
        for aircraft in data['aircraft']:
            f.write(json.dumps(aircraft) + '\n')

    print(f"\n🎉 FINAL COMPLETION RESULTS:")
    print(f"📊 Updated: {updated_count} aircraft")
    print(f"📊 Total with images: {data['metadata']['aircraft_with_images']}/{len(data['aircraft'])} ({data['metadata']['aircraft_with_images']/len(data['aircraft'])*100:.1f}%)")

    if data['metadata']['aircraft_with_images'] == len(data['aircraft']):
        print(f"\n🎊 100% IMAGE COVERAGE ACHIEVED! 🎊")
        print(f"All {len(data['aircraft'])} military aircraft now have complete image data!")
        print(f"🏆 MILITARY AIRCRAFT DATASET COMPLETE - VERSION 2.0 🏆")

if __name__ == '__main__':
    main()