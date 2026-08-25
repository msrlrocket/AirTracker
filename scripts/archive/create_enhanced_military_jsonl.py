#!/usr/bin/env python3
"""Create enhanced military aircraft JSONL by merging complete.json with types.jsonl"""

import json
import re
from datetime import datetime
from difflib import SequenceMatcher

def similarity(a, b):
    """Calculate similarity between two strings"""
    return SequenceMatcher(None, a.lower(), b.lower()).ratio()

def find_best_match(aircraft_name, types_data):
    """Find the best matching aircraft from types.jsonl"""
    best_match = None
    best_score = 0

    # Clean the aircraft name for better matching
    clean_name = re.sub(r'[^\w\s-]', '', aircraft_name.lower())

    for aircraft_type in types_data:
        # Try matching against name and model
        type_name = aircraft_type['name'].lower()
        type_model = aircraft_type.get('model', '').lower()

        # Calculate similarity scores
        name_score = similarity(clean_name, type_name)
        model_score = similarity(clean_name, type_model)

        # Also try matching individual words
        name_words = clean_name.split()
        type_words = type_name.split()
        word_matches = 0
        for word in name_words:
            if any(word in type_word or type_word in word for type_word in type_words):
                word_matches += 1
        word_score = word_matches / max(len(name_words), 1) if name_words else 0

        # Best score from all methods
        max_score = max(name_score, model_score, word_score)

        if max_score > best_score and max_score > 0.4:  # Minimum threshold
            best_score = max_score
            best_match = aircraft_type

    return best_match, best_score

def clean_specifications(specs):
    """Clean up corrupted specifications"""
    cleaned = {}
    for key, value in specs.items():
        if isinstance(value, str) and len(value) > 200:
            # Skip overly long/corrupted values
            continue
        if key and value and value != 's':
            cleaned[key] = value
    return cleaned

def main():
    print("🔧 Creating enhanced military aircraft JSONL...")

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

    enhanced_aircraft = []
    matched_count = 0

    for i, aircraft in enumerate(complete_data['aircraft'], 1):
        print(f"🔍 Processing {i}/{len(complete_data['aircraft'])}: {aircraft['name']}")

        # Skip corrupted entries
        if aircraft['name'] == 'Military Aircraft' or len(aircraft['name']) < 3:
            continue

        # Find matching type data
        type_match, score = find_best_match(aircraft['name'], types_data)

        # Create enhanced entry
        enhanced = {
            'name': aircraft['name'],
            'url': aircraft['url'],
            'category': aircraft.get('category', 'Unknown'),
            'description': aircraft.get('description', ''),
            'specifications': clean_specifications(aircraft.get('specifications', {})),
            'images': aircraft.get('images', []),
            'scraped_at': aircraft.get('scraped_at', '')
        }

        # Add type data if found
        if type_match and score > 0.5:
            print(f"  ✅ Matched with {type_match['name']} (score: {score:.2f})")
            enhanced.update({
                'icao': type_match.get('icao'),
                'iata': type_match.get('iata', []),
                'manufacturer': type_match.get('manufacturer'),
                'model': type_match.get('model'),
                'aircraft_type': type_match.get('type'),
                'role': type_match.get('role'),
                'engines': type_match.get('engines'),
                'seats': type_match.get('seats'),
                'variants': type_match.get('variants', []),
                'match_score': round(score, 3)
            })
            matched_count += 1
        else:
            print(f"  ❌ No match found (best score: {score:.2f})")
            # Try to extract basic info from name
            enhanced['match_score'] = 0

            # Simple aircraft type detection
            name_lower = aircraft['name'].lower()
            if any(word in name_lower for word in ['helicopter', 'hawk', 'huey', 'apache', 'chinook']):
                enhanced['aircraft_type'] = 'Helicopter'
            elif any(word in name_lower for word in ['fighter', 'falcon', 'hornet', 'raptor', 'lightning']):
                enhanced['aircraft_type'] = 'Fighter'
            elif any(word in name_lower for word in ['bomber', 'stratofortress', 'lancer', 'spirit']):
                enhanced['aircraft_type'] = 'Bomber'
            elif any(word in name_lower for word in ['transport', 'hercules', 'galaxy', 'globemaster']):
                enhanced['aircraft_type'] = 'Transport'
            elif any(word in name_lower for word in ['tanker', 'stratotanker', 'pegasus']):
                enhanced['aircraft_type'] = 'Tanker'
            elif any(word in name_lower for word in ['trainer', 'texan', 'talon', 'goshawk']):
                enhanced['aircraft_type'] = 'Trainer'
            elif any(word in name_lower for word in ['drone', 'uav', 'hawk', 'predator', 'reaper']):
                enhanced['aircraft_type'] = 'UAV'
            else:
                enhanced['aircraft_type'] = 'Unknown'

        enhanced_aircraft.append(enhanced)

    # Write enhanced JSONL
    output_file = '../mqtt/unified/datasets/military_aircraft_enhanced.jsonl'
    with open(output_file, 'w') as f:
        for aircraft in enhanced_aircraft:
            f.write(json.dumps(aircraft) + '\n')

    print(f"\n✅ Enhanced dataset created!")
    print(f"📊 Total aircraft: {len(enhanced_aircraft)}")
    print(f"📊 Matched with types: {matched_count}/{len(enhanced_aircraft)} ({matched_count/len(enhanced_aircraft)*100:.1f}%)")
    print(f"📁 Saved to: {output_file}")

    # Create summary
    type_counts = {}
    for aircraft in enhanced_aircraft:
        aircraft_type = aircraft.get('aircraft_type', 'Unknown')
        type_counts[aircraft_type] = type_counts.get(aircraft_type, 0) + 1

    print(f"\n📋 Aircraft by type:")
    for aircraft_type, count in sorted(type_counts.items()):
        print(f"  • {aircraft_type}: {count}")

    print(f"\n📋 Sample enhanced entries:")
    for aircraft in enhanced_aircraft[:3]:
        if aircraft.get('icao'):
            print(f"  • {aircraft['name']}")
            print(f"    ICAO: {aircraft.get('icao')}")
            print(f"    Type: {aircraft.get('aircraft_type')}")
            print(f"    Role: {aircraft.get('role')}")
            print(f"    Engines: {aircraft.get('engines')}")
            print(f"    Images: {len(aircraft.get('images', []))}")
            print()

if __name__ == '__main__':
    main()