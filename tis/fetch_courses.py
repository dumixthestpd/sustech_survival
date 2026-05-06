#!/usr/bin/env python3
"""
Extract course info from TIS course selection page and save to Downloads.
Usage: python fetch_courses.py
"""

import os
import csv
import subprocess
import re
from bs4 import BeautifulSoup

TIS_COURSES_CSV = os.path.expanduser("~/.openclaw/workspace/sustech/26spring/courses.csv")

def get_page_text(selector):
    """Get page HTML using AppleScript and JavaScript"""
    result = subprocess.run(
        ['osascript', '-e', f'tell application "Google Chrome" to tell active tab of front window to execute javascript "document.querySelector(\'{selector}\').innerHTML"'],
        capture_output=True, text=True
    )
    return result.stdout

def check_login():
    """Check if logged in to TIS"""
    result = subprocess.run(
        ['osascript', '-e', 'tell application "Google Chrome" to get URL of active tab of front window'],
        capture_output=True, text=True
    )
    url = result.stdout.strip()
    return 'tis.sustech.edu.cn' in url and 'session/invalid' not in url and 'cas.' not in url

def parse_courses(html_content):
    """Parse course info from HTML"""
    soup = BeautifulSoup(html_content, 'lxml')
    
    courses = []
    
    # Find all table rows
    rows = soup.select('tr.ivu-table-row')
    
    for row in rows:
        try:
            # Extract course name (Chinese)
            name_elem = row.select_one('.ivu-table-cell a')
            course_name = name_elem.get_text(strip=True) if name_elem else ''
            
            # Extract course code
            code_elem = row.select_one('td[class*="l0YlU1"] span')
            course_code = code_elem.get_text(strip=True) if code_elem else ''
            
            # Extract class section
            section_elem = row.select_one('td[class*="XIBzry"] span')
            section = section_elem.get_text(strip=True) if section_elem else ''
            
            # Extract course nature (required/elective)
            nature_elem = row.select_one('td[class*="4BDzAq"] span')
            nature = nature_elem.get_text(strip=True) if nature_elem else ''
            
            # Extract course category
            category_elem = row.select_one('td[class*="lS7CCo"] span')
            category = category_elem.get_text(strip=True) if category_elem else ''
            
            # Extract credits
            credits_elem = row.select_one('td[class*="4Jl7qj"] span')
            credits = credits_elem.get_text(strip=True) if credits_elem else ''
            
            # Extract schedule info
            schedule_elems = row.select('.ivu-table-cell .ivu-tag-text p')
            schedule = '; '.join([s.get_text(strip=True) for s in schedule_elems])
            
            # Extract teacher
            teacher_elems = row.select('.ivu-table-cell a[href="javascript:void(0);"]')
            teachers = ', '.join([t.get_text(strip=True) for t in teacher_elems])
            
            # Extract department
            dept_elem = row.select_one('td[class*="OUWoov"] span')
            department = dept_elem.get_text(strip=True) if dept_elem else ''
            
            if course_name or course_code:
                courses.append({
                    'Course Code': course_code,
                    'Course Name': course_name,
                    'Section': section,
                    'Nature': nature,
                    'Category': category,
                    'Credits': credits,
                    'Teacher': teachers,
                    'Schedule': schedule,
                    'Department': department
                })
        except Exception as e:
            print(f"Error parsing row: {e}")
            continue
    
    return courses

def save_to_csv(courses, output_path):
    """Save courses to CSV"""
    if not courses:
        print("No courses found!")
        return False
    
    # Ensure directory exists
    os.makedirs(os.path.dirname(output_path), exist_ok=True)
    
    fieldnames = ['Course Code', 'Course Name', 'Section', 'Nature', 'Category', 'Credits', 'Teacher', 'Schedule', 'Department']
    
    with open(output_path, 'w', newline='', encoding='utf-8-sig') as f:
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(courses)
    
    print(f"Saved {len(courses)} courses to {output_path}")
    return True

def main():
    print("=== TIS Course Fetcher ===")
    
    # Step 1: Check login
    print("\n[1/3] Checking login status...")
    if not check_login():
        print("NOT LOGGED IN! Please login via CAS first.")
        print("Run: ./login-tis.sh")
        return
    
    print("✓ Logged in")
    
    # Step 2: Visit course selection page
    print("\n[2/3] Fetching course selection page...")
    # Get the table body content using JavaScript
    html = get_page_text(".ivu-table-body")
    
    if not html or 'session/invalid' in html:
        print("Session expired! Please login again.")
        return
    
    print("✓ Page fetched")
    
    # Step 3: Parse and save
    print("\n[3/3] Parsing courses...")
    courses = parse_courses(html)
    
    if save_to_csv(courses, TIS_COURSES_CSV):
        print(f"\n✅ Done! Courses saved to {TIS_COURSES_CSV}")
    else:
        print("\n❌ Failed to save courses")

if __name__ == '__main__':
    main()
