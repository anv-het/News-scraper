"""
LODR Data Fetcher
Fetches data from scanx API for multiple ISINs from a CSV file
and saves each company's data as a separate JSON file or MongoDB.

Features:
- Random delay (2-6 sec) between each ISIN fetch
- 5-15 min break after every 100 fetches
- Optional MongoDB storage
- Cron job scheduling with configurable time range and days gap
"""

import requests
import json
import csv
import os
import time
import random
import threading
from pathlib import Path
from datetime import datetime, timedelta
from dotenv import load_dotenv

# Load environment variables
load_dotenv()


def get_config():
    """Load configuration from environment variables."""
    return {
        # Delay settings
        'fetch_min_delay': int(os.getenv('FETCH_MIN_DELAY', 2)),
        'fetch_max_delay': int(os.getenv('FETCH_MAX_DELAY', 6)),
        'batch_size': int(os.getenv('BATCH_SIZE', 100)),
        'break_min_minutes': int(os.getenv('BREAK_MIN_MINUTES', 5)),
        'break_max_minutes': int(os.getenv('BREAK_MAX_MINUTES', 15)),
        
        # MongoDB settings
        'mongodb_enabled': os.getenv('MONGODB_ENABLED', 'false').lower() == 'true',
        'mongodb_url': os.getenv('MONGODB_URL', 'mongodb://localhost:27017'),
        'mongodb_database': os.getenv('MONGODB_DATABASE', 'scanx_db'),
        'mongodb_collection': os.getenv('MONGODB_COLLECTION', 'lodr_data'),
        
        # Cron settings
        'cron_enabled': os.getenv('CRON_ENABLED', 'false').lower() == 'true',
        'cron_start_hour': int(os.getenv('CRON_START_HOUR', 9)),
        'cron_end_hour': int(os.getenv('CRON_END_HOUR', 18)),
        'cron_days_gap': int(os.getenv('CRON_DAYS_GAP', 1)),
    }


def get_mongo_client(config):
    """Create and return MongoDB client and collection."""
    try:
        from pymongo import MongoClient
        client = MongoClient(config['mongodb_url'])
        db = client[config['mongodb_database']]
        collection = db[config['mongodb_collection']]
        # Test connection
        client.admin.command('ping')
        print(f"[MongoDB] Connected to {config['mongodb_database']}.{config['mongodb_collection']}")
        return client, collection
    except Exception as e:
        print(f"[MongoDB] Connection failed: {e}")
        return None, None


def save_to_mongodb(collection, data, isin, company_name):
    """Save data to MongoDB collection."""
    try:
        document = {
            'isin': isin,
            'company_name': company_name,
            'data': data,
            'fetched_at': datetime.utcnow(),
            'updated_at': datetime.utcnow()
        }
        
        # Upsert - update if exists, insert if not
        result = collection.update_one(
            {'isin': isin},
            {'$set': document},
            upsert=True
        )
        
        if result.upserted_id:
            return 'inserted'
        elif result.modified_count > 0:
            return 'updated'
        else:
            return 'unchanged'
    except Exception as e:
        print(f"  [MongoDB] Error saving data: {e}")
        return 'error'


def load_isins_from_csv(csv_path: str) -> list:
    """
    Load company names and ISINs from a CSV file.
    Expects CSV with columns 'NAME OF COMPANY' and 'ISIN NUMBER' (or 'isin').
    Returns list of tuples: (company_name, isin)
    """
    results = []
    with open(csv_path, 'r', encoding='utf-8') as file:
        reader = csv.DictReader(file)
        
        # Find column names (case-insensitive, handle spaces)
        fieldnames = {col.strip().lower(): col for col in reader.fieldnames}
        
        # Try to find ISIN column
        isin_column = None
        for key in ['isin number', 'isin']:
            if key in fieldnames:
                isin_column = fieldnames[key]
                break
        
        # Try to find company name column
        name_column = None
        for key in ['name of company', 'company name', 'name']:
            if key in fieldnames:
                name_column = fieldnames[key]
                break
        
        if isin_column is None:
            # Fallback: use first two columns (name, isin)
            file.seek(0)
            reader = csv.reader(file)
            next(reader)  # Skip header
            for row in reader:
                if len(row) >= 2 and row[1].strip():
                    results.append((row[0].strip(), row[1].strip()))
                elif row and row[0].strip():
                    results.append((row[0].strip(), row[0].strip()))  # Use ISIN as name too
        else:
            for row in reader:
                isin = row[isin_column].strip() if row.get(isin_column) else ''
                if isin:
                    name = row.get(name_column, '').strip() if name_column else isin
                    results.append((name if name else isin, isin))
    
    return results


