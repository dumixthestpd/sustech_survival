#!/bin/bash
# BB Tab Cleaner - Clean up excess Chrome tabs, keep BB tabs
# - Close CAS login pages if logged in
# - Remove duplicate tabs (keep unique URLs)
# Usage: ./cleanup-tabs.sh

echo "Cleaning up BB tabs..."

LOGGED_IN=$(osascript -e '
set isLoggedIn to false
tell application "Google Chrome"
    set windowList to windows
    repeat with w in windowList
        set tabList to tabs of w
        repeat with t in tabList
            try
                set tURL to URL of t
                if tURL contains "portal/execute/tabs" then
                    set isLoggedIn to true
                end if
            end try
        end repeat
    end repeat
end tell
return isLoggedIn
')

echo "Logged in: $LOGGED_IN"

# Close duplicates and CAS login if logged in
osascript -e '
set tabsToClose to {}
set seenURLs to {}
set isLoggedIn to '$LOGGED_IN'

tell application "Google Chrome"
    set windowList to windows
    repeat with w in windowList
        set tabList to tabs of w
        repeat with i from (count of tabList) to 1 by -1
            set t to item i of tabList
            try
                set tURL to URL of t
                
                -- Close non-BB tabs
                if tURL does not contain "bb.sustech.edu.cn" then
                    set end of tabsToClose to t
                end if
            end try
        end repeat
    end repeat
    
    -- Second pass: close duplicates and CAS if logged in
    repeat with w in windowList
        set tabList to tabs of w
        repeat with i from (count of tabList) to 1 by -1
            set t to item i of tabList
            try
                set tURL to URL of t
                
                if tURL is in seenURLs then
                    set end of tabsToClose to t
                else
                    set end of seenURLs to tURL
                    
                    -- Close CAS login if logged in
                    if isLoggedIn and tURL contains "cas.sustech.edu.cn" then
                        set end of tabsToClose to t
                    end if
                end if
            end try
        end repeat
    end repeat
    
    -- Close the tabs
    repeat with t in tabsToClose
        try
            close t
        end try
    end repeat
end tell
'

echo "✓ BB tab cleanup complete"

# Report remaining BB tabs
echo ""
echo "Remaining BB tabs:"
osascript -e '
set output to ""
tell application "Google Chrome"
    set windowList to windows
    repeat with w in windowList
        set tabList to tabs of w
        repeat with t in tabList
            try
                set tURL to URL of t
                if tURL contains "bb.sustech.edu.cn" then
                    set output to output & tURL & linefeed
                end if
            end try
        end repeat
    end repeat
end tell
return output
' 2>/dev/null || echo "No BB tabs found"
