#!/usr/bin/env python3
"""Add missing ICAO codes to military aircraft dataset"""

import json
import re
from datetime import datetime

def create_icao_mapping():
    """Create mapping of aircraft names to ICAO codes"""

    # Known military aircraft ICAO codes from aviation databases
    icao_mapping = {
        # A-10 variants
        'a-10': 'A10',
        'a-10 warthog': 'A10',
        'a-10 thunderbolt': 'A10',

        # AC-130 variants
        'ac-130': 'C130',
        'ac-130h': 'C130',
        'ac-130u': 'C130',
        'ac-130w': 'C130',
        'ac-130j': 'C130',

        # AH-1 variants
        'ah-1w': 'AH1',
        'ah-1z': 'AH1',
        'ah-1 super cobra': 'AH1',
        'ah-1 viper': 'AH1',

        # AH-64 variants
        'ah-64 apache': 'AH64',
        'ah-64 longbow': 'AH64',
        'ah-64d': 'AH64',
        'ah-64e': 'AH64',

        # AV-8 Harrier
        'av-8': 'AV8',
        'av-8b': 'AV8',
        'harrier': 'AV8',

        # B-1 Lancer
        'b-1': 'B1',
        'b-1b': 'B1',
        'lancer': 'B1',

        # B-2 Spirit
        'b-2': 'B2',
        'spirit': 'B2',

        # C-2 Greyhound
        'c-2': 'C2',
        'c-2a': 'C2',
        'greyhound': 'C2',

        # C-5 Galaxy
        'c-5': 'C5',
        'galaxy': 'C5',

        # C-9 Skytrain
        'c-9': 'C9',
        'skytrain': 'C9',

        # C-12 variants
        'c-12': 'C12',
        'huron': 'C12',

        # C-20 Gulfstream
        'c-20': 'C20',
        'gulfstream': 'GLF',  # Generic Gulfstream

        # C-21 Learjet
        'c-21': 'C21',

        # C-32 variants
        'c-32': 'C32',
        'air force two': 'C32',

        # C-37 Gulfstream
        'c-37': 'C37',

        # C-40 Clipper
        'c-40': 'C40',
        'clipper': 'C40',

        # CV-22 Osprey
        'cv-22': 'CV22',
        'osprey': 'V22',
        'mv-22': 'MV22',

        # E-2 Hawkeye
        'e-2': 'E2',
        'hawkeye': 'E2',

        # E-3 Sentry
        'e-3': 'E3',
        'sentry': 'E3',
        'awacs': 'E3',

        # E-4 variants
        'e-4': 'E4',
        'e-4b': 'E4',

        # E-6 Mercury
        'e-6': 'E6',
        'mercury': 'E6',

        # E-8 Joint STARS
        'e-8': 'E8',
        'joint stars': 'E8',

        # E-9 Widget
        'e-9': 'E9',
        'widget': 'E9',

        # EA-6 Prowler
        'ea-6': 'EA6',
        'prowler': 'EA6',

        # EA-18 Growler
        'ea-18': 'EA18',
        'growler': 'EA18',

        # EC-130 variants
        'ec-130': 'C130',

        # F-5 Tiger
        'f-5': 'F5',
        'tiger': 'F5',
        'tigershark': 'F5',

        # F-15 variants
        'f-15': 'F15',
        'eagle': 'F15',
        'strike eagle': 'F15',

        # F/A-18 variants
        'f/a-18': 'F18',
        'fa-18': 'F18',
        'hornet': 'F18',
        'super hornet': 'F18',

        # HC-130 variants
        'hc-130': 'C130',

        # HU-25 Guardian
        'hu-25': 'HU25',
        'guardian': 'HU25',

        # KC-10 Extender
        'kc-10': 'KC10',
        'extender': 'KC10',

        # KC-46 Tanker
        'kc-46': 'KC46',

        # MH-47 Chinook
        'mh-47': 'CH47',

        # MH-53 variants
        'mh-53': 'CH53',
        'sea dragon': 'CH53',

        # MH-60 variants
        'mh-60': 'MH60',
        'jayhawk': 'MH60',
        'knighthawk': 'MH60',
        'sea hawk': 'SH60',

        # MH-65 Dolphin
        'mh-65': 'MH65',
        'dolphin': 'MH65',

        # MQ-1 Predator
        'mq-1': 'MQ1',
        'predator': 'MQ1',

        # MQ-8 Fire Scout
        'mq-8': 'MQ8',
        'fire scout': 'MQ8',

        # MQ-9 Reaper
        'mq-9': 'MQ9',
        'reaper': 'MQ9',

        # OH-58 Kiowa
        'oh-58': 'OH58',
        'kiowa': 'OH58',

        # P-3 Orion
        'p-3': 'P3',
        'orion': 'P3',
        'ep-3': 'P3',

        # RC-135 variants
        'rc-135': 'RC135',
        'rivet joint': 'RC135',
        'cobra ball': 'RC135',

        # RQ-2 Pioneer
        'rq-2': 'RQ2',
        'pioneer': 'RQ2',

        # RQ-7 Shadow
        'rq-7': 'RQ7',
        'shadow': 'RQ7',

        # RQ-11 Raven
        'rq-11': 'RQ11',
        'raven': 'RQ11',

        # S-3 Viking
        's-3': 'S3',
        'viking': 'S3',

        # T-1 Jayhawk
        't-1': 'T1',
        't-1a': 'T1',

        # T-2 Buckeye
        't-2': 'T2',
        'buckeye': 'T2',

        # T-34 Turbo Mentor
        't-34': 'T34',
        'turbo mentor': 'T34',

        # TH-57 Sea Ranger
        'th-57': 'TH57',
        'sea ranger': 'TH57',

        # U-6 Beaver
        'u-6': 'U6',
        'beaver': 'U6',

        # U-28 variants
        'u-28': 'U28',

        # UH-72 Lakota
        'uh-72': 'UH72',
        'lakota': 'UH72',

        # VC-25 Air Force One
        'vc-25': 'VC25',
        'air force one': 'VC25',

        # VH-3 Sea King
        'vh-3': 'VH3',
        'sea king': 'VH3',

        # VH-60 variants
        'vh-60': 'VH60',

        # WC-130/135 weather variants
        'wc-130': 'C130',
        'wc-135': 'C135',
    }

    return icao_mapping

