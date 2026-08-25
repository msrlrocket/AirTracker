#!/usr/bin/env python3
"""Create clean military aircraft JSONL prioritizing accurate JSONL data over corrupted scraped data"""

import json
import re
from datetime import datetime
from difflib import SequenceMatcher

def similarity(a, b):
    """Calculate similarity between two strings"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def is_corrupted_spec(value):
    """Check if a specification value is corrupted"""
    if not isinstance(value, str):
        return False

    # Common corruption patterns
    corruption_indicators = [
        'in a MH-65 Dolphin helicopter',
        'Failures, Marine Corps to Field-Test',
        'equipment/military-aircraft',
        'polish navy divers',
        len(value) > 300,  # Overly long values
        value == 's',  # Single character 's'
        'visit our customer support' in value.lower()
    ]

    return any(indicator in value if isinstance(indicator, str) else indicator for indicator in corruption_indicators)

def find_exact_match(aircraft_name, types_data):
    """Find exact or very close match for aircraft"""
    clean_name = re.sub(r'[^\w\s-]', '', aircraft_name.lower().strip())

    # Remove common prefixes/suffixes that might interfere
    clean_name = re.sub(r'^(boeing|lockheed|sikorsky|bell|mcdonnell douglas|fairchild|northrop|grumman)\s+', '', clean_name)
    clean_name = re.sub(r'\s+(aircraft|helicopter|fighter|bomber)$', '', clean_name)

    best_match = None
    best_score = 0

    for aircraft_type in types_data:
        type_name = aircraft_type['name'].lower()
        type_model = aircraft_type.get('model', '').lower()

        # Clean type names similarly
        clean_type = re.sub(r'^(boeing|lockheed|sikorsky|bell|mcdonnell douglas|fairchild|northrop|grumman)\s+', '', type_name)
        clean_model = re.sub(r'^(boeing|lockheed|sikorsky|bell|mcdonnell douglas|fairchild|northrop|grumman)\s+', '', type_model)

        # Calculate multiple similarity scores
        name_score = similarity(clean_name, clean_type)
        model_score = similarity(clean_name, clean_model)

        # Special exact matches for key aircraft
        exact_matches = {
            'f-16 fighting falcon': 'f16',
            'f-35a lightning ii': 'f35',
            'f-35b lightning ii': 'f35',
            'f-35c lightning ii': 'f35',
            'a-10': 'a10',
            'b-52 stratofortress': 'b52',
            'b-1b lancer': 'b1',
            'b-2 spirit': 'b2',
            'c-130 hercules': 'c130',
            'c-17 globemaster': 'c17',
            'c-5 galaxy': 'c5',
            'kc-135 stratotanker': 'kc135',
            'uh-60': 'h60',
            'ah-64 apache': 'h64',
            'ch-47 chinook': 'ch47',
            'ch-53': 'ch53'
        }

        # Check for exact matches
        for pattern, icao in exact_matches.items():
            if pattern in clean_name and aircraft_type.get('icao', '').lower() == icao:
                return aircraft_type, 1.0

        max_score = max(name_score, model_score)
        if max_score > best_score:
            best_score = max_score
            best_match = aircraft_type

    # Only return matches with high confidence
    if best_score >= 0.85:
        return best_match, best_score

    return None, 0

def main():
    print("🔧 Creating clean military aircraft JSONL...")

    # Load the complete dataset
    with open('../mqtt/unified/datasets/military_aircraft_complete.json', 'r') as f:
        complete_data = json.load(f)

    # Load the types JSONL
    types_data = []
    with open('../mqtt/unified/datasets/military_aircraft_types.jsonl', 'r') as f:
        for line in f:
            types_data.append(json.loads(line.strip()))

    print(f"📊 Loaded {len(complete_data['aircraft'])} aircraft from complete dataset")
    print(f"📊 Loaded {len(types_data)} aircraft types from JSONL")

    # Start with clean JSONL data and add images from scraped data
    enhanced_aircraft = []
    matched_count = 0

    # First, process all JSONL aircraft
    for type_aircraft in types_data:
        print(f"🔍 Processing JSONL aircraft: {type_aircraft['name']}")

        # Find corresponding scraped data by name matching
        scraped_match = None
        best_scraped_score = 0

        for scraped in complete_data['aircraft']:
            if len(scraped.get('name', '')) < 3:  # Skip corrupted entries
                continue

            score = similarity(type_aircraft['name'], scraped['name'])
            if score > best_scraped_score and score > 0.7:
                best_scraped_score = score
                scraped_match = scraped

        # Create clean enhanced entry starting with JSONL data
        enhanced = {
            'name': type_aircraft['name'],
            'icao': type_aircraft['icao'],
            'iata': type_aircraft.get('iata', []),
            'manufacturer': type_aircraft['manufacturer'],
            'model': type_aircraft['model'],
            'aircraft_type': type_aircraft['type'],
            'role': type_aircraft['role'],
            'engines': type_aircraft['engines'],
            'seats': type_aircraft['seats'],
            'variants': type_aircraft.get('variants', [])
        }

        # Add scraped data if found
        if scraped_match:
            print(f"  ✅ Found scraped data: {scraped_match['name']} (score: {best_scraped_score:.2f})")
            enhanced.update({
                'url': scraped_match.get('url', ''),
                'category': scraped_match.get('category', ''),
                'description': scraped_match.get('description', ''),
                'images': scraped_match.get('images', []),
                'scraped_at': scraped_match.get('scraped_at', ''),
                'scraped_match_score': round(best_scraped_score, 3)
            })

            # Only add clean specifications from scraped data
            scraped_specs = scraped_match.get('specifications', {})
            clean_specs = {}
            for key, value in scraped_specs.items():
                if not is_corrupted_spec(value):
                    clean_specs[key] = value

            if clean_specs:
                enhanced['additional_specifications'] = clean_specs

            matched_count += 1
        else:
            print(f"  ❌ No scraped data found")
            enhanced.update({
                'url': '',
                'category': 'Military Aircraft',
                'description': f'{type_aircraft["role"]} manufactured by {type_aircraft["manufacturer"]}',
                'images': [],
                'scraped_at': '',
                'scraped_match_score': 0
            })

        enhanced_aircraft.append(enhanced)

    # Add any scraped aircraft that weren't matched to JSONL data
    print(f"\n🔍 Checking for unmatched scraped aircraft...")
    matched_names = {aircraft['name'].lower() for aircraft in enhanced_aircraft}

    for scraped in complete_data['aircraft']:
        if len(scraped.get('name', '')) < 3:  # Skip corrupted entries
            continue

        scraped_name = scraped['name'].lower()

        # Check if this scraped aircraft was already matched
        already_matched = False
        for matched_name in matched_names:
            if similarity(scraped_name, matched_name) > 0.7:
                already_matched = True
                break

        if not already_matched:
            print(f"  📝 Adding unmatched: {scraped['name']}")

            # Create entry with scraped data only
            enhanced = {
                'name': scraped['name'],
                'icao': None,
                'iata': [],
                'manufacturer': 'Unknown',
                'model': scraped['name'],
                'aircraft_type': 'Unknown',
                'role': 'Unknown',
                'engines': 'Unknown',
                'seats': None,
                'variants': [],
                'url': scraped.get('url', ''),
                'category': scraped.get('category', ''),
                'description': scraped.get('description', ''),
                'images': scraped.get('images', []),
                'scraped_at': scraped.get('scraped_at', ''),
                'scraped_match_score': 0
            }

            # Try to infer basic aircraft type from name
            name_lower = scraped['name'].lower()
            if any(word in name_lower for word in ['helicopter', 'hawk', 'huey', 'apache', 'chinook']):
                enhanced['aircraft_type'] = 'Helicopter'
            elif any(word in name_lower for word in ['fighter', 'falcon', 'hornet', 'raptor', 'lightning']):
                enhanced['aircraft_type'] = 'Fighter'
            elif any(word in name_lower for word in ['bomber', 'stratofortress', 'lancer', 'spirit']):
                enhanced['aircraft_type'] = 'Bomber'
            elif any(word in name_lower for word in ['transport', 'hercules', 'galaxy', 'globemaster']):
                enhanced['aircraft_type'] = 'Transport'

            enhanced_aircraft.append(enhanced)

    # Write clean JSONL
    output_file = '../mqtt/unified/datasets/military_aircraft_clean.jsonl'
    with open(output_file, 'w') as f:
        for aircraft in enhanced_aircraft:
            f.write(json.dumps(aircraft) + '\n')

    print(f"\n✅ Clean dataset created!")
    print(f"📊 Total aircraft: {len(enhanced_aircraft)}")
    print(f"📊 JSONL aircraft with scraped data: {matched_count}")
    print(f"📁 Saved to: {output_file}")

    # Statistics
    with_images = sum(1 for a in enhanced_aircraft if a.get('images'))
    with_icao = sum(1 for a in enhanced_aircraft if a.get('icao'))

    print(f"\n📊 Data quality:")
    print(f"  • Aircraft with ICAO codes: {with_icao}")
    print(f"  • Aircraft with images: {with_images}")
    print(f"  • Aircraft with URLs: {sum(1 for a in enhanced_aircraft if a.get('url'))}")

    # Sample entries
    print(f"\n📋 Sample clean entries:")
    for aircraft in enhanced_aircraft[:3]:
        if aircraft.get('icao'):
            print(f"  • {aircraft['name']}")
            print(f"    ICAO: {aircraft['icao']}")
            print(f"    Type: {aircraft['aircraft_type']}")
            print(f"    Manufacturer: {aircraft['manufacturer']}")
            print(f"    Images: {len(aircraft.get('images', []))}")

if __name__ == '__main__':
    main()