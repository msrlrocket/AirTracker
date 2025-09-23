#!/usr/bin/env python3
"""
AirTracker Image Manager

This script manages processed images and provides URLs for other scripts to use.
It works alongside image_processor.py to provide a clean interface for
accessing processed aircraft images stored in memory.

Usage:
    # Import for use in other scripts
    from image_manager import get_processed_url, list_processed_images

    # CLI usage
    python3 image_manager.py --get-url "https://original-image.com/aircraft.jpg"
    python3 image_manager.py --list-all
    python3 image_manager.py --export-urls urls.txt
"""

import argparse
import json
import os
import sys
from datetime import datetime
from typing import Dict, List, Optional

# Import the global cache from image_processor
try:
    from image_processor import _processed_images_cache
except ImportError:
    _processed_images_cache = {}


def get_processed_url(original_url: str) -> Optional[str]:
    """Get Zipline URL for an original image URL from in-memory cache."""
    entry = _processed_images_cache.get(original_url)
    return entry['zipline_url'] if entry else None


def list_processed_images() -> Dict:
    """Get all processed images from in-memory cache."""
    return _processed_images_cache.copy()


def get_latest_processed(count: int = 10) -> List[Dict]:
    """Get the latest N processed images from in-memory cache."""
    # Sort by processed_date
    sorted_items = sorted(
        _processed_images_cache.items(),
        key=lambda x: x[1].get('processed_date', ''),
        reverse=True
    )

    results = []
    for original_url, data in sorted_items[:count]:
        results.append({
            'original_url': original_url,
            'zipline_url': data['zipline_url'],
            'processed_date': data['processed_date'],
            'dimensions': data.get('dimensions', 'unknown'),
            'format': data.get('format', 'BMP')
        })

    return results


def search_processed_images(pattern: str) -> List[Dict]:
    """Search for images by URL pattern in in-memory cache."""
    results = []
    pattern_lower = pattern.lower()

    for original_url, data in _processed_images_cache.items():
        if pattern_lower in original_url.lower():
            results.append({
                'original_url': original_url,
                'zipline_url': data['zipline_url'],
                'processed_date': data['processed_date']
            })

    return results


class ImageManager:
    """Manages access to processed images - wrapper for backward compatibility."""

    def __init__(self, processed_file: str = "data/processed_images.json"):
        self.processed_file = processed_file

    def get_zipline_url(self, original_url: str) -> Optional[str]:
        """Get Zipline URL for an original image URL."""
        return get_processed_url(original_url)

    def list_all(self) -> Dict:
        """Get all processed images."""
        return list_processed_images()

    def get_latest(self, count: int = 10) -> List[Dict]:
        """Get the latest N processed images."""
        return get_latest_processed(count)

    def search_by_pattern(self, pattern: str) -> List[Dict]:
        """Search for images by URL pattern."""
        return search_processed_images(pattern)

    def load_from_json(self) -> Dict:
        """Load processed images from JSON file into memory cache."""
        if os.path.exists(self.processed_file):
            try:
                with open(self.processed_file, 'r') as f:
                    data = json.load(f)
                    _processed_images_cache.update(data)
                    print(f"📂 Loaded {len(data)} images from {self.processed_file} into memory")
                    return data
            except (json.JSONDecodeError, IOError) as e:
                print(f"❌ Error loading processed images: {e}")
                return {}
        return {}

    def export_urls(self, output_file: str, url_type: str = 'cloudinary') -> int:
        """Export URLs to a text file."""
        try:
            with open(output_file, 'w') as f:
                count = 0
                for original_url, data in _processed_images_cache.items():
                    if url_type == 'zipline':
                        f.write(f"{data['zipline_url']}\n")
                    elif url_type == 'original':
                        f.write(f"{original_url}\n")
                    elif url_type == 'both':
                        f.write(f"{original_url} -> {data['zipline_url']}\n")
                    count += 1

            print(f"✅ Exported {count} URLs to {output_file}")
            return count

        except IOError as e:
            print(f"❌ Export failed: {e}")
            return 0

    def get_stats(self) -> Dict:
        """Get statistics about processed images."""
        if not _processed_images_cache:
            return {'total': 0}

        # Parse dates for statistics
        dates = []
        for data in _processed_images_cache.values():
            try:
                date_str = data.get('processed_date', '')
                if date_str:
                    dates.append(datetime.fromisoformat(date_str.replace('Z', '+00:00')))
            except ValueError:
                continue

        stats = {
            'total': len(_processed_images_cache),
            'oldest': min(dates).isoformat() if dates else None,
            'newest': max(dates).isoformat() if dates else None,
            'formats': {},
            'dimensions': {}
        }

        # Count formats and dimensions
        for data in _processed_images_cache.values():
            fmt = data.get('format', 'unknown')
            dim = data.get('dimensions', 'unknown')

            stats['formats'][fmt] = stats['formats'].get(fmt, 0) + 1
            stats['dimensions'][dim] = stats['dimensions'].get(dim, 0) + 1

        return stats