def fetch_lodr_data(isin: str, count: int = 501, pg_no: int = 1) -> dict:
    """
    Fetch LODR data for a given ISIN from the scanx API.
    """
    url = "https://ow-static-scanx.dhan.co/staticscanx/lodr"
    
    headers = {
        "Accept": "application/json, text/plain, */*",
        "Content-Type": "application/json",
        "Origin": "https://scanx.trade",
        "Referer": "https://scanx.trade/",
        "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/144.0.0.0"
    }
    
    payload = {
        "data": {
            "isin": isin,
            "pg_no": pg_no,
            "count": count
        }
    }
    
    try:
        response = requests.post(url, headers=headers, json=payload, timeout=30)
        response.raise_for_status()
        return response.json()
    except requests.exceptions.RequestException as e:
        print(f"  Error fetching data for ISIN {isin}: {e}")
        return None


def sanitize_filename(name: str) -> str:
    """Remove or replace invalid filename characters."""
    invalid_chars = '<>:"/\\|?*'
    for char in invalid_chars:
        name = name.replace(char, '_')
    return name.strip()


def save_to_json(data: dict, output_path: str):
    """Save data to a JSON file."""
    with open(output_path, 'w', encoding='utf-8') as file:
        json.dump(data, file, indent=2, ensure_ascii=False)


def run_fetch(csv_path: str, output_dir: str = "output", count: int = 501, save_to_db: bool = False):
    """
    Main function to fetch LODR data for all ISINs in a CSV file.
    
    Args:
        csv_path: Path to CSV file containing ISINs
        output_dir: Directory to save JSON files
        count: Number of records to fetch per request
        save_to_db: Whether to save data to MongoDB
    """
    config = get_config()
    
    # Create output directory
    output_path = Path(output_dir)
    output_path.mkdir(parents=True, exist_ok=True)
    
    # MongoDB setup
    mongo_client = None
    mongo_collection = None
    if save_to_db or config['mongodb_enabled']:
        mongo_client, mongo_collection = get_mongo_client(config)
        if mongo_collection is None:
            print("[Warning] MongoDB not available, will save to JSON files only")
    
    # Load ISINs
    print(f"Loading data from: {csv_path}")
    company_data = load_isins_from_csv(csv_path)
    print(f"Found {len(company_data)} entries to process\n")
    
    if not company_data:
        print("No ISINs found in the CSV file.")
        return
    
    # Delay settings
    delay_range = (config['fetch_min_delay'], config['fetch_max_delay'])
    batch_size = config['batch_size']
    break_range = (config['break_min_minutes'], config['break_max_minutes'])
    
    print(f"[Config] Delay between fetches: {delay_range[0]}-{delay_range[1]} seconds")
    print(f"[Config] Break every {batch_size} fetches: {break_range[0]}-{break_range[1]} minutes\n")
    
    # Process each ISIN
    success_count = 0
    failed_count = 0
    db_inserted = 0
    db_updated = 0
    
    for i, (company_name, isin) in enumerate(company_data, 1):
        print(f"[{i}/{len(company_data)}] Fetching data for: {company_name} - {isin}")
        
        data = fetch_lodr_data(isin, count=count)
        
        if data:
            # Skip if no records fetched (code -1 or empty data)
            if isinstance(data, dict) and (data.get('code') == -1 or data.get('total_count', 1) == 0):
                print(f"  [SKIP] No records found for this ISIN")
                failed_count += 1
                continue
            
            # Save to JSON file (filename is just ISIN)
            filename = f"{isin}.json"
            file_path = output_path / filename
            save_to_json(data, str(file_path))
            print(f"  [OK] Saved to: {filename}")
            
            # Save to MongoDB if enabled
            if mongo_collection is not None:
                result = save_to_mongodb(mongo_collection, data, isin, company_name)
                if result == 'inserted':
                    db_inserted += 1
                    print(f"  [MongoDB] Inserted new record")
                elif result == 'updated':
                    db_updated += 1
                    print(f"  [MongoDB] Updated existing record")
            
            success_count += 1
        else:
            print(f"  [FAILED] Failed to fetch data")
            failed_count += 1
        
        # Check if we need a break after batch
        if i < len(company_data) and i % batch_size == 0:
            break_minutes = random.uniform(*break_range)
            print(f"\n{'='*50}")
            print(f"[BREAK] Completed {i} fetches. Taking a {break_minutes:.1f} minute break...")
            print(f"[BREAK] Will resume at: {(datetime.now() + timedelta(minutes=break_minutes)).strftime('%H:%M:%S')}")
            print(f"{'='*50}\n")
            time.sleep(break_minutes * 60)
            print("[BREAK] Resuming fetches...\n")
        
        # Add random delay between requests (except for the last one)
        elif i < len(company_data):
            delay = random.uniform(*delay_range)
            print(f"  Waiting {delay:.1f}s before next request...")
            time.sleep(delay)
    
    # Close MongoDB connection
    if mongo_client:
        mongo_client.close()
    
    # Summary
    print(f"\n{'='*50}")
    print(f"Processing complete!")
    print(f"  Total entries: {len(company_data)}")
    print(f"  Successful: {success_count}")
    print(f"  Failed: {failed_count}")
    print(f"  Output directory: {output_path.absolute()}")
    if mongo_collection is not None:
        print(f"  MongoDB - Inserted: {db_inserted}, Updated: {db_updated}")


