#!/usr/bin/env python3
"""Extract actual Zipline URLs from upload results and create airline logo mapping"""

import json
from pathlib import Path

def main():
    print("🔗 Extracting Zipline URLs from upload results...")

    results_file = Path('airline_png_upload_results.json')
    if not results_file.exists():
        print("❌ Upload results file not found")
        return

    # Load upload results
    with open(results_file, 'r') as f:
        upload_results = json.load(f)

    # Extract URL mappings
    url_mapping = {}
    working_count = 0
    broken_count = 0

    for result in upload_results:
        if result.get('success') and result.get('zipline_url'):
            # Extract airline code from filename (airline_logo_XXX.png)
            filename = result['filename']
            if filename.startswith('airline_logo_') and filename.endswith('.png'):
                code = filename[13:-4]  # Remove 'airline_logo_' and '.png'
                url_mapping[code] = result['zipline_url']
                working_count += 1
        else:
            broken_count += 1

    print(f"✅ Extracted {working_count} working Zipline URLs")
    print(f"❌ Found {broken_count} broken/missing URLs")

    # Save mapping to file
    mapping_file = Path('../mqtt/unified/datasets/airline_logo_png_urls.json')
    with open(mapping_file, 'w') as f:
        json.dump(url_mapping, f, indent=2)

    print(f"💾 Saved URL mapping to: {mapping_file}")

    # Show some examples
    print(f"\n📋 Sample mappings:")
    for i, (code, url) in enumerate(list(url_mapping.items())[:10]):
        print(f"  • {code}: {url}")

    if len(url_mapping) > 10:
        print(f"  ... and {len(url_mapping) - 10} more")

    print(f"\n🎯 Ready to update unified script with {len(url_mapping)} PNG logo URLs!")

if __name__ == '__main__':
    main()