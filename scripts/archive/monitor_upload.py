#!/usr/bin/env python3
"""Monitor airline PNG upload progress"""

import subprocess
import time
import os

def check_upload_progress():
    """Check if upload is running and show progress"""

    # Check if process is running
    try:
        result = subprocess.run(['ps', 'aux'], capture_output=True, text=True)
        upload_lines = [line for line in result.stdout.split('\n') if 'upload_airline_pngs.py' in line and 'grep' not in line]

        if not upload_lines:
            print("❌ Upload process not running")

            # Check if results file exists
            if os.path.exists('airline_png_upload_results.json'):
                print("✅ Upload completed! Results file found.")
                with open('airline_png_upload_results.json', 'r') as f:
                    import json
                    results = json.load(f)
                    successful = len([r for r in results if r.get('success', False)])
                    failed = len([r for r in results if not r.get('success', False)])
                    print(f"📊 Final Results: ✅{successful} ❌{failed}")
            else:
                print("⚠️  No results file found yet")
            return False

        print("🚀 Upload process is running")
        for line in upload_lines:
            parts = line.split()
            if len(parts) > 10:
                print(f"   PID: {parts[1]} | CPU: {parts[2]}% | Memory: {parts[3]}%")

        return True

    except Exception as e:
        print(f"❌ Error checking process: {e}")
        return False

def main():
    print("🔍 Airline PNG Upload Monitor")
    print("=" * 50)

    while True:
        print(f"\n⏰ {time.strftime('%H:%M:%S')} - Checking upload status...")

        if not check_upload_progress():
            print("\n🏁 Monitoring stopped - upload not running")
            break

        print("💤 Waiting 10 seconds... (Ctrl+C to exit)")
        try:
            time.sleep(10)
        except KeyboardInterrupt:
            print("\n\n👋 Monitoring stopped by user")
            break

if __name__ == '__main__':
    main()