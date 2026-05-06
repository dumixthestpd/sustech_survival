# TIS (Teaching Information System)

教学信息管理系统 — course schedule, grades, academic info.

## IMPORTANT: Login Status Check

⚠️ **ALWAYS check login status BEFORE any TIS action!**

### Check Login Status

Use `/user/me` endpoint:

```bash
open -a "Google Chrome" "https://tis.sustech.edu.cn/user/me"
sleep 3
URL=$(osascript -e 'tell application "Google Chrome" to get URL of active tab of window 1')

# - Contains "cas.sustech.edu.cn" → NOT logged in
# - Still "tis.sustech.edu.cn/user/me" → LOGGED IN
```

**Never use screenshots** — use URL check only.

### If NOT Logged In

1. Login via CAS
2. Verify login successful (repeat check)
3. Then proceed

---

## Login to TIS

### Method 1: Direct CAS URL (Recommended)

```bash
osascript -e 'tell application "Google Chrome" to open location "https://cas.sustech.edu.cn/cas/login?service=https://tis.sustech.edu.cn/CAS"'
```

Wait for CAS page → click username field to trigger autofill → login.

### Method 2: Via TIS Main Page

```bash
osascript -e 'tell application "Google Chrome" to open location "https://tis.sustech.edu.cn"'
```

Click CAS login icon.

---

## Extract Schedule

### Step 1: Get HTML

```bash
osascript -e 'tell application "Google Chrome" to execute active tab of window 1 javascript "document.body.innerHTML"' > schedule.html
```

### Step 2: Parse to CSV

```bash
cd ~/.openclaw/workspace/skills/sustech-survival
python3 parse_kebiao.py /path/to/schedule.html -o schedule.csv
```

### Output Format

| Weekday | Period | Time | Course |
|---------|--------|------|--------|
| Monday | 第1-2节 | 08:00-09:50 | 体育IV [梁锡元] [定向越野3班] [1-15周] |

---

## Tested

- ✅ Login via CAS
- ✅ Schedule extraction (2026春季)
