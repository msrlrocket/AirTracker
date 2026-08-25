#!/usr/bin/env python3
"""Quick check of airline logos from recent data"""

import json
import requests
from pathlib import Path

def check_url(url):
    """Quick URL check"""
    try:
        response = requests.head(url, timeout=5)
        return response.status_code == 200, response.status_code
    except:
        return False, 'ERROR'

def main():
    print("🔍 Quick airline logo verification...")

    # Extract URLs from recent data
    logo_urls = set()
    data_file = Path('../mqtt/unified/data/planes_complete.json')

    if data_file.exists():
        with open(data_file, 'r') as f:
            data = json.load(f)

        # Extract from planes
        for plane in data.get('planes', []):
            url = plane.get('airline_logo_url', '')
            if url and url.strip():
                logo_urls.add(url.strip())

    print(f"Found {len(logo_urls)} unique airline logo URLs")

    # Test each URL
    working = []
    broken = []

    for i, url in enumerate(sorted(logo_urls), 1):
        print(f"[{i:2d}/{len(logo_urls)}] {url}")

        is_working, status = check_url(url)
        if is_working:
            working.append(url)
            print(f"    ✅ Working")
        else:
            broken.append((url, status))
            print(f"    ❌ Failed ({status})")

    print(f"\n{'='*50}")
    print(f"📊 RESULTS:")
    print(f"✅ Working: {len(working)}")
    print(f"❌ Broken:  {len(broken)}")
    print(f"📊 Total:   {len(logo_urls)}")

    if broken:
        print(f"\n❌ Broken URLs:")
        for url, status in broken:
            print(f"  • {url} ({status})")

    if len(working) == len(logo_urls):
        print(f"\n🎉 All airline logos are working perfectly!")
    else:
        print(f"\n⚠️  {len(broken)} airline logos need attention")

if __name__ == '__main__':
    main()