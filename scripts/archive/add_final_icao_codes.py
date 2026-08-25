#!/usr/bin/env python3
"""Add the final 7 missing ICAO codes to military aircraft dataset"""

import json
from datetime import datetime

def add_final_icao_codes():
    """Add the remaining ICAO codes based on online research"""

    print("🔧 Adding final ICAO codes to military aircraft dataset...")

    # Load the dataset
    with open('../mqtt/unified/datasets/military_aircraft_final.json', 'r') as f:
        data = json.load(f)

    # Mapping of aircraft names to ICAO codes from online research
    final_icao_mapping = {
        'MH-6 Little Bird': 'AH6',  # Same family as AH-6 Little Bird
        'NU-1B Otter': 'DHC3',     # De Havilland Canada DHC-3 Otter
        'RQ-4 Global Hawk': 'Q4',   # Confirmed from doc8643.com
        'T-38 Talon': 'T38',        # Confirmed from aviation databases
        'T-45 Goshawk': 'HAWK',     # Shares code with BAE Hawk family
        'T-6 Texan': 'TEX2',        # Modern T-6 Texan II uses TEX2
        'UH-60A/L Black Hawk Helicopter': 'H60'  # Standard UH-60 code
    }

    added_count = 0

    for aircraft in data['aircraft']:
        if not aircraft.get('icao'):
            name = aircraft['name']
            if name in final_icao_mapping:
                icao = final_icao_mapping[name]
                aircraft['icao'] = icao
                added_count += 1
                print(f"  ✅ {name} → {icao}")

    # Update metadata
    data['metadata']['aircraft_with_icao'] = sum(1 for a in data['aircraft'] if a.get('icao'))
    data['metadata']['last_updated'] = datetime.now().isoformat()
    data['metadata']['version'] = '1.2'
    data['metadata']['icao_completion'] = f"{data['metadata']['aircraft_with_icao']}/{len(data['aircraft'])} ({data['metadata']['aircraft_with_icao']/len(data['aircraft'])*100:.1f}%)"

    # Save updated dataset
    with open('../mqtt/unified/datasets/military_aircraft_final.json', 'w') as f:
        json.dump(data, f, indent=2)

    # Update JSONL too
    with open('../mqtt/unified/datasets/military_aircraft_final.jsonl', 'w') as f:
        for aircraft in data['aircraft']:
            f.write(json.dumps(aircraft) + '\n')

    print(f"\n🎯 Final ICAO codes added!")
    print(f"📊 Added: {added_count} codes")
    print(f"📊 Total with ICAO: {data['metadata']['aircraft_with_icao']}/{len(data['aircraft'])} ({data['metadata']['aircraft_with_icao']/len(data['aircraft'])*100:.1f}%)")

    if data['metadata']['aircraft_with_icao'] == len(data['aircraft']):
        print(f"\n🎉 100% ICAO COVERAGE ACHIEVED! 🎉")
        print(f"All {len(data['aircraft'])} military aircraft now have ICAO codes!")

    print(f"\n📋 Final additions:")
    for name, icao in final_icao_mapping.items():
        print(f"  • {name} → {icao}")

if __name__ == '__main__':
    add_final_icao_codes()