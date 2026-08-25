#!/usr/bin/env python3
"""Create final deduplicated military aircraft dataset optimized for AirTracker system"""

import json
import re
from datetime import datetime
from collections import defaultdict

def merge_duplicate_aircraft(aircraft_list):
    """Merge duplicate aircraft entries, prioritizing those with more data"""

    # Group by name (case insensitive)
    groups = defaultdict(list)
    for aircraft in aircraft_list:
        name_key = aircraft.get('name', '').lower().strip()
        if name_key:
            groups[name_key].append(aircraft)

    merged = []

    for name_key, group in groups.items():
        if len(group) == 1:
            # No duplicates, add as-is
            merged.append(group[0])
        else:
            # Merge duplicates - prioritize entry with more complete data
            print(f"  🔄 Merging {len(group)} duplicates: {group[0]['name']}")

            # Sort by data completeness (ICAO, images, scraped data)
            def score_completeness(aircraft):
                score = 0
                if aircraft.get('icao'): score += 10
                if aircraft.get('images'): score += len(aircraft['images'])
                if aircraft.get('url'): score += 5
                if aircraft.get('engines') and aircraft['engines'] != 'Unknown': score += 3
                if aircraft.get('seats'): score += 2
                return score

            group = sorted(group, key=score_completeness, reverse=True)
            best = group[0]

            # Merge additional data from other entries
            for other in group[1:]:
                # Merge images
                if other.get('images') and not best.get('images'):
                    best['images'] = other['images']
                elif other.get('images') and best.get('images'):
                    # Combine unique images
                    existing_urls = {img.get('original_url') for img in best['images']}
                    for img in other['images']:
                        if img.get('original_url') not in existing_urls:
                            best['images'].append(img)

                # Use scraped data if missing
                if other.get('url') and not best.get('url'):
                    best['url'] = other['url']
                if other.get('description') and not best.get('description'):
                    best['description'] = other['description']
                if other.get('category') and not best.get('category'):
                    best['category'] = other['category']

            merged.append(best)

    return merged

def is_invalid_aircraft(aircraft):
    """Check if aircraft entry should be filtered out"""
    name = aircraft.get('name', '').lower()

    # Filter out non-aircraft entries
    invalid_patterns = [
        'military aircraft',
        'electronics',
        'military vehicles',
        'ordnance',
        'personal equipment',
        'ships and submarines',
        'weapons',
        'edit equipment',
        len(name) < 3
    ]

    return any(pattern in name if isinstance(pattern, str) else pattern for pattern in invalid_patterns)

def clean_aircraft_data(aircraft):
    """Clean and standardize aircraft data"""
    # Clean name
    if aircraft.get('name'):
        aircraft['name'] = re.sub(r'\s+', ' ', aircraft['name']).strip()

    # Ensure required fields exist
    if not aircraft.get('icao'):
        aircraft['icao'] = None
    if not aircraft.get('iata'):
        aircraft['iata'] = []
    if not aircraft.get('variants'):
        aircraft['variants'] = []
    if not aircraft.get('images'):
        aircraft['images'] = []

    # Clean description
    if aircraft.get('description'):
        desc = aircraft['description']
        if len(desc) > 500:  # Truncate overly long descriptions
            aircraft['description'] = desc[:500] + '...'

    return aircraft

def create_airtracker_optimized_dataset():
    """Create final dataset optimized for AirTracker"""

    print("🔧 Creating final military aircraft dataset for AirTracker...\n")

    # Load clean JSONL
    aircraft_list = []
    with open('../mqtt/unified/datasets/military_aircraft_clean.jsonl', 'r') as f:
        for line in f:
            aircraft_list.append(json.loads(line))

    print(f"📊 Loaded {len(aircraft_list)} aircraft from clean JSONL")

    # Filter out invalid entries
    print("🔍 Filtering out invalid aircraft entries...")
    valid_aircraft = [aircraft for aircraft in aircraft_list if not is_invalid_aircraft(aircraft)]
    print(f"  ✅ Kept {len(valid_aircraft)} valid aircraft (removed {len(aircraft_list) - len(valid_aircraft)})")

    # Merge duplicates
    print("🔄 Merging duplicate aircraft...")
    merged_aircraft = merge_duplicate_aircraft(valid_aircraft)
    print(f"  ✅ Result: {len(merged_aircraft)} unique aircraft (merged {len(valid_aircraft) - len(merged_aircraft)} duplicates)")

    # Clean and standardize data
    print("🧹 Cleaning aircraft data...")
    final_aircraft = []
    for aircraft in merged_aircraft:
        cleaned = clean_aircraft_data(aircraft)
        final_aircraft.append(cleaned)

    # Sort by ICAO code, then by name
    print("📊 Sorting aircraft...")
    final_aircraft.sort(key=lambda x: (x.get('icao') or 'ZZZZ', x.get('name', '')))

    # Create final dataset structure
    dataset = {
        'metadata': {
            'name': 'Military Aircraft Dataset for AirTracker',
            'description': 'Comprehensive military aircraft database with ICAO codes, specifications, and images',
            'created_at': datetime.now().isoformat(),
            'total_aircraft': len(final_aircraft),
            'aircraft_with_icao': sum(1 for a in final_aircraft if a.get('icao')),
            'aircraft_with_images': sum(1 for a in final_aircraft if a.get('images')),
            'version': '1.0'
        },
        'aircraft': final_aircraft
    }

    # Save as JSON for AirTracker
    output_file = '../mqtt/unified/datasets/military_aircraft_final.json'
    with open(output_file, 'w') as f:
        json.dump(dataset, f, indent=2)

    # Also save as JSONL for compatibility
    output_jsonl = '../mqtt/unified/datasets/military_aircraft_final.jsonl'
    with open(output_jsonl, 'w') as f:
        for aircraft in final_aircraft:
            f.write(json.dumps(aircraft) + '\n')

    print(f"\n✅ Final dataset created!")
    print(f"📁 JSON: {output_file}")
    print(f"📁 JSONL: {output_jsonl}")
    print(f"📊 Total aircraft: {len(final_aircraft)}")
    print(f"📊 With ICAO codes: {dataset['metadata']['aircraft_with_icao']}")
    print(f"📊 With images: {dataset['metadata']['aircraft_with_images']}")

    # Statistics by type
    type_counts = defaultdict(int)
    for aircraft in final_aircraft:
        aircraft_type = aircraft.get('aircraft_type', 'Unknown')
        type_counts[aircraft_type] += 1

    print(f"\n📋 Aircraft by type:")
    for aircraft_type, count in sorted(type_counts.items()):
        print(f"  • {aircraft_type}: {count}")

    # Show sample entries
    print(f"\n📋 Sample entries with ICAO codes:")
    icao_aircraft = [a for a in final_aircraft if a.get('icao')][:5]
    for aircraft in icao_aircraft:
        print(f"  • {aircraft['name']}")
        print(f"    ICAO: {aircraft['icao']} | Type: {aircraft.get('aircraft_type')} | Images: {len(aircraft.get('images', []))}")

    return dataset

if __name__ == '__main__':
    create_airtracker_optimized_dataset()