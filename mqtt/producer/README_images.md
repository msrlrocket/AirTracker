# AirTracker Image Processing

This module provides image processing capabilities for the AirTracker system, converting aircraft images to the optimal format for ESP32 display.

## Overview

The image processing pipeline:
1. **Download** images from URLs
2. **Convert** to 24-bit BMP at 96x72 resolution
3. **Upload** to Zipline for self-hosted storage
4. **Store** processed URLs for other scripts to use

## Files

- `image_processor.py` - Main processing script
- `image_manager.py` - Manages processed images and provides URLs
- `image_requirements.txt` - Python dependencies
- `cloudinary_config.example` - Configuration template
- `test_image_urls.txt` - Sample URLs for testing

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r image_requirements.txt
   ```

2. **Configure Zipline:**
   ```bash
   # Add Zipline credentials to .env file:
   ZIPLINE_URL=https://zip.spacegeese.com
   ZIPLINE_TOKEN=your_zipline_token_here
   ZIPLINE_AIRCRAFT_FOLDER_ID=your_folder_id_here
   ```

3. **Zipline** provides self-hosted file storage and CDN capabilities

## Usage

### Process a single image:
```bash
python3 image_processor.py --url "https://example.com/aircraft.jpg"
```

### Process multiple images:
```bash
python3 image_processor.py --batch-file test_image_urls.txt
```

### List processed images:
```bash
python3 image_processor.py --list-processed
```

### Get Zipline URL for processed image:
```bash
python3 image_manager.py --get-url "https://original-image.com/aircraft.jpg"
```

### Export all Zipline URLs:
```bash
python3 image_manager.py --export-urls aircraft_urls.txt
```

## Output Format

- **Resolution:** 96x72 pixels (optimized for ESP32 display)
- **Format:** 24-bit BMP (compatible with ESP32 decoder)
- **Hosting:** Zipline self-hosted for fast, reliable access
- **Storage:** JSON file tracks original → processed URL mapping

## Integration

Other scripts can use the processed images:

```python
from image_manager import ImageManager

manager = ImageManager()
zipline_url = manager.get_zipline_url("https://original-image.com/aircraft.jpg")
# Use zipline_url in your ESP32 or other applications
```

## File Structure

```
data/
├── processed_images.json     # URL mapping storage
└── temp_images/             # Temporary processing files (auto-cleaned)
```

## Features

- ✅ **Smart caching** - Avoids reprocessing same URLs
- ✅ **High-quality scaling** - Uses Lanczos resampling
- ✅ **Aspect ratio preservation** - Centers image with black padding
- ✅ **Metadata tracking** - Stores processing date, dimensions, format
- ✅ **Error handling** - Graceful failure with detailed logging
- ✅ **Batch processing** - Handle multiple images efficiently
- ✅ **Export capabilities** - Generate URL lists for other tools