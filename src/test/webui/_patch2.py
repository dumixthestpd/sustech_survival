"""Patch remaining picked-panel + stepper strings."""
import io
p = r'D:\dumix\.openclaw\workspace\sustech_code\sustech_survival\src\sustech_survival\webui\skins\default\static\tis\tis.js'
src = io.open(p, encoding='utf-8').read()

patches = [
    # "All" label inside picked-select-all
    ("'<span>All</span>'",
     "'<span>' + t('All', '全选') + '</span>'"),
    # 0 / 0 selected
    ("'<span class=\"picked-selected-count\" id=\"picked-selected-count\">0 / 0 selected</span>'",
     "'<span class=\"picked-selected-count\" id=\"picked-selected-count\">' + t('0 / 0 selected', '已选 0 / 0') + '</span>'"),
    # Remove button
    ("'title=\"Remove all ticked picks (confirm for many)\">\\u2702 Remove</button>'",
     "'title=\"' + t('Remove all ticked picks (confirm for many)', '移除所有勾选项（数量多时需确认）') + '\">' + t('Remove', '移除') + '</button>'"),
    # ignore-tis-enrolled label
    ("'<span>Ignore TIS enrolled</span>'",
     "'<span>' + t('Ignore TIS enrolled', '忽略 TIS 已选课程') + '</span>'"),
    # Drop all enrolled button
    ("'>\\ud83d\\uddd1 Drop all enrolled courses in TIS</button>';",
     "'>' + t('Drop all enrolled courses in TIS', '退掉 TIS 中所有已选课程') + '</button>';'"),
    # Drop all enrolled button title
    ("title=\"Drop every currently-enrolled section on TIS (destructive \\u2014 will prompt for confirmation)\"",
     "title=\"' + t('Drop every currently-enrolled section on TIS (destructive \\u2014 will prompt for confirmation)', '退掉 TIS 中所有已选教学班（危险操作 — 会弹出确认）')"),
    # "Tick all visible picks" tooltip
    ("title=\"Tick all visible picks\"",
     "title=\"' + t('Tick all visible picks', '勾选所有可见项')"),
    # ignore-tis-enrolled title (label tooltip)
    ("title=\"When OFF, TIS-enrolled courses are unquestionable \\u2014 solver keeps them, can\\'t be dropped here, win every conflict\"",
     "title=\"' + t('When OFF, TIS-enrolled courses are unquestionable \\u2014 solver keeps them, can\\'t be dropped here, win every conflict', '关闭时，TIS 已选课程不可更改 — 求解器会保留它们，不能在此退课，且在冲突中胜出')"),
    # Step toggle text (Grid)
    ("'#step-toggle-text'",
     "'#step-toggle-text'"),  # placeholder
]

for old, new in patches:
    if old in src:
        src = src.replace(old, new, 1)
        print('OK:', repr(old[:70]))
    else:
        print('MISS:', repr(old[:70]))

io.open(p, 'w', encoding='utf-8').write(src)
print('done')