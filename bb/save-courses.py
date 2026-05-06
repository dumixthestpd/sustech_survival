#!/usr/bin/env python3
import json

data = json.load(open('/tmp/bb_structure.json'))

output = {
    'scraped_at': data['scraped_at'],
    'courses': []
}

for c in data['courses']:
    items = [i for i in data['items'] if i['course_id'] == c['id']]
    sections = {}
    for item in items:
        sec = item['section'] or 'Other'
        if sec not in sections:
            sections[sec] = []
        sections[sec].append({
            'title': item['title'],
            'cid': item['cid'],
            'href': item['href'],
            'content_preview': item['content_preview'],
        })
    output['courses'].append({
        'id': c['id'],
        'name': c['name'],
        'sections': sections,
    })

with open('/Users/dumix/.openclaw/workspace/skills/sustech-survival/bb/bb-courses.json', 'w', encoding='utf-8') as f:
    json.dump(output, f, indent=2, ensure_ascii=False)

print('Saved to bb-courses.json')
print(f'Courses: {len(output["courses"])}')
for c in output['courses']:
    total = sum(len(v) for v in c['sections'].values())
    print(f'  {c["name"]}: {len(c["sections"])} sections, {total} items')
    for sec, items in c['sections'].items():
        print(f'    [{sec}] ({len(items)})')
