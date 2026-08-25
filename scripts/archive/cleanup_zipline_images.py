#!/usr/bin/env python3
"""
Zipline Image Cleanup Script
Cleans up images from specific folders in Zipline.
"""

import os
import requests
import json
from typing import List, Dict

class ZiplineCleanup:
    def __init__(self, zipline_url: str, zipline_token: str):
        self.zipline_url = zipline_url.rstrip('/')
        self.zipline_token = zipline_token
        self.session = requests.Session()
        self.session.headers.update({'Authorization': zipline_token})

    def get_user_files(self) -> List[Dict]:
        """Get all files for the current user."""
        try:
            response = self.session.get(f"{self.zipline_url}/api/user/files")
            response.raise_for_status()
            return response.json()
        except Exception as e:
            print(f"❌ Error getting files: {e}")
            return []

    def delete_file(self, file_id: str) -> bool:
        """Delete a specific file by ID."""
        try:
            response = self.session.delete(f"{self.zipline_url}/api/upload/{file_id}")
            response.raise_for_status()
            return True
        except Exception as e:
            print(f"❌ Error deleting file {file_id}: {e}")
            return False

    def cleanup_by_pattern(self, patterns: List[str], dry_run: bool = True):
        """Clean up files matching specific patterns."""
        print(f"🔍 Getting all user files...")
        files = self.get_user_files()

        if not files:
            print("❌ No files found or error accessing files")
            return

        print(f"📊 Found {len(files)} total files")

        # Find matching files
        matching_files = []
        for file_info in files:
            filename = file_info.get('name', '').lower()
            for pattern in patterns:
                if pattern.lower() in filename:
                    matching_files.append(file_info)
                    break

        print(f"🎯 Found {len(matching_files)} files matching patterns: {patterns}")

        if not matching_files:
            print("✅ No files to delete")
            return

        # Show what would be deleted
        print("\n📋 Files to delete:")
        for i, file_info in enumerate(matching_files, 1):
            name = file_info.get('name', 'Unknown')
            file_id = file_info.get('id', 'Unknown')
            size = file_info.get('size', 0)
            created = file_info.get('created_at', 'Unknown')
            print(f"  {i}. {name} (ID: {file_id}, Size: {size} bytes, Created: {created})")

        if dry_run:
            print(f"\n🔬 DRY RUN: Would delete {len(matching_files)} files")
            print("To actually delete, run with --delete flag")
            return

        # Confirm deletion
        confirm = input(f"\n⚠️  Are you sure you want to delete {len(matching_files)} files? (yes/no): ")
        if confirm.lower() != 'yes':
            print("❌ Deletion cancelled")
            return

        # Delete files
        print(f"\n🗑️  Deleting {len(matching_files)} files...")
        deleted = 0
        for file_info in matching_files:
            file_id = file_info.get('id')
            filename = file_info.get('name', 'Unknown')

            if self.delete_file(file_id):
                deleted += 1
                print(f"  ✅ Deleted: {filename}")
            else:
                print(f"  ❌ Failed: {filename}")

        print(f"\n📊 Cleanup complete: {deleted}/{len(matching_files)} files deleted")

def main():
    import argparse

    parser = argparse.ArgumentParser(description='Clean up Zipline images')
    parser.add_argument('--delete', action='store_true', help='Actually delete files (default is dry run)')
    parser.add_argument('--pattern', action='append', help='Filename patterns to match (can specify multiple)')
    parser.add_argument('--military', action='store_true', help='Clean up military aircraft images')
    parser.add_argument('--aircraft', action='store_true', help='Clean up all aircraft images')
    parser.add_argument('--all', action='store_true', help='Clean up all user files (DANGEROUS)')

    args = parser.parse_args()

    # Get credentials from environment
    zipline_url = os.getenv('ZIPLINE_URL', 'https://zip.spacegeese.com')
    zipline_token = os.getenv('ZIPLINE_TOKEN')

    if not zipline_token:
        print("❌ ZIPLINE_TOKEN environment variable not set")
        print("Set it with: export ZIPLINE_TOKEN='your_token_here'")
        return

    # Determine patterns to clean
    patterns = []

    if args.pattern:
        patterns.extend(args.pattern)

    if args.military:
        patterns.extend(['military_', '_esp32.bmp', '_original.jpg'])

    if args.aircraft:
        patterns.extend(['aircraft_', '_esp32.bmp', '_original.jpg'])

    if args.all:
        patterns = ['']  # Empty pattern matches everything

    if not patterns:
        print("❌ No cleanup patterns specified")
        print("Use --military, --aircraft, --pattern, or --all")
        print("Examples:")
        print("  python3 cleanup_zipline_images.py --military")
        print("  python3 cleanup_zipline_images.py --pattern 'test_' --delete")
        print("  python3 cleanup_zipline_images.py --all --delete")
        return

    print("🧹 Zipline Image Cleanup Tool")
    print("=" * 40)
    print(f"🌐 Zipline URL: {zipline_url}")
    print(f"🔑 Token: {'Set' if zipline_token else 'Not set'}")
    print(f"🎯 Patterns: {patterns}")
    print(f"🔬 Mode: {'DELETE' if args.delete else 'DRY RUN'}")
    print()

    # Initialize cleanup
    cleanup = ZiplineCleanup(zipline_url, zipline_token)
    cleanup.cleanup_by_pattern(patterns, dry_run=not args.delete)

if __name__ == '__main__':
    main()