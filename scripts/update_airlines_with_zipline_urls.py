#!/usr/bin/env python3
"""Update airlines.jsonl with correct Zipline PNG URLs from upload results"""

import json
from pathlib import Path

def main():
    print("🔗 Updating airlines.jsonl with correct Zipline PNG URLs")
    print("=" * 60)

    # Load upload results from the corrected upload
    results_file = Path('airline_png_upload_results_corrected.json')
    if not results_file.exists():
        print("❌ Upload results file not found")
        return

    print("📂 Loading upload results...")
    with open(results_file, 'r') as f:
        upload_results = json.load(f)

    # Create mapping of airline codes to their actual Zipline URLs
    print("🗺️  Creating URL mapping...")
    url_mapping = {}
    successful_uploads = 0

    for result in upload_results:
        if result.get('success') and result.get('url'):
            # Extract airline code from filename (airline_logo_XXX.png)
            filename = result['filename']
            if filename.startswith('airline_logo_') and filename.endswith('.png'):
                code = filename[13:-4]  # Remove 'airline_logo_' and '.png'
                url_mapping[code] = result['url']  # Use the actual Zipline URL
                successful_uploads += 1

    print(f"✅ Found {successful_uploads} successful uploads with URLs")

    # Load and update airlines dataset
    airlines_file = Path('../mqtt/unified/datasets/airlines.jsonl')
    if not airlines_file.exists():
        print("❌ Airlines dataset not found")
        return

    print("📋 Loading airlines dataset...")
    updated_airlines = []
    updated_count = 0
    total_airlines = 0

    with open(airlines_file, 'r') as f:
        for line in f:
            if line.strip():
                total_airlines += 1
                airline = json.loads(line)
                icao = airline.get('icao', '').strip()
                iata = airline.get('iata', '').strip()

                # Check if we have a PNG logo URL for this airline
                png_url = None

                # Check ICAO code first (more specific)
                if icao and icao in url_mapping:
                    png_url = url_mapping[icao]
                # Then check IATA code
                elif iata and iata in url_mapping:
                    png_url = url_mapping[iata]

                # Add the PNG URL if we found one
                if png_url:
                    airline['logo_png_url'] = png_url
                    updated_count += 1

                updated_airlines.append(airline)

    # Write updated dataset
    print(f"💾 Writing updated airlines dataset...")
    with open(airlines_file, 'w') as f:
        for airline in updated_airlines:
            f.write(json.dumps(airline) + '\n')

    print("\n" + "=" * 60)
    print("📊 UPDATE RESULTS")
    print("=" * 60)
    print(f"📋 Total airlines:           {total_airlines:4d}")
    print(f"🔗 Available PNG URLs:       {len(url_mapping):4d}")
    print(f"✅ Airlines updated:         {updated_count:4d}")
    print(f"📊 Coverage:                 {updated_count/total_airlines*100:.1f}%")

    # Show some examples
    print(f"\n✅ SAMPLE UPDATED AIRLINES (first 10):")
    count = 0
    for airline in updated_airlines:
        if airline.get('logo_png_url') and count < 10:
            icao = airline.get('icao', 'None')
            iata = airline.get('iata', 'None')
            name = airline.get('name', 'Unknown')
            url = airline['logo_png_url']
            print(f"  • {name} ({icao}/{iata}): {url}")
            count += 1

    if updated_count > 10:
        print(f"  ... and {updated_count - 10} more airlines with PNG URLs")

    print(f"\n🎉 SUCCESS! Updated {updated_count} airlines with correct Zipline PNG URLs!")
    return True

if __name__ == '__main__':
    success = main()
    exit(0 if success else 1)