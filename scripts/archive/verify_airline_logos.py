#!/usr/bin/env python3
"""Verify all airline logo URLs in the datasets are working"""

import json
import requests
import time
from pathlib import Path
import sys

def check_url(url, timeout=10):
    """Check if a URL returns a valid response"""
    try:
        response = requests.head(url, timeout=timeout)
        return {
            'status_code': response.status_code,
            'content_type': response.headers.get('content-type', ''),
            'content_length': response.headers.get('content-length', ''),
            'working': response.status_code == 200
        }
    except requests.exceptions.RequestException as e:
        return {
            'status_code': None,
            'content_type': '',
            'content_length': '',
            'working': False,
            'error': str(e)
        }

def extract_airline_logos_from_data():
    """Extract airline logo URLs from recent data files"""
    logo_urls = set()

    # Check recent data files
    data_dir = Path('../mqtt/unified/data')
    for data_file in ['planes_complete.json', 'planes.json']:
        file_path = data_dir / data_file
        if file_path.exists():
            try:
                with open(file_path, 'r') as f:
                    data = json.load(f)

                # Extract from planes array
                planes = data.get('planes', [])
                for plane in planes:
                    logo_url = plane.get('airline_logo_url', '')
                    if logo_url and logo_url.strip():
                        logo_urls.add(logo_url.strip())

                # Extract from nearest aircraft
                nearest = data.get('nearest', {})
                if nearest:
                    logo_url = nearest.get('airline_logo_url', '')
                    if logo_url and logo_url.strip():
                        logo_urls.add(logo_url.strip())

                # Extract from nearest_commercial
                nearest_commercial = data.get('nearest_commercial', {})
                if nearest_commercial:
                    logo_url = nearest_commercial.get('airline_logo_url', '')
                    if logo_url and logo_url.strip():
                        logo_urls.add(logo_url.strip())

            except Exception as e:
                print(f"❌ Error reading {file_path}: {e}")

    return list(logo_urls)

def extract_airline_logos_from_datasets():
    """Extract airline logo patterns from airline datasets"""
    logo_patterns = set()

    # Check airline dataset
    airline_file = Path('../mqtt/unified/datasets/airlines.jsonl')
    if airline_file.exists():
        try:
            with open(airline_file, 'r') as f:
                for line in f:
                    if line.strip():
                        airline = json.loads(line)
                        icao = airline.get('icao', '')
                        iata = airline.get('iata', '')

                        # Generate expected logo URLs
                        if icao:
                            logo_patterns.add(f"https://zip.spacegeese.com/raw/airline_logo_{icao}.bmp")
                        if iata:
                            logo_patterns.add(f"https://zip.spacegeese.com/raw/airline_logo_{iata}.bmp")
        except Exception as e:
            print(f"❌ Error reading airlines dataset: {e}")

    return list(logo_patterns)

def main():
    print("🔍 Verifying airline logo URLs...")

    # Extract URLs from recent data
    print("\n📊 Extracting URLs from recent data files...")
    data_urls = extract_airline_logos_from_data()
    print(f"Found {len(data_urls)} unique logo URLs in data files")

    # Extract patterns from datasets
    print("\n📋 Generating URLs from airline datasets...")
    pattern_urls = extract_airline_logos_from_datasets()
    print(f"Generated {len(pattern_urls)} potential logo URLs from datasets")

    # Combine and deduplicate
    all_urls = list(set(data_urls + pattern_urls))
    print(f"\n🔗 Total unique URLs to check: {len(all_urls)}")

    if not all_urls:
        print("❌ No airline logo URLs found to check")
        return

    # Check each URL
    print("\n🌐 Checking URL availability...")
    results = {
        'working': [],
        'broken': [],
        'errors': []
    }

    for i, url in enumerate(all_urls, 1):
        print(f"[{i:3d}/{len(all_urls)}] Checking: {url}")

        result = check_url(url)
        result['url'] = url

        if result['working']:
            results['working'].append(result)
            print(f"    ✅ OK ({result['status_code']}) - {result['content_type']} - {result['content_length']} bytes")
        elif result.get('error'):
            results['errors'].append(result)
            print(f"    ❌ ERROR: {result['error']}")
        else:
            results['broken'].append(result)
            print(f"    ❌ FAILED ({result['status_code']})")

        # Be polite to the server (reduced delay)
        if i < len(all_urls):
            time.sleep(0.1)

    # Summary
    print(f"\n{'='*60}")
    print(f"📊 AIRLINE LOGO VERIFICATION RESULTS:")
    print(f"{'='*60}")
    print(f"✅ Working:    {len(results['working']):3d}")
    print(f"❌ Broken:     {len(results['broken']):3d}")
    print(f"🔥 Errors:     {len(results['errors']):3d}")
    print(f"📊 Total:      {len(all_urls):3d}")

    if results['working']:
        success_rate = len(results['working']) / len(all_urls) * 100
        print(f"🎯 Success Rate: {success_rate:.1f}%")

    # Show broken URLs
    if results['broken']:
        print(f"\n❌ BROKEN URLs ({len(results['broken'])}):")
        for result in results['broken']:
            print(f"  • {result['url']} (HTTP {result['status_code']})")

    # Show error URLs
    if results['errors']:
        print(f"\n🔥 ERROR URLs ({len(results['errors'])}):")
        for result in results['errors']:
            print(f"  • {result['url']}")
            print(f"    Error: {result['error']}")

    # Show working examples
    if results['working']:
        print(f"\n✅ WORKING URLs (showing first 10):")
        for result in results['working'][:10]:
            size_info = f" - {result['content_length']} bytes" if result['content_length'] else ""
            print(f"  • {result['url']} ({result['content_type']}{size_info})")

        if len(results['working']) > 10:
            print(f"  ... and {len(results['working']) - 10} more working URLs")

    # Save detailed results
    results_file = Path('airline_logo_verification_results.json')
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n💾 Detailed results saved to: {results_file}")

    # Exit code
    if results['broken'] or results['errors']:
        print(f"\n⚠️  Some airline logos may need attention!")
        sys.exit(1)
    else:
        print(f"\n🎉 All airline logos are working perfectly!")
        sys.exit(0)

if __name__ == '__main__':
    main()