# -*- coding: utf-8 -*-
"""calendar.txt 格式校验（发布闸门用）：python check_calendar.py

规则与页面 parseCalendar 保持一致：
- # 开头是整行注释，行尾 # 之后是注释
- 每行：日期 或 日期~日期 + 模板名 + 说明（说明不能为空，会显示在页面提示条上）
- 模板名只允许 weekday / saturday / sunday / holiday
- 日期必须真实存在（2026-02-30 这种会直接报出来）
"""
import datetime
import os
import re
import sys

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

HERE = os.path.dirname(os.path.abspath(__file__))
TEMPLATES = ('weekday', 'saturday', 'sunday', 'holiday')
LINE_RE = re.compile(r'^\s*(\d{4}-\d{2}-\d{2})(?:\s*~\s*(\d{4}-\d{2}-\d{2}))?\s+(\w+)\s+(.+?)\s*$')


def valid_date(s):
    try:
        datetime.date.fromisoformat(s)
        return True
    except ValueError:
        return False


def main():
    path = os.path.join(HERE, 'calendar.txt')
    if not os.path.exists(path):
        print('  calendar.txt 不存在')
        return 1
    bad = 0
    ok = 0
    with open(path, encoding='utf-8') as f:
        for ln, line in enumerate(f, 1):
            s = line.strip()
            if not s or s.startswith('#'):
                continue
            s = s.split('#')[0].strip()      # 行尾注释
            if not s:
                continue
            m = LINE_RE.match(s)
            if not m:
                print('  ✗ 第%d行看不懂：%s' % (ln, s))
                bad += 1
                continue
            d1, d2, tpl, note = m.group(1), m.group(2), m.group(3), m.group(4)
            if not valid_date(d1):
                print('  ✗ 第%d行日期不存在：%s' % (ln, d1))
                bad += 1
                continue
            if d2 and not valid_date(d2):
                print('  ✗ 第%d行结束日期不存在：%s' % (ln, d2))
                bad += 1
                continue
            if d2 and d2 < d1:
                print('  ✗ 第%d行日期区间反了：%s ~ %s' % (ln, d1, d2))
                bad += 1
                continue
            if tpl not in TEMPLATES:
                print('  ✗ 第%d行模板名不认识：%s（只允许 %s）' % (ln, tpl, '/'.join(TEMPLATES)))
                bad += 1
                continue
            if not note:
                print('  ✗ 第%d行缺少说明（会显示在页面提示条上，必须写）' % ln)
                bad += 1
                continue
            ok += 1
    if bad:
        print('  calendar.txt 校验未通过：%d 行有问题，%d 行正常' % (bad, ok))
        return 1
    print('  calendar.txt 校验通过：%d 条特殊日' % ok)
    return 0


if __name__ == '__main__':
    sys.exit(main())
