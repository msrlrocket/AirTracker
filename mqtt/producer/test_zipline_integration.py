#!/usr/bin/env python3
"""
Test Zipline integration for AirTracker image processing
"""
import sys
from image_processor import ImageProcessor
from image_manager import get_processed_url, list_processed_images

def test_zipline_integration():
    print("🧪 Testing Zipline Image Processing Integration")
    print("=" * 50)

    # Initialize processor (in-memory mode)
    processor = ImageProcessor(use_memory_only=True)

    # Process an aircraft image
    test_url = "https://cdn.jetphotos.com/full/5/367779_1758341530.jpg"
    print(f"\n1️⃣ Processing aircraft image: {test_url}")

    zipline_url = processor.process_image(test_url)

    if zipline_url:
        print(f"✅ Processing successful!")
        print(f"📤 Zipline URL: {zipline_url}")

        # Test in-memory retrieval
        print(f"\n2️⃣ Testing in-memory retrieval...")
        retrieved_url = get_processed_url(test_url)

        if retrieved_url:
            print(f"✅ Retrieved from memory: {retrieved_url}")
            print(f"🔍 URLs match: {zipline_url == retrieved_url}")
        else:
            print("❌ Failed to retrieve from memory")

        # List all processed images
        print(f"\n3️⃣ Listing all processed images in memory...")
        all_images = list_processed_images()
        print(f"📋 Total images in memory: {len(all_images)}")

        for original_url, data in all_images.items():
            print(f"  • Original: {original_url}")
            print(f"    Zipline: {data['zipline_url']}")
            print(f"    Date: {data['processed_date']}")
            print(f"    Dimensions: {data['dimensions']}")
            print(f"    Format: {data['format']}")
            print()

        print("🎉 Zipline integration test completed successfully!")
        print(f"🔗 Aircraft image available at: {zipline_url}")
        return True
    else:
        print("❌ Processing failed")
        return False

if __name__ == '__main__':
    success = test_zipline_integration()
    sys.exit(0 if success else 1)