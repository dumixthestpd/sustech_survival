#!/usr/bin/env python3
"""
Parse SUSTech TIS schedule HTML and export to CSV.

Usage:
    python parse_kebiao.py input.html -o schedule.csv
"""

import argparse
import csv
from bs4 import BeautifulSoup


def parse_kebiao(html_content):
    """
    Parse schedule HTML and return a list of course records.
    Each record contains: weekday, period, time range, course info.
    """
    soup = BeautifulSoup(html_content, 'lxml')

    # 1. Get weekday headers from table
    header_table = soup.select_one('.ivu-table-header table')
    days = []
    if header_table:
        header_row = header_table.select_one('thead tr')
        if header_row:
            for th in header_row.find_all('th'):
                if 'ivu-table-hidden' in th.get('class', []):
                    continue
                span = th.select_one('.ivu-table-cell span')
                if span:
                    day = span.get_text(strip=True)
                    if day:
                        days.append(day)
    
    # Fallback to default weekday order
    if len(days) < 7:
        days = ['Monday', 'Tuesday', 'Wednesday', 'Thursday', 'Friday', 'Saturday', 'Sunday']
    else:
        # Map Chinese to English
        day_map = {
            '星期一': 'Monday',
            '星期二': 'Tuesday',
            '星期三': 'Wednesday',
            '星期四': 'Thursday',
            '星期五': 'Friday',
            '星期六': 'Saturday',
            '星期日': 'Sunday'
        }
        days = [day_map.get(d, d) for d in days]

    # 2. Locate schedule body
    tbody = soup.select_one('.ivu-table-tbody')
    if not tbody:
        raise ValueError("Schedule body .ivu-table-tbody not found")

    records = []

    # 3. Iterate through each row (time slot)
    for tr in tbody.find_all('tr'):
        tds = tr.find_all('td')
        if not tds:
            continue

        # First td is time column
        time_td = tds[0]
        
        # Extract period and time
        section = ''
        time_range = ''
        subtable = time_td.find('div', class_='subtable-boxtop')
        if subtable:
            ps = subtable.find_all('p')
            if len(ps) >= 5:
                start_section = ps[0].get_text(strip=True)
                start_time = ps[1].get_text(strip=True)
                end_section = ps[3].get_text(strip=True)
                end_time = ps[4].get_text(strip=True)
                section = f"{start_section}-{end_section}"
                time_range = f"{start_time}-{end_time}"

        # Process remaining tds (one per weekday)
        for idx, td in enumerate(tds[1:]):
            if idx >= len(days):
                break
            day = days[idx]

            cards = td.find_all('div', class_='ivu-card')
            if not cards:
                continue

            for card in cards:
                span = card.select_one('.codedd-wrap span')
                if span:
                    card_text = span.get_text(separator='\n', strip=True)
                else:
                    card_text = card.get_text(separator='\n', strip=True)

                records.append({
                    'Weekday': day,
                    'Period': section,
                    'Time': time_range,
                    'Course': card_text
                })

    return records


def write_csv(records, output_file):
    """Write records to CSV (UTF-8 with BOM for Excel compatibility)"""
    with open(output_file, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=['Weekday', 'Period', 'Time', 'Course'])
        writer.writeheader()
        writer.writerows(records)


def main():
    parser = argparse.ArgumentParser(description='Parse SUSTech TIS schedule HTML to CSV')
    parser.add_argument('input', help='Input HTML file path')
    parser.add_argument('-o', '--output', default='schedule.csv',
                        help='Output CSV file path (default: schedule.csv)')
    args = parser.parse_args()

    with open(args.input, 'r', encoding='utf-8') as f:
        html = f.read()

    records = parse_kebiao(html)
    write_csv(records, args.output)
    print(f"Extracted {len(records)} course records, saved to {args.output}")


if __name__ == '__main__':
    main()