def find_icao_for_aircraft(aircraft_name, icao_mapping):
    """Find ICAO code for an aircraft based on name matching"""

    # Clean and normalize the name
    clean_name = aircraft_name.lower()
    clean_name = re.sub(r'[^\w\s-]', ' ', clean_name)
    clean_name = re.sub(r'\s+', ' ', clean_name).strip()

    # Try exact matches first
    if clean_name in icao_mapping:
        return icao_mapping[clean_name]

    # Try partial matches
    for pattern, icao in icao_mapping.items():
        if pattern in clean_name:
            return icao

    # Try to extract common patterns
    # F-XX pattern (fighters)
    f_match = re.search(r'f-?(\d+)', clean_name)
    if f_match:
        return f'F{f_match.group(1)}'

    # C-XX pattern (cargo/transport)
    c_match = re.search(r'c-?(\d+)', clean_name)
    if c_match:
        return f'C{c_match.group(1)}'

    # B-XX pattern (bombers)
    b_match = re.search(r'b-?(\d+)', clean_name)
    if b_match:
        return f'B{b_match.group(1)}'

    return None

def add_icao_codes():
    """Add missing ICAO codes to the dataset"""

    print("🔧 Adding missing ICAO codes to military aircraft dataset...")

    # Load the dataset
    with open('../mqtt/unified/datasets/military_aircraft_final.json', 'r') as f:
        data = json.load(f)

    icao_mapping = create_icao_mapping()

    added_count = 0
    total_without_icao = 0

    for aircraft in data['aircraft']:
        if not aircraft.get('icao'):
            total_without_icao += 1
            icao = find_icao_for_aircraft(aircraft['name'], icao_mapping)
            if icao:
                aircraft['icao'] = icao
                added_count += 1
                print(f"  ✅ {aircraft['name']} → {icao}")

    # Update metadata
    data['metadata']['aircraft_with_icao'] = sum(1 for a in data['aircraft'] if a.get('icao'))
    data['metadata']['last_updated'] = datetime.now().isoformat()
    data['metadata']['version'] = '1.1'

    # Save updated dataset
    with open('../mqtt/unified/datasets/military_aircraft_final.json', 'w') as f:
        json.dump(data, f, indent=2)

    # Update JSONL too
    with open('../mqtt/unified/datasets/military_aircraft_final.jsonl', 'w') as f:
        for aircraft in data['aircraft']:
            f.write(json.dumps(aircraft) + '\n')

    print(f"\n✅ ICAO codes added!")
    print(f"📊 Added codes for: {added_count}/{total_without_icao} aircraft")
    print(f"📊 Total with ICAO: {data['metadata']['aircraft_with_icao']}/{len(data['aircraft'])} ({data['metadata']['aircraft_with_icao']/len(data['aircraft'])*100:.1f}%)")

    # Show some examples
    print(f"\n📋 Sample additions:")
    examples = [a for a in data['aircraft'] if a.get('icao') and a['name'] in [
        "A-10 'Warthog' Thunderbolt II",
        'B-1B Lancer',
        'F-15 Eagle',
        'MQ-9 Reaper',
        'C-5 Galaxy'
    ]][:5]

    for aircraft in examples:
        print(f"  • {aircraft['name']} → {aircraft['icao']}")

if __name__ == '__main__':
    add_icao_codes()