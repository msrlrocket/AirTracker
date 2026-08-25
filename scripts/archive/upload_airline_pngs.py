#!/usr/bin/env python3
"""Upload airline logo PNGs to Zipline and update dataset with PNG URLs"""

import json
import requests
import os
from pathlib import Path
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Configuration
ZIPLINE_URL = os.getenv('ZIPLINE_URL', 'https://zip.spacegeese.com')
ZIPLINE_TOKEN = os.getenv('ZIPLINE_TOKEN')
ZIPLINE_FOLDER_ID = 'cmg5jcr9x000q01mvcd9siqm8'  # PNG logos folder
PNG_LOGOS_DIR = Path('../mqtt/producer/datasets/airline_logos')
AIRLINES_DATASET = Path('../mqtt/unified/datasets/airlines.jsonl')

# Thread-safe progress tracking
progress_lock = Lock()
uploaded_count = 0
failed_count = 0

def upload_to_zipline(file_path, filename):
    """Upload a single file to Zipline"""
    try:
        # Prepare the upload
        with open(file_path, 'rb') as f:
            files = {'file': (filename, f, 'image/png')}
            data = {'folderId': ZIPLINE_FOLDER_ID}
            headers = {'Authorization': ZIPLINE_TOKEN}

            response = requests.post(
                f'{ZIPLINE_URL}/api/upload',
                files=files,
                data=data,
                headers=headers,
                timeout=30
            )

            if response.status_code == 200:
                result = response.json()
                # Extract URL from Zipline response structure
                zipline_url = ''
                if 'files' in result and len(result['files']) > 0:
                    zipline_url = result['files'][0].get('url', '')

                return {
                    'success': True,
                    'filename': filename,
                    'url': f"{ZIPLINE_URL}/raw/{filename}",
                    'zipline_url': zipline_url,
                    'size': file_path.stat().st_size
                }
            else:
                return {
                    'success': False,
                    'filename': filename,
                    'error': f"HTTP {response.status_code}: {response.text}"
                }

    except Exception as e:
        return {
            'success': False,
            'filename': filename,
            'error': str(e)
        }

def update_progress(success=True):
    """Update progress counters thread-safely"""
    global uploaded_count, failed_count
    with progress_lock:
        if success:
            uploaded_count += 1
        else:
            failed_count += 1

