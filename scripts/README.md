# Zipline Airline Logo Uploader

One-time script to upload all airline BMP files to your Zipline instance.

## Setup

1. **Install dependencies:**
   ```bash
   pip install -r requirements.txt
   ```

2. **The script includes your Zipline token by default** (from the example you provided)

3. **Test with dry run:**
   ```bash
   python3 upload_airline_logos_zipline.py --folder "/Users/mattlindsay/Downloads/esp32-flightradar24-ttgo-main 2/images/airline_logos" --dry-run
   ```

4. **Upload all logos:**
   ```bash
   python3 upload_airline_logos_zipline.py --folder "/Users/mattlindsay/Downloads/esp32-flightradar24-ttgo-main 2/images/airline_logos"
   ```

## Configuration

The script defaults to:
- **Zipline URL**: `https://zip.spacegeese.com`
- **Auth Token**: Your token from the example script
- **Upload delay**: 0.5 seconds between files

You can override these with command line arguments or environment variables.

## Features

- ✅ **Batch upload** all BMP files in a folder
- ✅ **Rate limiting** to avoid overwhelming the server
- ✅ **Progress tracking** with detailed output
- ✅ **Error handling** and retry logic
- ✅ **Dry run mode** to preview what will be uploaded
- ✅ **Environment variable** support for credentials

Perfect for uploading your 2,664 airline logos! ✈️