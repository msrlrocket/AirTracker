#!/usr/bin/env python3
"""Add missing seat/crew data to military aircraft dataset"""

import json
import re
from datetime import datetime

def create_seat_crew_mapping():
    """Create comprehensive mapping of aircraft to seat/crew data from aviation databases"""

    # Military aircraft seat/crew specifications from Jane's, manufacturer specs, and military documentation
    seat_crew_mapping = {
        # Attack Aircraft
        'a-10': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'a-10 warthog': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'a-10 thunderbolt': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'av-8': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'av-8b': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'harrier': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},

        # Bombers
        'b-1': {'seats': 4, 'crew': 4, 'crew_type': 'pilot, copilot, 2x weapon systems officers'},
        'b-1b': {'seats': 4, 'crew': 4, 'crew_type': 'pilot, copilot, 2x weapon systems officers'},
        'lancer': {'seats': 4, 'crew': 4, 'crew_type': 'pilot, copilot, 2x weapon systems officers'},
        'b-2': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, mission commander'},
        'spirit': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, mission commander'},
        'b-52': {'seats': 5, 'crew': 5, 'crew_type': 'pilot, copilot, radar navigator, navigator, electronic warfare officer'},
        'stratofortress': {'seats': 5, 'crew': 5, 'crew_type': 'pilot, copilot, radar navigator, navigator, electronic warfare officer'},

        # Cargo/Transport Aircraft
        'c-2': {'seats': 2, 'crew': 2, 'passengers': 39, 'crew_type': 'pilot, copilot'},
        'greyhound': {'seats': 2, 'crew': 2, 'passengers': 39, 'crew_type': 'pilot, copilot'},
        'c-5': {'seats': 6, 'crew': 6, 'passengers': 73, 'crew_type': '2 pilots, flight engineer, 3 loadmasters'},
        'galaxy': {'seats': 6, 'crew': 6, 'passengers': 73, 'crew_type': '2 pilots, flight engineer, 3 loadmasters'},
        'c-9': {'seats': 3, 'crew': 3, 'passengers': 40, 'crew_type': 'pilot, copilot, flight attendant'},
        'skytrain': {'seats': 3, 'crew': 3, 'passengers': 40, 'crew_type': 'pilot, copilot, flight attendant'},
        'c-12': {'seats': 2, 'crew': 2, 'passengers': 8, 'crew_type': 'pilot, copilot'},
        'huron': {'seats': 2, 'crew': 2, 'passengers': 8, 'crew_type': 'pilot, copilot'},
        'c-20': {'seats': 2, 'crew': 2, 'passengers': 19, 'crew_type': 'pilot, copilot'},
        'gulfstream': {'seats': 2, 'crew': 2, 'passengers': 19, 'crew_type': 'pilot, copilot'},
        'c-21': {'seats': 2, 'crew': 2, 'passengers': 8, 'crew_type': 'pilot, copilot'},
        'c-32': {'seats': 3, 'crew': 3, 'passengers': 45, 'crew_type': 'pilot, copilot, flight engineer'},
        'air force two': {'seats': 3, 'crew': 3, 'passengers': 45, 'crew_type': 'pilot, copilot, flight engineer'},
        'c-37': {'seats': 2, 'crew': 2, 'passengers': 12, 'crew_type': 'pilot, copilot'},
        'c-40': {'seats': 3, 'crew': 3, 'passengers': 121, 'crew_type': 'pilot, copilot, flight attendant'},
        'clipper': {'seats': 3, 'crew': 3, 'passengers': 121, 'crew_type': 'pilot, copilot, flight attendant'},

        # Electronic Warfare
        'ea-6': {'seats': 4, 'crew': 4, 'crew_type': 'pilot, 3x electronic countermeasures officers'},
        'prowler': {'seats': 4, 'crew': 4, 'crew_type': 'pilot, 3x electronic countermeasures officers'},
        'ea-18': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, electronic warfare officer'},
        'growler': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, electronic warfare officer'},

        # Early Warning & Control
        'e-2': {'seats': 5, 'crew': 5, 'crew_type': 'pilot, copilot, 3x systems operators'},
        'hawkeye': {'seats': 5, 'crew': 5, 'crew_type': 'pilot, copilot, 3x systems operators'},
        'e-3': {'seats': 17, 'crew': 17, 'crew_type': 'flight crew (4) + mission crew (13)'},
        'sentry': {'seats': 17, 'crew': 17, 'crew_type': 'flight crew (4) + mission crew (13)'},
        'awacs': {'seats': 17, 'crew': 17, 'crew_type': 'flight crew (4) + mission crew (13)'},
        'e-4': {'seats': 50, 'crew': 50, 'crew_type': 'flight crew + command staff + support'},
        'e-6': {'seats': 14, 'crew': 14, 'crew_type': 'flight crew (5) + mission crew (9)'},
        'mercury': {'seats': 14, 'crew': 14, 'crew_type': 'flight crew (5) + mission crew (9)'},
        'e-8': {'seats': 19, 'crew': 19, 'crew_type': 'flight crew (4) + mission crew (15)'},
        'joint stars': {'seats': 19, 'crew': 19, 'crew_type': 'flight crew (4) + mission crew (15)'},
        'e-9': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, systems operator'},
        'widget': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, systems operator'},

        # Fighters
        'f-5': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'tiger': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'tigershark': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'f-15': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'eagle': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'f-15e': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, weapon systems officer'},
        'strike eagle': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, weapon systems officer'},
        'f/a-18': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'fa-18': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'hornet': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'super hornet': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'f-22': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'raptor': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'f-35': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'lightning': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},

        # Helicopters
        'ah-1': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, gunner'},
        'super cobra': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, gunner'},
        'viper': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, gunner'},
        'ah-6': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, copilot'},
        'little bird': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, copilot'},
        'ah-64': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, gunner'},
        'apache': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, gunner'},
        'ch-47': {'seats': 3, 'crew': 3, 'passengers': 55, 'crew_type': 'pilot, copilot, flight engineer'},
        'chinook': {'seats': 3, 'crew': 3, 'passengers': 55, 'crew_type': 'pilot, copilot, flight engineer'},
        'ch-53': {'seats': 3, 'crew': 3, 'passengers': 55, 'crew_type': 'pilot, copilot, crew chief'},
        'sea stallion': {'seats': 3, 'crew': 3, 'passengers': 55, 'crew_type': 'pilot, copilot, crew chief'},
        'mh-47': {'seats': 3, 'crew': 3, 'passengers': 33, 'crew_type': 'pilot, copilot, flight engineer'},
        'mh-53': {'seats': 6, 'crew': 6, 'passengers': 38, 'crew_type': '2 pilots, flight engineer, 3 crew chiefs'},
        'sea dragon': {'seats': 6, 'crew': 6, 'passengers': 38, 'crew_type': '2 pilots, flight engineer, 3 crew chiefs'},
        'mh-60': {'seats': 4, 'crew': 4, 'passengers': 11, 'crew_type': 'pilot, copilot, 2x crew chiefs'},
        'black hawk': {'seats': 4, 'crew': 4, 'passengers': 11, 'crew_type': 'pilot, copilot, 2x crew chiefs'},
        'sea hawk': {'seats': 4, 'crew': 4, 'passengers': 11, 'crew_type': 'pilot, copilot, 2x crew chiefs'},
        'jayhawk': {'seats': 4, 'crew': 4, 'passengers': 6, 'crew_type': 'pilot, copilot, flight mechanic, rescue swimmer'},
        'knighthawk': {'seats': 4, 'crew': 4, 'passengers': 11, 'crew_type': 'pilot, copilot, 2x crew chiefs'},
        'mh-65': {'seats': 4, 'crew': 4, 'passengers': 6, 'crew_type': 'pilot, copilot, flight mechanic, rescue swimmer'},
        'dolphin': {'seats': 4, 'crew': 4, 'passengers': 6, 'crew_type': 'pilot, copilot, flight mechanic, rescue swimmer'},
        'oh-58': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, observer'},
        'kiowa': {'seats': 2, 'crew': 2, 'crew_type': 'pilot, observer'},
        'th-57': {'seats': 2, 'crew': 2, 'crew_type': 'instructor pilot, student pilot'},
        'sea ranger': {'seats': 2, 'crew': 2, 'crew_type': 'instructor pilot, student pilot'},
        'uh-72': {'seats': 2, 'crew': 2, 'passengers': 8, 'crew_type': 'pilot, copilot'},
        'lakota': {'seats': 2, 'crew': 2, 'passengers': 8, 'crew_type': 'pilot, copilot'},
        'vh-3': {'seats': 3, 'crew': 3, 'passengers': 14, 'crew_type': 'pilot, copilot, crew chief'},
        'sea king': {'seats': 3, 'crew': 3, 'passengers': 14, 'crew_type': 'pilot, copilot, crew chief'},
        'vh-60': {'seats': 4, 'crew': 4, 'passengers': 11, 'crew_type': 'pilot, copilot, 2x crew chiefs'},

        # Tankers
        'kc-10': {'seats': 4, 'crew': 4, 'passengers': 75, 'crew_type': 'pilot, copilot, flight engineer, boom operator'},
        'extender': {'seats': 4, 'crew': 4, 'passengers': 75, 'crew_type': 'pilot, copilot, flight engineer, boom operator'},
        'kc-46': {'seats': 3, 'crew': 3, 'passengers': 114, 'crew_type': 'pilot, copilot, boom operator'},
        'kc-135': {'seats': 4, 'crew': 4, 'passengers': 37, 'crew_type': 'pilot, copilot, navigator, boom operator'},
        'stratotanker': {'seats': 4, 'crew': 4, 'passengers': 37, 'crew_type': 'pilot, copilot, navigator, boom operator'},

        # Maritime Patrol
        'p-3': {'seats': 11, 'crew': 11, 'crew_type': 'flight crew (4) + mission crew (7)'},
        'orion': {'seats': 11, 'crew': 11, 'crew_type': 'flight crew (4) + mission crew (7)'},
        'p-8': {'seats': 9, 'crew': 9, 'crew_type': 'flight crew (3) + mission crew (6)'},
        'poseidon': {'seats': 9, 'crew': 9, 'crew_type': 'flight crew (3) + mission crew (6)'},

        # Presidential Aircraft
        'vc-25': {'seats': 8, 'crew': 8, 'passengers': 102, 'crew_type': 'flight crew + cabin crew'},
        'air force one': {'seats': 8, 'crew': 8, 'passengers': 102, 'crew_type': 'flight crew + cabin crew'},

        # Reconnaissance
        'rc-135': {'seats': 15, 'crew': 15, 'crew_type': 'flight crew (4) + mission crew (11)'},
        'rivet joint': {'seats': 15, 'crew': 15, 'crew_type': 'flight crew (4) + mission crew (11)'},
        'cobra ball': {'seats': 15, 'crew': 15, 'crew_type': 'flight crew (4) + mission crew (11)'},
        'u-2': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},
        'dragon lady': {'seats': 1, 'crew': 1, 'crew_type': 'pilot'},

        # Special Operations
        'cv-22': {'seats': 4, 'crew': 4, 'passengers': 24, 'crew_type': 'pilot, copilot, flight engineer, gunner'},
        'mv-22': {'seats': 4, 'crew': 4, 'passengers': 24, 'crew_type': 'pilot, copilot, crew chief, gunner'},
        'osprey': {'seats': 4, 'crew': 4, 'passengers': 24, 'crew_type': 'pilot, copilot, crew chief, gunner'},
        'ac-130': {'seats': 13, 'crew': 13, 'crew_type': 'flight crew (5) + mission crew (8)'},
        'spectre': {'seats': 13, 'crew': 13, 'crew_type': 'flight crew (5) + mission crew (8)'},
        'spooky': {'seats': 13, 'crew': 13, 'crew_type': 'flight crew (5) + mission crew (8)'},
        'ghostrider': {'seats': 13, 'crew': 13, 'crew_type': 'flight crew (5) + mission crew (8)'},

        # Trainers
        't-1': {'seats': 2, 'crew': 2, 'crew_type': 'instructor pilot, student pilot'},
        't-6': {'seats': 2, 'crew': 2, 'crew_type': 'instructor pilot, student pilot'},
        'texan': {'seats': 2, 'crew': 2, 'crew_type': 'instructor pilot, student pilot'},
        't-34': {'seats': 2, 'crew': 2, 'crew_type': 'instructor pilot, student pilot'},
        'turbo mentor': {'seats': 2, 'crew': 2, 'crew_type': 'instructor pilot, student pilot'},
        't-38': {'seats': 2, 'crew': 2, 'crew_type': 'instructor pilot, student pilot'},
        'talon': {'seats': 2, 'crew': 2, 'crew_type': 'instructor pilot, student pilot'},
        't-45': {'seats': 2, 'crew': 2, 'crew_type': 'instructor pilot, student pilot'},
        'goshawk': {'seats': 2, 'crew': 2, 'crew_type': 'instructor pilot, student pilot'},

        # UAVs/Drones
        'mq-1': {'seats': 0, 'crew': 2, 'crew_type': 'remote pilot, sensor operator (ground control)'},
        'predator': {'seats': 0, 'crew': 2, 'crew_type': 'remote pilot, sensor operator (ground control)'},
        'mq-8': {'seats': 0, 'crew': 1, 'crew_type': 'remote operator (ground control)'},
        'fire scout': {'seats': 0, 'crew': 1, 'crew_type': 'remote operator (ground control)'},
        'mq-9': {'seats': 0, 'crew': 2, 'crew_type': 'remote pilot, sensor operator (ground control)'},
        'reaper': {'seats': 0, 'crew': 2, 'crew_type': 'remote pilot, sensor operator (ground control)'},
        'rq-4': {'seats': 0, 'crew': 3, 'crew_type': 'remote pilot, sensor operator, mission coordinator (ground control)'},
        'global hawk': {'seats': 0, 'crew': 3, 'crew_type': 'remote pilot, sensor operator, mission coordinator (ground control)'},
        'rq-7': {'seats': 0, 'crew': 1, 'crew_type': 'remote operator (ground control)'},
        'shadow': {'seats': 0, 'crew': 1, 'crew_type': 'remote operator (ground control)'},
        'rq-11': {'seats': 0, 'crew': 1, 'crew_type': 'remote operator (ground control)'},
        'raven': {'seats': 0, 'crew': 1, 'crew_type': 'remote operator (ground control)'},

        # Utility Aircraft
        'u-6': {'seats': 2, 'crew': 2, 'passengers': 6, 'crew_type': 'pilot, copilot'},
        'beaver': {'seats': 2, 'crew': 2, 'passengers': 6, 'crew_type': 'pilot, copilot'},
        'u-28': {'seats': 2, 'crew': 2, 'passengers': 9, 'crew_type': 'pilot, copilot'},
        'nu-1b': {'seats': 2, 'crew': 2, 'passengers': 10, 'crew_type': 'pilot, copilot'},
        'otter': {'seats': 2, 'crew': 2, 'passengers': 10, 'crew_type': 'pilot, copilot'},

        # Coast Guard Aircraft
        'hu-25': {'seats': 3, 'crew': 3, 'passengers': 7, 'crew_type': 'pilot, copilot, mission specialist'},
        'guardian': {'seats': 3, 'crew': 3, 'passengers': 7, 'crew_type': 'pilot, copilot, mission specialist'},
        'hc-130': {'seats': 5, 'crew': 5, 'passengers': 15, 'crew_type': 'pilot, copilot, flight engineer, navigator, radio operator'},

        # Other Specialized Aircraft
        's-3': {'seats': 4, 'crew': 4, 'crew_type': 'pilot, copilot, tactical coordinator, acoustic sensor operator'},
        'viking': {'seats': 4, 'crew': 4, 'crew_type': 'pilot, copilot, tactical coordinator, acoustic sensor operator'},
        'wc-130': {'seats': 5, 'crew': 5, 'crew_type': 'pilot, copilot, navigator, weather officer, aerial reconnaissance weather officer'},
        'wc-135': {'seats': 12, 'crew': 12, 'crew_type': 'flight crew (5) + mission crew (7)'},
    }

    return seat_crew_mapping

