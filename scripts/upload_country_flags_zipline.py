#!/usr/bin/env python3
"""
Zipline Country Flags Uploader

This script uploads all country flag PNG files to a specific Zipline folder.
One-time batch upload for ESP32 AirTracker project.

Usage:
    python3 upload_country_flags_zipline.py --folder "/path/to/country/flags" --zipline-url "https://zip.spacegeese.com" --folder-id "cmfx44uky000s01mveyv80wbf"
    python3 upload_country_flags_zipline.py --help

Requires ZIPLINE_TOKEN environment variable or --token parameter.
"""

import argparse
import os
import sys
import time
from pathlib import Path
from typing import List, Optional, Tuple

try:
    import requests
    from dotenv import load_dotenv
except ImportError as e:
    print(f"❌ Missing required dependency: {e}")
    print("Install with: pip install requests python-dotenv")
    sys.exit(1)

# Load environment variables
load_dotenv()

def find_flag_files(folder_path: Path) -> List[Path]:
    """Find all PNG flag files in the folder."""
    flag_files = []

    if not folder_path.exists():
        raise ValueError(f"Folder not found: {folder_path}")

    if not folder_path.is_dir():
        raise ValueError(f"Not a directory: {folder_path}")

    # Find all PNG files starting with "country_flag_"
    for file_path in folder_path.iterdir():
        if (file_path.is_file() and
            file_path.suffix.lower() == '.png' and
            file_path.name.startswith('country_flag_')):
            flag_files.append(file_path)

    return sorted(flag_files)

def upload_file_to_zipline(file_path: Path, zipline_url: str, token: str, folder_id: Optional[str] = None) -> Tuple[bool, str, Optional[str]]:
    """
    Upload a single file to Zipline.

    Returns:
        (success, message, file_url) tuple
    """
    try:
        # Prepare the upload
        upload_url = f"{zipline_url.rstrip('/')}/api/upload"

        headers = {
            'authorization': token,  # Use the token directly as shown in example
            'x-zipline-format': 'name'
        }

        # Add folder header if specified
        if folder_id:
            headers['x-zipline-folder'] = folder_id

        # File data - detect MIME type properly
        files = {
            'file': (file_path.name, open(file_path, 'rb'), 'image/png')
        }

        # No additional form data needed based on example
        data = {}

        # Upload the file
        response = requests.post(
            upload_url,
            headers=headers,
            files=files,
            data=data,
            timeout=30
        )

        # Close the file
        files['file'][1].close()

        if response.status_code == 200 or response.status_code == 201:
            try:
                result = response.json()
                # Based on example: .files[0].url
                file_url = result.get('files', [{}])[0].get('url')
                return True, f"Uploaded successfully", file_url
            except Exception as e:
                return True, f"Uploaded (couldn't parse response)", None
        else:
            return False, f"HTTP {response.status_code}: {response.text[:200]}", None

    except requests.exceptions.Timeout:
        return False, "Upload timeout", None
    except requests.exceptions.ConnectionError:
        return False, "Connection error", None
    except Exception as e:
        return False, f"Upload error: {str(e)}", None

def batch_upload_flags(folder_path: Path, zipline_url: str, token: str, zipline_folder_id: Optional[str] = None, delay: float = 0.5) -> Tuple[int, int]:
    """
    Upload all country flag PNG files in folder to Zipline.

    Returns:
        (successful_uploads, total_files) tuple
    """
    flag_files = find_flag_files(folder_path)

    if not flag_files:
        print(f"📁 No country flag PNG files found in: {folder_path}")
        return 0, 0

    print(f"🔄 Found {len(flag_files)} country flag files to upload")
    print(f"📤 Uploading to: {zipline_url}")
    if zipline_folder_id:
        print(f"📁 Target folder ID: {zipline_folder_id}")
    else:
        print(f"📁 Target: Default folder")
    print(f"⏱️  Delay between uploads: {delay}s")
    print()

    successful = 0
    uploaded_urls = []

    for i, file_path in enumerate(flag_files, 1):
        print(f"[{i:4d}/{len(flag_files)}] Uploading: {file_path.name}")

        success, message, file_url = upload_file_to_zipline(
            file_path, zipline_url, token, zipline_folder_id
        )

        if success:
            successful += 1
            print(f"             ✅ {message}")
            if file_url:
                uploaded_urls.append(file_url)
                print(f"             🔗 {file_url}")
        else:
            print(f"             ❌ {message}")

        # Rate limiting delay
        if i < len(flag_files):  # Don't delay after the last file
            time.sleep(delay)

        print()

    return successful, len(flag_files)

