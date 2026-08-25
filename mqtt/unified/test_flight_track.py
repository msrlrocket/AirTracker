#!/usr/bin/env python3
"""
Test script to demonstrate GPS track retrieval
Usage: python3 test_flight_track.py <flight_id>
"""

import sys
import json
from datetime import datetime
from airtracker import get_flight_track_fr24_sync

def format_timestamp(ts):
    """Convert unix timestamp to readable time"""
    return datetime.fromtimestamp(ts).strftime('%Y-%m-%d %H:%M:%S')

def main():
    if len(sys.argv) < 2:
        print("Usage: python3 test_flight_track.py <flight_id>")
        print("\nExample flight IDs to try:")
        print("  - Get from your planes_complete.json under flight_schedule[].flight_id")
        print("  - Recent flight IDs only work for completed or in-progress flights")
        sys.exit(1)

    flight_id = sys.argv[1]

    print(f"📡 Fetching GPS track for flight ID: {flight_id}")
    print("=" * 80)

    # Get the track
    result = get_flight_track_fr24_sync(flight_id)

    if result.get('error'):
        print(f"❌ Error: {result['error']}")
        return

    track = result.get('track', [])
    stats = result.get('statistics', {})
    info = result.get('flight_info', {})

    if not track:
        print("❌ No track data available (flight may not have departed yet)")
        return

    # Display flight info
    print(f"\n✈️  Flight Information:")
    print(f"   Callsign: {info.get('callsign', 'N/A')}")
    print(f"   Registration: {info.get('registration', 'N/A')}")
    print(f"   Aircraft: {info.get('aircraft_type', 'N/A')}")
    print(f"   Route: {info.get('origin', 'N/A')} → {info.get('destination', 'N/A')}")

    # Display statistics
    print(f"\n📊 Flight Statistics:")
    print(f"   Total GPS points: {stats.get('total_points', 0):,}")
    print(f"   Duration: {stats.get('duration_seconds', 0) // 60} minutes")
    print(f"   Max altitude: {stats.get('max_altitude_ft', 0):,}ft")
    print(f"   Max speed: {stats.get('max_speed_kts', 0)}kts")

    if stats.get('start_time'):
        print(f"   Departure: {format_timestamp(stats['start_time'])}")
        print(f"   Arrival: {format_timestamp(stats['end_time'])}")

    # Show sample points
    print(f"\n🗺️  GPS Track Sample Points:")
    print(f"\n   TAKEOFF (first 3 points):")
    for i, point in enumerate(track[:3], 1):
        print(f"   {i}. Lat: {point['latitude']:.6f}, Lon: {point['longitude']:.6f}")
        print(f"      Alt: {point['altitude']['feet']:,}ft, Speed: {point['speed']['kts']}kts")

    if len(track) > 6:
        print(f"\n   CRUISE (middle points):")
        mid = len(track) // 2
        for i, point in enumerate(track[mid:mid+2], mid+1):
            print(f"   {i}. Lat: {point['latitude']:.6f}, Lon: {point['longitude']:.6f}")
            print(f"      Alt: {point['altitude']['feet']:,}ft, Speed: {point['speed']['kts']}kts")

    print(f"\n   LANDING (last 3 points):")
    for i, point in enumerate(track[-3:], len(track)-2):
        print(f"   {i}. Lat: {point['latitude']:.6f}, Lon: {point['longitude']:.6f}")
        print(f"      Alt: {point['altitude']['feet']:,}ft, Speed: {point['speed']['kts']}kts")

    # Save to file
    output_file = f"data/flight_track_{flight_id}.json"
    with open(output_file, 'w') as f:
        json.dump(result, f, indent=2)

    print(f"\n💾 Full track saved to: {output_file}")
    print(f"   File size: {len(json.dumps(track)) / 1024:.1f} KB")

if __name__ == "__main__":
    main()
