#!/bin/bash
# BB Login via Headless Playwright
# Usage: login-bb.sh <username> <password>
# If no args, reads from ~/.openclaw/workspace/credentials.txt (username:password format)

CRED_FILE="$HOME/.openclaw/workspace/credentials.txt"
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"

if [ $# -ge 2 ]; then
    USERNAME="$1"
    PASSWORD="$2"
elif [ -f "$CRED_FILE" ]; then
    USERNAME=$(head -1 "$CRED_FILE" | cut -d: -f1)
    PASSWORD=$(head -1 "$CRED_FILE" | cut -d: -f2)
else
    echo "Usage: login-bb.sh <username> <password>"
    echo "Or create $CRED_FILE with format: username:password"
    exit 1
fi

echo "=== BB Login: $USERNAME ==="
python3 "$SCRIPT_DIR/headless-login.py" "$USERNAME" "$PASSWORD"