def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(
        description="Upload country flag PNG files to Zipline",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python3 upload_country_flags_zipline.py --folder "/path/to/flags"
  python3 upload_country_flags_zipline.py --folder "/path/to/flags" --delay 1.0
  python3 upload_country_flags_zipline.py --folder "/path/to/flags" --token "your_token"

Environment Variables:
  ZIPLINE_TOKEN - Your Zipline authentication token
  ZIPLINE_URL   - Zipline server URL (optional, defaults to https://zip.spacegeese.com)
  ZIPLINE_FOLDER_ID - Target folder ID (optional)
        """
    )

    parser.add_argument('--folder', required=True,
                       help='Folder containing country flag PNG files to upload')
    parser.add_argument('--zipline-url',
                       default=os.getenv('ZIPLINE_URL', 'https://zip.spacegeese.com'),
                       help='Zipline server URL (default: https://zip.spacegeese.com)')
    parser.add_argument('--token',
                       default=os.getenv('ZIPLINE_TOKEN'),
                       help='Zipline authentication token (or set ZIPLINE_TOKEN env var)')
    parser.add_argument('--zipline-folder-id',
                       default='cmfx44uky000s01mveyv80wbf',
                       help='Zipline folder ID to upload to (default: cmfx44uky000s01mveyv80wbf)')
    parser.add_argument('--delay', type=float, default=0.25,
                       help='Delay between uploads in seconds (default: 0.25)')
    parser.add_argument('--dry-run', action='store_true',
                       help='List files that would be uploaded without actually uploading')

    args = parser.parse_args()

    # Validate inputs
    folder_path = Path(args.folder).resolve()

    if not args.token:
        print("❌ Zipline token required!")
        print("Set ZIPLINE_TOKEN environment variable or use --token parameter")
        sys.exit(1)

    if not folder_path.exists():
        print(f"❌ Folder not found: {folder_path}")
        sys.exit(1)

    # Dry run mode
    if args.dry_run:
        print("🧪 DRY RUN MODE - No files will be uploaded")
        print("=" * 50)

        try:
            flag_files = find_flag_files(folder_path)
            print(f"📁 Folder: {folder_path}")
            print(f"📤 Target: {args.zipline_url}")
            print(f"📋 Found {len(flag_files)} country flag PNG files:")

            for i, file_path in enumerate(flag_files[:10], 1):  # Show first 10
                print(f"  {i:3d}. {file_path.name}")

            if len(flag_files) > 10:
                print(f"  ... and {len(flag_files) - 10} more files")

            print(f"\nTo upload, remove --dry-run flag")
            return

        except Exception as e:
            print(f"❌ Error: {e}")
            sys.exit(1)

    # Perform upload
    print("🚀 Zipline Country Flags Uploader")
    print("=" * 50)

    try:
        successful, total = batch_upload_flags(
            folder_path,
            args.zipline_url,
            args.token,
            args.zipline_folder_id,
            args.delay
        )

        # Summary
        print("=" * 50)
        print(f"📊 Upload Summary:")
        print(f"   Total files: {total}")
        print(f"   Successful: {successful}")
        print(f"   Failed: {total - successful}")

        if successful > 0:
            print(f"✅ Successfully uploaded {successful} country flags to Zipline!")
            print(f"🔗 Zipline instance: {args.zipline_url}")

        if total - successful > 0:
            print(f"⚠️  {total - successful} uploads failed")

        # Exit with appropriate code
        sys.exit(0 if successful == total else 1)

    except Exception as e:
        print(f"❌ Upload failed: {e}")
        sys.exit(1)

if __name__ == '__main__':
    main()