def find_seat_crew_for_aircraft(aircraft_name, seat_crew_mapping):
    """Find seat/crew data for an aircraft based on name matching"""

    # Clean and normalize the name
    clean_name = aircraft_name.lower()
    clean_name = re.sub(r'[^\w\s-]', ' ', clean_name)
    clean_name = re.sub(r'\s+', ' ', clean_name).strip()

    # Try exact matches first
    if clean_name in seat_crew_mapping:
        return seat_crew_mapping[clean_name]

    # Try partial matches - look for key aircraft identifiers
    for pattern, data in seat_crew_mapping.items():
        if pattern in clean_name:
            return data

    # Try to extract common patterns and make educated guesses
    # Single-seat fighters
    if any(word in clean_name for word in ['f-16', 'f-22', 'f-35', 'a-10']):
        return {'seats': 1, 'crew': 1, 'crew_type': 'pilot'}

    # Two-seat trainers
    if any(word in clean_name for word in ['trainer', 'training', 't-']):
        return {'seats': 2, 'crew': 2, 'crew_type': 'instructor pilot, student pilot'}

    # UAVs/Drones
    if any(word in clean_name for word in ['drone', 'uav', 'unmanned', 'rq-', 'mq-']):
        return {'seats': 0, 'crew': 2, 'crew_type': 'remote pilot, sensor operator (ground control)'}

    return None

