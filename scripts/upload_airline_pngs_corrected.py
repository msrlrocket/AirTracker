#!/usr/bin/env python3
"""Upload airline logo PNGs to Zipline using the WORKING method from airtracker scripts"""

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
ZIPLINE_FOLDER_ID = 'cmg5jd07c000r01mv53s7zt2l'  # Aircraft folder from unified config
PNG_LOGOS_DIR = Path('../mqtt/producer/datasets/airline_logos')

# Thread-safe progress tracking
progress_lock = Lock()
uploaded_count = 0
failed_count = 0

def upload_to_zipline(file_path, filename):
    """Upload a single file to Zipline using the WORKING method"""
    try:
        # Use the CORRECT parameters from working airtracker scripts
        with open(file_path, 'rb') as f:
            files = {'file': (filename, f, 'image/png')}
            # CRITICAL: Use 'folder' NOT 'folderId' - this was the bug!
            data = {
                'folder': ZIPLINE_FOLDER_ID,  # CORRECT parameter name
                'expires': '',
                'password': '',
                'maxViews': '',
                'zeroWidth': 'false'
            }
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
                # Extract the direct URL from response
                direct_url = ''
                if 'files' in result and len(result['files']) > 0:
                    # Get the direct URL to the uploaded file
                    file_data = result['files'][0]
                    if 'url' in file_data:
                        direct_url = file_data['url']

                return {
                    'success': True,
                    'filename': filename,
                    'url': direct_url,
                    'raw_url': f"{ZIPLINE_URL}/raw/{filename}",
                    'size': file_path.stat().st_size,
                    'response': result
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

def main():
    print("🚀 CORRECTED Airline Logo PNG Upload to Zipline")
    print("=== Using WORKING method from airtracker scripts ===")
    print("=" * 70)

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
    print(f"🔧 Using CORRECT parameter: 'folder' (not 'folderId')")

    # Upload files with progress tracking
    print(f"\n🌐 Uploading {len(png_files)} files with 5 threads...")
    print("=" * 70)

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

    print("\n" + "=" * 70)
    print("📊 CORRECTED UPLOAD RESULTS")
    print("=" * 70)
    print(f"✅ Successful:  {len(successful_uploads):4d}")
    print(f"❌ Failed:      {len(failed_uploads):4d}")
    print(f"📊 Total:       {len(png_files):4d}")
    print(f"⏱️  Time:        {elapsed:.1f}s")
    print(f"🚀 Speed:       {len(png_files)/elapsed:.1f} files/sec")

    if successful_uploads:
        success_rate = len(successful_uploads) / len(png_files) * 100
        print(f"🎯 Success Rate: {success_rate:.1f}%")

    # Show successful uploads (first 10)
    if successful_uploads:
        print(f"\n✅ SUCCESSFUL UPLOADS (showing first 10 of {len(successful_uploads)}):")
        for result in successful_uploads[:10]:
            print(f"  • {result['filename']}: {result['url']}")
        if len(successful_uploads) > 10:
            print(f"  ... and {len(successful_uploads) - 10} more successful uploads")

    # Show failed uploads
    if failed_uploads:
        print(f"\n❌ FAILED UPLOADS ({len(failed_uploads)}):")
        for result in failed_uploads[:10]:  # Show first 10 failures
            print(f"  • {result['filename']}: {result['error']}")
        if len(failed_uploads) > 10:
            print(f"  ... and {len(failed_uploads) - 10} more failures")

    # Save upload results for reference
    results_file = Path('airline_png_upload_results_corrected.json')
    with open(results_file, 'w') as f:
        json.dump(upload_results, f, indent=2)
    print(f"\n💾 Upload results saved to: {results_file}")

    # Summary message
    if len(failed_uploads) == 0:
        print(f"\n🎉 ALL {len(successful_uploads)} AIRLINE PNG LOGOS UPLOADED SUCCESSFULLY!")
        print(f"🔗 They should now be accessible in the Zipline folder")
    else:
        print(f"\n⚠️  {len(failed_uploads)} uploads failed out of {len(png_files)} total")
        print(f"✅ {len(successful_uploads)} PNG logos uploaded successfully")

    return len(failed_uploads) == 0

if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)