def main():
    """Main CLI interface."""
    parser = argparse.ArgumentParser(description="AirTracker Image Manager")
    parser.add_argument('--get-url', help='Get Cloudinary URL for original URL')
    parser.add_argument('--list-all', action='store_true', help='List all processed images')
    parser.add_argument('--latest', type=int, help='Get latest N images (default: 10)')
    parser.add_argument('--search', help='Search images by URL pattern')
    parser.add_argument('--export-urls', help='Export URLs to file')
    parser.add_argument('--url-type', choices=['zipline', 'original', 'both'],
                       default='zipline', help='Type of URLs to export')
    parser.add_argument('--stats', action='store_true', help='Show statistics')
    parser.add_argument('--json', action='store_true', help='Output in JSON format')

    args = parser.parse_args()

    if not any([args.get_url, args.list_all, args.latest is not None,
               args.search, args.export_urls, args.stats]):
        parser.print_help()
        sys.exit(1)

    # Initialize manager
    manager = ImageManager()

    if args.get_url:
        zipline_url = manager.get_zipline_url(args.get_url)
        if zipline_url:
            print(zipline_url)
        else:
            print(f"❌ No processed image found for: {args.get_url}", file=sys.stderr)
            sys.exit(1)

    elif args.list_all:
        images = manager.list_all()
        if args.json:
            print(json.dumps(images, indent=2))
        else:
            if images:
                print(f"📋 {len(images)} processed images:")
                for original_url, data in images.items():
                    print(f"  Original: {original_url}")
                    print(f"  Zipline: {data['zipline_url']}")
                    print(f"  Date: {data.get('processed_date', 'unknown')}")
                    print()
            else:
                print("📋 No processed images found.")

    elif args.latest is not None:
        count = args.latest if args.latest > 0 else 10
        latest = manager.get_latest(count)
        if args.json:
            print(json.dumps(latest, indent=2))
        else:
            if latest:
                print(f"📋 Latest {len(latest)} processed images:")
                for img in latest:
                    print(f"  Original: {img['original_url']}")
                    print(f"  Zipline: {img['zipline_url']}")
                    print(f"  Date: {img['processed_date']}")
                    print()
            else:
                print("📋 No processed images found.")

    elif args.search:
        results = manager.search_by_pattern(args.search)
        if args.json:
            print(json.dumps(results, indent=2))
        else:
            if results:
                print(f"🔍 Found {len(results)} images matching '{args.search}':")
                for img in results:
                    print(f"  Original: {img['original_url']}")
                    print(f"  Zipline: {img['zipline_url']}")
                    print()
            else:
                print(f"🔍 No images found matching '{args.search}'")

    elif args.export_urls:
        count = manager.export_urls(args.export_urls, args.url_type)
        if count == 0:
            sys.exit(1)

    elif args.stats:
        stats = manager.get_stats()
        if args.json:
            print(json.dumps(stats, indent=2))
        else:
            print("📊 Image Processing Statistics:")
            print(f"  Total images: {stats['total']}")
            if stats['total'] > 0:
                print(f"  Oldest: {stats.get('oldest', 'unknown')}")
                print(f"  Newest: {stats.get('newest', 'unknown')}")
                print(f"  Formats: {stats.get('formats', {})}")
                print(f"  Dimensions: {stats.get('dimensions', {})}")


if __name__ == '__main__':
    main()