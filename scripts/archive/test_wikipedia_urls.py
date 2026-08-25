#!/usr/bin/env python3
"""Test a few sample Wikipedia Commons URLs to find working image patterns"""

import requests
import json

def test_url(url, name):
    """Test if a URL returns a valid image"""
    try:
        response = requests.head(url, timeout=10)
        if response.status_code == 200:
            content_type = response.headers.get('content-type', '')
            if 'image' in content_type:
                print(f"✅ {name}: {url}")
                return True
            else:
                print(f"❌ {name}: Not an image ({content_type})")
        else:
            print(f"❌ {name}: HTTP {response.status_code}")
    except Exception as e:
        print(f"❌ {name}: Error - {e}")

    return False

def main():
    # Test a few different URL patterns for popular aircraft
    test_urls = [
        # Standard Commons URL patterns
        ("A-10 Standard", "https://upload.wikimedia.org/wikipedia/commons/c/c8/A-10_Thunderbolt_II_In-flight-2.jpg"),
        ("A-10 Thumb", "https://upload.wikimedia.org/wikipedia/commons/thumb/c/c8/A-10_Thunderbolt_II_In-flight-2.jpg/800px-A-10_Thunderbolt_II_In-flight-2.jpg"),

        # Try F-22
        ("F-22 Standard", "https://upload.wikimedia.org/wikipedia/commons/2/2f/F-22_Raptor_edit1.jpg"),
        ("F-22 Thumb", "https://upload.wikimedia.org/wikipedia/commons/thumb/2/2f/F-22_Raptor_edit1.jpg/800px-F-22_Raptor_edit1.jpg"),

        # Try Apache
        ("Apache Standard", "https://upload.wikimedia.org/wikipedia/commons/d/d8/AH-64D_Apache_Longbow.jpg"),
        ("Apache Thumb", "https://upload.wikimedia.org/wikipedia/commons/thumb/d/d8/AH-64D_Apache_Longbow.jpg/800px-AH-64D_Apache_Longbow.jpg"),

        # Try some alternative names
        ("A-10 Alt", "https://upload.wikimedia.org/wikipedia/commons/thumb/9/97/A-10_Thunderbolt_II_In-flight-2.jpg/800px-A-10_Thunderbolt_II_In-flight-2.jpg"),
        ("F-22 Alt", "https://upload.wikimedia.org/wikipedia/commons/thumb/b/b8/F-22_Raptor_-_100702-F-4815G-217.jpg/800px-F-22_Raptor_-_100702-F-4815G-217.jpg"),
    ]

    print("🔍 Testing Wikipedia Commons image URLs...")
    working_urls = []

    for name, url in test_urls:
        if test_url(url, name):
            working_urls.append((name, url))

    print(f"\n✅ Found {len(working_urls)} working URLs:")
    for name, url in working_urls:
        print(f"  • {name}: {url}")

if __name__ == '__main__':
    main()