def calculate_next_run_time(config):
    """Calculate the next scheduled run time based on config."""
    now = datetime.now()
    start_hour = config['cron_start_hour']
    end_hour = config['cron_end_hour']
    days_gap = config['cron_days_gap']
    
    # Calculate random hour and minute within the range
    random_hour = random.randint(start_hour, end_hour - 1 if end_hour > start_hour else end_hour)
    random_minute = random.randint(0, 59)
    random_second = random.randint(0, 59)
    
    # Start from today + days_gap
    next_run = now.replace(hour=random_hour, minute=random_minute, second=random_second, microsecond=0)
    next_run += timedelta(days=days_gap)
    
    return next_run


def run_cron_mode(csv_path: str, output_dir: str = "output", count: int = 501):
    """
    Run in cron mode - schedule runs at random times within configured range.
    """
    config = get_config()
    
    print("="*60)
    print("CRON MODE ACTIVATED")
    print(f"  Time range: {config['cron_start_hour']:02d}:00 - {config['cron_end_hour']:02d}:00")
    print(f"  Days gap: {config['cron_days_gap']} day(s)")
    print("="*60)
    
    while True:
        next_run = calculate_next_run_time(config)
        wait_seconds = (next_run - datetime.now()).total_seconds()
        
        print(f"\n[CRON] Next run scheduled for: {next_run.strftime('%Y-%m-%d %H:%M:%S')}")
        print(f"[CRON] Waiting {wait_seconds/3600:.1f} hours...")
        
        # Wait until next run time
        if wait_seconds > 0:
            time.sleep(wait_seconds)
        
        # Run the fetch
        print(f"\n[CRON] Starting scheduled run at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
        try:
            run_fetch(csv_path, output_dir, count, save_to_db=True)
        except Exception as e:
            print(f"[CRON] Error during fetch: {e}")
        
        print(f"[CRON] Run completed at {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    import argparse
    
    parser = argparse.ArgumentParser(description="Fetch LODR data for ISINs from a CSV file")
    parser.add_argument("csv_file", help="Path to CSV file containing ISINs")
    parser.add_argument("-o", "--output", default="output", help="Output directory for JSON files (default: output)")
    parser.add_argument("-c", "--count", type=int, default=501, help="Number of records to fetch per ISIN (default: 501)")
    parser.add_argument("--save-to-db", action="store_true", help="Save data to MongoDB")
    parser.add_argument("--cron", action="store_true", help="Run in cron mode (scheduled execution)")
    
    args = parser.parse_args()
    
    if args.cron:
        run_cron_mode(
            csv_path=args.csv_file,
            output_dir=args.output,
            count=args.count
        )
    else:
        run_fetch(
            csv_path=args.csv_file,
            output_dir=args.output,
            count=args.count,
            save_to_db=args.save_to_db
        )