def print_progress(current, total, uploaded, failed):
    """Print progress bar"""
    percent = (current / total) * 100
    filled_length = int(50 * current // total)
    bar = '█' * filled_length + '-' * (50 - filled_length)
    print(f'\rUploading |{bar}| {current}/{total} ({percent:.1f}%) - ✅{uploaded} ❌{failed}', end='', flush=True)

def load_airlines_dataset():
    """Load airlines dataset to create mapping"""
    airlines = {}
    if AIRLINES_DATASET.exists():
        try:
            with open(AIRLINES_DATASET, 'r') as f:
                for line in f:
                    if line.strip():
                        airline = json.loads(line)
                        icao = airline.get('icao', '').strip()
                        iata = airline.get('iata', '').strip()
                        if icao:
                            airlines[icao] = airline
                        if iata:
                            airlines[iata] = airline
        except Exception as e:
            print(f"❌ Error loading airlines dataset: {e}")
    return airlines

def update_airlines_dataset(upload_results):
    """Update airlines dataset with PNG URLs"""
    print("\n📝 Updating airlines dataset with PNG URLs...")

    airlines = load_airlines_dataset()

    # Create mapping of successful uploads
    png_urls = {}
    for result in upload_results:
        if result['success']:
            # Extract airline code from filename (airline_logo_XXX.png)
            filename = result['filename']
            if filename.startswith('airline_logo_') and filename.endswith('.png'):
                code = filename[13:-4]  # Remove 'airline_logo_' and '.png'
                png_urls[code] = result['url']

    # Update airlines with PNG URLs
    updated_airlines = []
    updated_count = 0

    if AIRLINES_DATASET.exists():
        with open(AIRLINES_DATASET, 'r') as f:
            for line in f:
                if line.strip():
                    airline = json.loads(line)
                    icao = airline.get('icao', '').strip()
                    iata = airline.get('iata', '').strip()

                    # Add PNG URL if available
                    png_url = None
                    if icao and icao in png_urls:
                        png_url = png_urls[icao]
                    elif iata and iata in png_urls:
                        png_url = png_urls[iata]

                    if png_url:
                        airline['logo_png_url'] = png_url
                        updated_count += 1

                    updated_airlines.append(airline)

    # Write updated dataset
    with open(AIRLINES_DATASET, 'w') as f:
        for airline in updated_airlines:
            f.write(json.dumps(airline) + '\n')

    print(f"✅ Updated {updated_count} airlines with PNG logo URLs")
    return updated_count

def main():
    print("🚀 Uploading Airline Logo PNGs to Zipline")
    print("=" * 60)

    if not ZIPLINE_TOKEN:
        print("❌ ZIPLINE_TOKEN environment variable not set")
        return

    # Find all PNG files
    png_files = list(PNG_LOGOS_DIR.glob('*.png'))
    if not png_files:
        print(f"❌ No PNG files found in {PNG_LOGOS_DIR}")
        return

    print(f"📁 Found {len(png_files)} PNG logo files")
    print(f"🎯 Uploading to Zipline folder: {ZIPLINE_FOLDER_ID}")

    # Upload files with progress tracking
    print(f"\n🌐 Uploading {len(png_files)} files with 5 threads...")
    print("=" * 60)

    upload_results = []
    completed = 0
    start_time = time.time()

    with ThreadPoolExecutor(max_workers=5) as executor:
        # Submit all upload tasks
        future_to_file = {
            executor.submit(upload_to_zipline, file_path, file_path.name): file_path
            for file_path in png_files
        }

        # Process completed uploads
        for future in as_completed(future_to_file):
            result = future.result()
            upload_results.append(result)

            update_progress(result['success'])
            completed += 1

            with progress_lock:
                print_progress(completed, len(png_files), uploaded_count, failed_count)

    print()  # Clear progress bar
    elapsed = time.time() - start_time

    # Summary
    successful_uploads = [r for r in upload_results if r['success']]
    failed_uploads = [r for r in upload_results if not r['success']]

    print("\n" + "=" * 60)
    print("📊 UPLOAD RESULTS")
    print("=" * 60)
    print(f"✅ Successful:  {len(successful_uploads):4d}")
    print(f"❌ Failed:      {len(failed_uploads):4d}")
    print(f"📊 Total:       {len(png_files):4d}")
    print(f"⏱️  Time:        {elapsed:.1f}s")
    print(f"🚀 Speed:       {len(png_files)/elapsed:.1f} files/sec")

    if successful_uploads:
        success_rate = len(successful_uploads) / len(png_files) * 100
        print(f"🎯 Success Rate: {success_rate:.1f}%")

    # Show failed uploads
    if failed_uploads:
        print(f"\n❌ FAILED UPLOADS ({len(failed_uploads)}):")
        for result in failed_uploads[:10]:  # Show first 10 failures
            print(f"  • {result['filename']}: {result['error']}")
        if len(failed_uploads) > 10:
            print(f"  ... and {len(failed_uploads) - 10} more failures")

    # Update dataset with PNG URLs
    if successful_uploads:
        updated_count = update_airlines_dataset(upload_results)

        # Save upload results for reference
        results_file = Path('airline_png_upload_results.json')
        with open(results_file, 'w') as f:
            json.dump(upload_results, f, indent=2)
        print(f"\n💾 Upload results saved to: {results_file}")

    # Summary message
    if len(failed_uploads) == 0:
        print(f"\n🎉 ALL {len(successful_uploads)} AIRLINE PNG LOGOS UPLOADED SUCCESSFULLY!")
    else:
        print(f"\n⚠️  {len(failed_uploads)} uploads failed out of {len(png_files)} total")
        print(f"✅ {len(successful_uploads)} PNG logos uploaded successfully")

    return len(failed_uploads) == 0

if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)