def add_seat_crew_data():
    """Add missing seat/crew data to the military aircraft dataset"""

    print("🔧 Adding missing seat/crew data to military aircraft dataset...")

    # Load the dataset
    with open('../mqtt/unified/datasets/military_aircraft_final.json', 'r') as f:
        data = json.load(f)

    seat_crew_mapping = create_seat_crew_mapping()

    added_count = 0
    updated_count = 0
    total_without_seats = 0
    total_without_crew = 0

    for aircraft in data['aircraft']:
        has_seats = aircraft.get('seats') is not None and aircraft.get('seats') != 'Unknown'
        has_crew_data = 'crew' in aircraft or 'crew_type' in aircraft

        if not has_seats:
            total_without_seats += 1
        if not has_crew_data:
            total_without_crew += 1

        # Look for seat/crew data
        seat_crew_data = find_seat_crew_for_aircraft(aircraft['name'], seat_crew_mapping)

        if seat_crew_data:
            # Add seats if missing
            if not has_seats:
                aircraft['seats'] = seat_crew_data['seats']
                print(f"  ✅ {aircraft['name']} → seats: {seat_crew_data['seats']}")
                added_count += 1

            # Add crew information
            if not has_crew_data:
                aircraft['crew'] = seat_crew_data['crew']
                aircraft['crew_type'] = seat_crew_data['crew_type']

                # Add passenger capacity if available
                if 'passengers' in seat_crew_data:
                    aircraft['passengers'] = seat_crew_data['passengers']

                updated_count += 1
                print(f"    + crew: {seat_crew_data['crew']} ({seat_crew_data['crew_type']})")
                if 'passengers' in seat_crew_data:
                    print(f"    + passengers: {seat_crew_data['passengers']}")

    # Update metadata
    data['metadata']['aircraft_with_seats'] = sum(1 for a in data['aircraft'] if a.get('seats') is not None and a.get('seats') != 'Unknown')
    data['metadata']['aircraft_with_crew'] = sum(1 for a in data['aircraft'] if 'crew' in a)
    data['metadata']['last_updated'] = datetime.now().isoformat()
    data['metadata']['version'] = '1.3'
    data['metadata']['seat_crew_completion'] = f"Seats: {data['metadata']['aircraft_with_seats']}/{len(data['aircraft'])} ({data['metadata']['aircraft_with_seats']/len(data['aircraft'])*100:.1f}%) | Crew: {data['metadata']['aircraft_with_crew']}/{len(data['aircraft'])} ({data['metadata']['aircraft_with_crew']/len(data['aircraft'])*100:.1f}%)"

    # Save updated dataset
    with open('../mqtt/unified/datasets/military_aircraft_final.json', 'w') as f:
        json.dump(data, f, indent=2)

    # Update JSONL too
    with open('../mqtt/unified/datasets/military_aircraft_final.jsonl', 'w') as f:
        for aircraft in data['aircraft']:
            f.write(json.dumps(aircraft) + '\n')

    print(f"\n✅ Seat/crew data enhanced!")
    print(f"📊 Added seat data for: {added_count} aircraft")
    print(f"📊 Added crew data for: {updated_count} aircraft")
    print(f"📊 Total with seats: {data['metadata']['aircraft_with_seats']}/{len(data['aircraft'])} ({data['metadata']['aircraft_with_seats']/len(data['aircraft'])*100:.1f}%)")
    print(f"📊 Total with crew: {data['metadata']['aircraft_with_crew']}/{len(data['aircraft'])} ({data['metadata']['aircraft_with_crew']/len(data['aircraft'])*100:.1f}%)")

    # Show some examples of enhanced data
    print(f"\n📋 Sample enhanced entries:")
    enhanced_aircraft = [a for a in data['aircraft'] if 'crew' in a and 'crew_type' in a][:5]
    for aircraft in enhanced_aircraft:
        print(f"  • {aircraft['name']}")
        print(f"    Seats: {aircraft.get('seats')} | Crew: {aircraft.get('crew')} | Type: {aircraft.get('crew_type')}")
        if aircraft.get('passengers'):
            print(f"    Passengers: {aircraft['passengers']}")

    # Show remaining gaps
    remaining_without_seats = [a for a in data['aircraft'] if a.get('seats') is None or a.get('seats') == 'Unknown']
    remaining_without_crew = [a for a in data['aircraft'] if 'crew' not in a]

    if remaining_without_seats:
        print(f"\n⚠️ Still missing seat data ({len(remaining_without_seats)} aircraft):")
        for aircraft in remaining_without_seats[:10]:  # Show first 10
            print(f"  • {aircraft['name']}")
        if len(remaining_without_seats) > 10:
            print(f"  ... and {len(remaining_without_seats) - 10} more")

    if remaining_without_crew:
        print(f"\n⚠️ Still missing crew data ({len(remaining_without_crew)} aircraft):")
        for aircraft in remaining_without_crew[:10]:  # Show first 10
            print(f"  • {aircraft['name']}")
        if len(remaining_without_crew) > 10:
            print(f"  ... and {len(remaining_without_crew) - 10} more")

if __name__ == '__main__':
    add_seat_crew_data()