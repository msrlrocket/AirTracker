#!/usr/bin/env python3
"""Fast multi-threaded airline logo verification for all airlines in dataset"""

import json
import requests
import time
from pathlib import Path
import sys
from concurrent.futures import ThreadPoolExecutor, as_completed
from threading import Lock

# Thread-safe counters
progress_lock = Lock()
results_lock = Lock()

def check_url(url, timeout=3):
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

def load_all_airlines():
    """Load all airlines from the dataset"""
    airlines = []
    airline_file = Path('../mqtt/unified/datasets/airlines.jsonl')

    if not airline_file.exists():
        print(f"❌ Airline dataset not found: {airline_file}")
        return []

    try:
        with open(airline_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                if line.strip():
                    try:
                        airline = json.loads(line)
                        airlines.append(airline)
                    except json.JSONDecodeError as e:
                        print(f"⚠️  Skipping invalid JSON on line {line_num}: {e}")
    except Exception as e:
        print(f"❌ Error reading airlines dataset: {e}")
        return []

    return airlines

def generate_logo_urls(airlines):
    """Generate all possible airline logo URLs"""
    urls = []

    for airline in airlines:
        icao = airline.get('icao', '').strip()
        iata = airline.get('iata', '').strip()
        name = airline.get('name', '').strip()

        # Generate ICAO-based URLs (both BMP and PNG)
        if icao:
            urls.append({
                'url': f"https://zip.spacegeese.com/raw/airline_logo_{icao}.bmp",
                'airline': name,
                'code': icao,
                'code_type': 'ICAO',
                'format': 'BMP'
            })
            urls.append({
                'url': f"https://zip.spacegeese.com/raw/airline_logo_{icao}.png",
                'airline': name,
                'code': icao,
                'code_type': 'ICAO',
                'format': 'PNG'
            })

        # Generate IATA-based URLs (both BMP and PNG)
        if iata:
            urls.append({
                'url': f"https://zip.spacegeese.com/raw/airline_logo_{iata}.bmp",
                'airline': name,
                'code': iata,
                'code_type': 'IATA',
                'format': 'BMP'
            })
            urls.append({
                'url': f"https://zip.spacegeese.com/raw/airline_logo_{iata}.png",
                'airline': name,
                'code': iata,
                'code_type': 'IATA',
                'format': 'PNG'
            })

    # Remove duplicates by URL
    seen_urls = set()
    unique_urls = []
    for item in urls:
        if item['url'] not in seen_urls:
            seen_urls.add(item['url'])
            unique_urls.append(item)

    return unique_urls

def print_progress_bar(current, total, prefix='Progress', suffix='Complete', length=50, working=0, failed=0):
    """Print a progress bar"""
    percent = (current / total) * 100
    filled_length = int(length * current // total)
    bar = '█' * filled_length + '-' * (length - filled_length)
    print(f'\r{prefix} |{bar}| {current}/{total} ({percent:.1f}%) - ✅{working} ❌{failed} {suffix}', end='', flush=True)

def check_url_worker(item):
    """Worker function for thread pool"""
    result = check_url(item['url'])
    item.update(result)
    return item

def main():
    print("🚀 Fast Multi-threaded Airline Logo Verification")
    print("=" * 60)

    # Load all airlines
    print("📋 Loading airline dataset...")
    airlines = load_all_airlines()
    if not airlines:
        print("❌ No airlines found in dataset")
        return

    print(f"✅ Loaded {len(airlines)} airlines from dataset")

    # Generate all possible logo URLs
    print("🔗 Generating logo URLs...")
    logo_items = generate_logo_urls(airlines)
    print(f"✅ Generated {len(logo_items)} unique logo URLs to check")

    # Multi-threaded checking with progress
    print(f"\n🌐 Checking {len(logo_items)} airline logo URLs with 10 threads...")
    print("=" * 60)

    results = {
        'working': [],
        'broken': [],
        'errors': []
    }

    start_time = time.time()
    completed = 0

    # Use ThreadPoolExecutor for concurrent requests
    with ThreadPoolExecutor(max_workers=10) as executor:
        # Submit all tasks
        future_to_item = {executor.submit(check_url_worker, item): item for item in logo_items}

        # Process completed tasks
        for future in as_completed(future_to_item):
            item = future.result()

            # Thread-safe result categorization
            with results_lock:
                if item['working']:
                    results['working'].append(item)
                elif item.get('error'):
                    results['errors'].append(item)
                else:
                    results['broken'].append(item)

            # Thread-safe progress update
            with progress_lock:
                completed += 1
                working_count = len(results['working'])
                failed_count = len(results['broken']) + len(results['errors'])
                print_progress_bar(completed, len(logo_items),
                                 prefix='Checking',
                                 suffix='',
                                 working=working_count,
                                 failed=failed_count)

    # Clear progress bar
    print()

    elapsed = time.time() - start_time

    # Final Summary
    print("\n" + "=" * 60)
    print("📊 FAST AIRLINE LOGO VERIFICATION RESULTS")
    print("=" * 60)
    print(f"✅ Working:     {len(results['working']):4d}")
    print(f"❌ Broken:      {len(results['broken']):4d}")
    print(f"🔥 Errors:      {len(results['errors']):4d}")
    print(f"📊 Total:       {len(logo_items):4d}")
    print(f"⏱️  Time:        {elapsed:.1f}s")
    print(f"🚀 Speed:       {len(logo_items)/elapsed:.1f} URLs/sec")

    if results['working']:
        success_rate = len(results['working']) / len(logo_items) * 100
        print(f"🎯 Success Rate: {success_rate:.1f}%")

    # Show working airlines (first 20)
    if results['working']:
        print(f"\n✅ WORKING LOGOS (showing first 20 of {len(results['working'])}):")
        for item in results['working'][:20]:
            size_info = f" ({item['content_length']} bytes)" if item['content_length'] else ""
            format_info = f" [{item['format']}]" if 'format' in item else ""
            print(f"  • {item['code']} ({item['code_type']}) - {item['airline']}{format_info}{size_info}")

        if len(results['working']) > 20:
            print(f"  ... and {len(results['working']) - 20} more working logos")

    # Show broken URLs
    if results['broken']:
        print(f"\n❌ BROKEN LOGOS ({len(results['broken'])}):")
        for item in results['broken']:
            format_info = f" [{item['format']}]" if 'format' in item else ""
            print(f"  • {item['code']} ({item['code_type']}) - {item['airline']}{format_info} - HTTP {item['status_code']}")

    # Show error URLs
    if results['errors']:
        print(f"\n🔥 ERROR LOGOS ({len(results['errors'])}):")
        for item in results['errors']:
            format_info = f" [{item['format']}]" if 'format' in item else ""
            print(f"  • {item['code']} ({item['code_type']}) - {item['airline']}{format_info} - {item['error']}")

    # Save detailed results
    results_file = Path('fast_airline_logo_results.json')
    with open(results_file, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\n💾 Detailed results saved to: {results_file}")

    # Summary message
    total_broken = len(results['broken']) + len(results['errors'])
    if total_broken == 0:
        print(f"\n🎉 ALL {len(results['working'])} AIRLINE LOGOS ARE WORKING PERFECTLY!")
    else:
        print(f"\n⚠️  {total_broken} airline logos need attention out of {len(logo_items)} total")
        print(f"✅ {len(results['working'])} logos are working correctly")

    # Exit code
    sys.exit(0 if total_broken == 0 else 1)

if __name__ == '__main__':
    main()