#!/usr/bin/env python3
"""
Fetch SUSTech academic calendar PDF - smart version.
- Checks if calendar URL changed
- Only downloads if updated
- Reads locally for parsing

Usage: 
    python3 fetch_calendar.py           # Check and update
    python3 fetch_calendar.py --force  # Force download
    python3 fetch_calendar.py --parse  # Parse local PDF and print dates
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import urllib.parse

ACADEMIC_CALENDAR_URL = "https://www.sustech.edu.cn/zh/academic-calendar.html"
CALENDAR_DIR = os.path.expanduser("~/.openclaw/workspace/sustech")
METADATA_FILE = os.path.join(CALENDAR_DIR, "calendar_metadata.json")

def ensure_dir():
    os.makedirs(CALENDAR_DIR, exist_ok=True)

def get_page_html():
    """Get page HTML using AppleScript to extract from Chrome"""
    result = subprocess.run(
        ['osascript', '-e', '''tell application "Google Chrome" to tell active tab of front window to execute javascript "document.body.innerHTML"'''],
        capture_output=True, text=True
    )
    return result.stdout

def open_calendar_page():
    """Open the academic calendar page in Chrome"""
    subprocess.run(
        ['open', '-a', 'Google Chrome', ACADEMIC_CALENDAR_URL],
        capture_output=True
    )
    import time
    time.sleep(2)

def find_calendar_links(html_content):
    """Find academic calendar PDF links from the page HTML."""
    base_url = "https://www.sustech.edu.cn"
    pdf_pattern = r'href="(/uploads/files/[^"]+\.pdf)"[^>]*>([^<]+)</a>'
    matches = re.findall(pdf_pattern, html_content)
    
    calendars = []
    for href, text in matches:
        year_match = re.search(r'（(\d{4})）', text)
        cal_year = year_match.group(1) if year_match else None
        
        if cal_year:
            full_url = base_url + href if href.startswith('/') else href
            calendars.append({
                'year': cal_year,
                'text': text.strip(),
                'url': full_url
            })
    
    return calendars

def get_url_content_hash(url):
    """Get a hash of URL to detect changes"""
    return hashlib.md5(url.encode()).hexdigest()

def load_metadata():
    """Load saved calendar metadata"""
    if os.path.exists(METADATA_FILE):
        with open(METADATA_FILE, 'r') as f:
            return json.load(f)
    return {}

def save_metadata(calendars):
    """Save calendar metadata"""
    metadata = {}
    for cal in calendars:
        metadata[cal['year']] = {
            'url': cal['url'],
            'url_hash': get_url_content_hash(cal['url']),
            'text': cal['text']
        }
    with open(METADATA_FILE, 'w') as f:
        json.dump(metadata, f, indent=2)

def check_updates(calendars):
    """Check which calendars need updating"""
    metadata = load_metadata()
    updates = []
    
    for cal in calendars:
        year = cal['year']
        url_hash = get_url_content_hash(cal['url'])
        
        if year not in metadata:
            updates.append((cal, "new"))
        elif metadata[year]['url_hash'] != url_hash:
            updates.append((cal, "updated"))
    
    return updates

def download_calendar(url, year):
    """Download a calendar PDF"""
    ensure_dir()
    filename = f"academic-calendar-{year}.pdf"
    output_path = os.path.join(CALENDAR_DIR, filename)
    
    print(f"Downloading {year} calendar to {output_path}...")
    
    result = subprocess.run(
        ['curl', '-L', '-o', output_path, url],
        capture_output=True
    )
    
    if result.returncode == 0:
        print(f"✅ Saved: {output_path}")
        return output_path
    else:
        print(f"❌ Download failed: {result.stderr.decode()}")
        return None

def parse_calendar_local(year):
    """Parse local PDF for semester dates and holidays"""
    pdf_path = os.path.join(CALENDAR_DIR, f"academic-calendar-{year}.pdf")
    
    if not os.path.exists(pdf_path):
        print(f"❌ Calendar not found: {pdf_path}")
        print("Run: python3 fetch_calendar.py --force")
        return None
    
    # Try using pdftotext if available
    result = subprocess.run(
        ['pdftotext', '-layout', pdf_path, '-'],
        capture_output=True, text=True
    )
    
    if result.returncode != 0 or not result.stdout.strip():
        # Fallback: try PDFMiner
        try:
            from pdfminer.high_level import extract_text
            text = extract_text(pdf_path)
        except ImportError:
            print("❌ Need pdftotext or pdfminer to parse PDF")
            print("Install: brew install poppler && pip install pdfminer.six")
            return None
    else:
        text = result.stdout
    
    return parse_calendar_text(text, year)

def parse_calendar_text(text, year):
    """Parse calendar text to extract dates"""
    info = {
        'year': year,
        'semesters': [],
        'holidays': [],
        'compensatory': []
    }
    
    # Find semester periods (春季/秋季学期)
    semester_patterns = [
        r'春季.*?(\d{1,2})[月\-](\d{1,2}).*?(\d{1,2})[月\-](\d{1,2})',
        r'20(\d{2})[-–](\d{2})[学年度].*?(\d{1,2})[月\-](\d{1,2})',
    ]
    
    # Find holidays
    holiday_names = ['春节', '清明', '劳动节', '端午节', '中秋节', '国庆节', '元旦']
    
    # Find compensatory work days (调休)
    comp_pattern = r'(\d{1,2})[月\-](\d{1,2})日.*?调休|调休.*?(\d{1,2})[月\-](\d{1,2})日'
    
    lines = text.split('\n')
    
    print(f"\n=== SUSTech Calendar {year} ===\n")
    
    # Print relevant lines for debugging
    for line in lines:
        if any(h in line for h in ['学期', '开学', '寒假', '暑假', '放假', '调休', '春节', '清明', '劳动', '端午', '中秋', '国庆']):
            print(line)
    
    return info

def main():
    parser = argparse.ArgumentParser(description="SUSTech Academic Calendar Fetcher")
    parser.add_argument('--year', type=int, help='Specific year to fetch (e.g., 2026)')
    parser.add_argument('--force', action='store_true', help='Force download even if not updated')
    parser.add_argument('--parse', action='store_true', help='Parse local PDF and print dates')
    parser.add_argument('--check', action='store_true', help='Check for updates only')
    args = parser.parse_args()
    
    print("=== SUSTech Academic Calendar ===\n")
    
    ensure_dir()
    
    # Try to get from current Chrome tab first
    html = get_page_html()
    
    if not html or 'academic-calendar' not in html.lower():
        print("[1/2] Opening academic calendar page...")
        open_calendar_page()
        html = get_page_html()
    
    if not html:
        print("❌ Failed to fetch page content")
        return
    
    print("[2/2] Parsing calendar links...")
    calendars = find_calendar_links(html)
    
    if not calendars:
        print("❌ No calendars found")
        return
    
    # Save metadata
    save_metadata(calendars)
    
    print(f"\nFound {len(calendars)} calendar(s):\n")
    for cal in calendars:
        print(f"  {cal['year']}: {cal['text']}")
        print(f"    URL: {cal['url']}\n")
    
    # Check for updates
    if args.parse:
        if args.year:
            parse_calendar_local(args.year)
        else:
            # Parse all available
            for cal in calendars:
                parse_calendar_local(cal['year'])
        return
    
    if args.check:
        updates = check_updates(calendars)
        if updates:
            print("\n�更新的校历 / Updated calendars:")
            for cal, reason in updates:
                print(f"  {cal['year']}: {reason}")
        else:
            print("\n✅ No updates available")
        return
    
    # Download if needed
    for cal in calendars:
        if args.year and str(args.year) != cal['year']:
            continue
        
        updates = check_updates([cal])
        
        if args.force or updates:
            download_calendar(cal['url'], cal['year'])
        else:
            print(f"  {cal['year']}: Already up to date, skipping download")

if __name__ == '__main__':
    main()
