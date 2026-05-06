#!/usr/bin/env python3
import requests, re, json

with open('/Users/dumix/.openclaw/workspace/credentials.txt') as f:
    username, password = f.read().strip().split(':')

cas_url = 'https://cas.sustech.edu.cn/cas/login?service=https://bb.sustech.edu.cn/webapps/bb-sso-BBLEARN/index.jsp'
s = requests.Session()
s.headers['User-Agent'] = 'Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36'

r = s.get(cas_url, timeout=10)
execution = re.search(r'name="execution" value="([^"]+)"', r.text)
if not execution:
    print("FAIL: no execution token")
    exit(1)
execution = execution.group(1)
print(f"Got execution: {execution[:30]}...")

r = s.post(cas_url, data={
    'username': username, 'password': password,
    'execution': execution, '_eventId': 'submit'
}, allow_redirects=False, timeout=10)

print(f"POST status: {r.status_code}")
if 'Location' not in r.headers:
    print("FAIL: no redirect")
    print(r.text[:500])
    exit(1)

redirect = r.headers['Location']
print(f"Redirect: {redirect[:100]}")

r = s.get(redirect, allow_redirects=False, timeout=10)
print(f"After 1st redirect: {r.status_code}")
if r.status_code == 302 and 'Location' in r.headers:
    redirect2 = r.headers['Location']
    print(f"Redirect 2: {redirect2[:100]}")
    r = s.get(redirect2, allow_redirects=True, timeout=10)
    print(f"After 2nd redirect: {r.status_code}, final URL: {r.url}")

# Deduplicate cookies - keep last occurrence
seen = {}
for k, v in s.cookies.items():
    seen[k] = v

print(f"Final cookies: {list(seen.keys())}")
with open('/Users/dumix/.openclaw/workspace/bb_session.json', 'w') as f:
    json.dump(seen, f, indent=2)
print("Saved.")
