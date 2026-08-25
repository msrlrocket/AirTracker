# AirTracker Scripts Directory

This directory contains utility scripts for managing AirTracker datasets and resources.

## Active Scripts

### Core Dataset Management
- **`military_aircraft_scraper.py`** - Scrapes military aircraft data and images from military.com and updates datasets
- **`update_airlines_with_zipline_urls.py`** - Updates airlines dataset with PNG logo URLs from successful Zipline uploads
- **`upload_airline_pngs_corrected.py`** - Uploads airline PNG logos to Zipline (corrected version that works)

### InfluxDB Management
- **`../mqtt/unified/influx_db_test.py`** - InfluxDB demo, query tool, and database management utility

## Data Files
- **`airline_png_upload_results_corrected.json`** - Results from successful airline PNG uploads
- **`fast_airline_logo_results.json`** - Fast airline logo check results
- **`test_*.json`** - Sample aircraft data for testing

## Archive Directory
The `archive/` directory contains scripts that were used for one-time dataset creation and are no longer needed for regular operations:

- Image scraping utilities (completed)
- Dataset enrichment scripts (completed)
- Military dataset creation scripts (completed)
- Airline logo checking and uploading (completed)
- Zipline URL extraction tools (completed)

## Usage

### Update Military Aircraft Dataset
```bash
cd scripts
python3 military_aircraft_scraper.py --debug --output ../mqtt/unified/datasets/military_aircraft_complete.json
```

### Query InfluxDB Data
```bash
cd mqtt/unified
# Show demo and available aircraft
python3 influx_db_test.py

# Show nearest aircraft data
python3 influx_db_test.py -nearest

# Search specific aircraft
python3 influx_db_test.py N431AS

# Wipe database (requires confirmation)
python3 influx_db_test.py --wipe
```

### InfluxDB Test Features
The `influx_db_test.py` script provides:
- **Historical aircraft tracking** - Shows aircraft timeline and flight patterns
- **Rich metadata display** - Images, airlines, routes, military detection
- **Analytics capabilities** - Min/max stats, hourly averages
- **Query examples** - Shows how to filter by airline, aircraft type, altitude, etc.
- **Database management** - Wipe/reset capabilities
- **Multi-bucket support** - View nearest, commercial, and all planes data

The script uses **pivot queries** to show single-row aircraft data instead of the default InfluxDB field-per-row format.

## Environment Requirements
Scripts require:
- Python 3.x
- Environment variables in `.env` file
- InfluxDB client library for database scripts
- Zipline credentials for upload scripts

Most scripts in the archive directory are no longer needed but are preserved for reference.