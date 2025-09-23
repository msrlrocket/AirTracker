#!/usr/bin/env python3
"""
Detailed test showing input and output data structures
"""
import json
from image_processor import ImageProcessor

def detailed_test():
    print("📊 AIRCRAFT IMAGE PROCESSING - DETAILED INPUT/OUTPUT")
    print("=" * 60)

    # Input data
    input_url = "https://cdn.jetphotos.com/full/5/367779_1758341530.jpg"
    print(f"📥 INPUT:")
    print(f"   Original URL: {input_url}")
    print(f"   Expected format: JPEG image from JetPhotos")
    print(f"   Target conversion: 96x72 24-bit BMP")
    print(f"   Target storage: Zipline aircraft folder")
    print()

    # Process the image
    processor = ImageProcessor(use_memory_only=True)
    result_url = processor.process_image(input_url)

    if result_url:
        print(f"📤 OUTPUT:")
        print(f"   Zipline URL: {result_url}")

        # Show the stored data structure
        stored_data = processor.processed_images.get(input_url)
        if stored_data:
            print(f"   Stored data structure:")
            print(json.dumps(stored_data, indent=4))

        print()
        print(f"🔄 PROCESSING PIPELINE SUMMARY:")
        print(f"   1. Downloaded: JPEG from JetPhotos")
        print(f"   2. Converted: To 96x72 24-bit BMP")
        print(f"   3. Uploaded: To Zipline aircraft folder")
        print(f"   4. Stored: URL and metadata in memory")
        print(f"   5. Cleaned: Temporary files removed")

        return True
    else:
        print("❌ Processing failed")
        return False

if __name__ == '__main__':
    detailed_test()