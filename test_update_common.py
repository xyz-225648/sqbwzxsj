# -*- coding: utf-8 -*-
"""update_common.py 纯函数单元测试：python test_update_common.py"""
import sys
import unittest

try:
    sys.stdout.reconfigure(encoding='utf-8', errors='replace')
except Exception:
    pass

from update_common import (
    is_valid_page, norm_ver, page_ver, parse_latest, parse_program)

GOOD_LATEST = 'window.SQZY_LATEST={"v": "v2.4.1", "h": "2975043db7bb5bbc", "t": "2026-09-27 00:58"};'
GOOD_PROGRAM = ('window.SQZY_PROGRAM={"exe": "v2.4.3", "apk": "v2.4.3", "tag": "v2.4.3", '
                '"t": "2026-09-27 01:00", '
                '"exeUrl": "https://gitee.com/xyz-225648/sqbwzxsj/releases/download/v2.4.3/a.exe", '
                '"apkUrl": "https://gitee.com/xyz-225648/sqbwzxsj/releases/download/v2.4.3/a.apk", '
                '"exeSha256": "' + 'a' * 64 + '", "apkSha256": "' + 'b' * 64 + '", '
                '"exeSize": 26675535, "apkSize": 144232, '
                '"apkMirror": ["https://cdn.jsdelivr.net/gh/xyz-225648/sqbwzxsj@master/a.apk"]};')


class TestNormVer(unittest.TestCase):
    def test_plain(self):
        self.assertEqual(norm_ver('v2.4.3'), 20403)

    def test_leading_v_optional(self):
        self.assertEqual(norm_ver('2.10.0'), 21000)

    def test_numeric_order(self):
        self.assertGreater(norm_ver('v2.10.0'), norm_ver('v2.9.9'))

    def test_bad(self):
        for bad in ('', 'v2', '2.4', 'v2.4.x', None):
            self.assertEqual(norm_ver(bad), -1)


class TestPageVer(unittest.TestCase):
    def test_found(self):
        html = "var APP_VERSION = 'v2.4.1';"
        self.assertEqual(page_ver(html), 20401)

    def test_missing(self):
        self.assertEqual(page_ver('no version here'), -1)


class TestIsValidPage(unittest.TestCase):
    def test_valid(self):
        self.assertTrue(is_valid_page('<html>宿迁职业技术学院作息时间表' + 'x' * 6000))

    def test_invalid(self):
        self.assertFalse(is_valid_page('short'))
        self.assertFalse(is_valid_page('<html>' + 'x' * 6000))


class TestParseLatest(unittest.TestCase):
    def test_good(self):
        self.assertEqual(parse_latest(GOOD_LATEST),
                         {'v': 'v2.4.1', 'h': '2975043db7bb5bbc', 't': '2026-09-27 00:58'})

    def test_bad_version(self):
        bad = GOOD_LATEST.replace('v2.4.1', 'v2.4')
        self.assertIsNone(parse_latest(bad))

    def test_bad_hash(self):
        bad = GOOD_LATEST.replace('2975043db7bb5bbc', 'xyz')
        self.assertIsNone(parse_latest(bad))

    def test_bad_json(self):
        self.assertIsNone(parse_latest('window.SQZY_LATEST={v: 1};'))


class TestParseProgram(unittest.TestCase):
    def test_good(self):
        info = parse_program(GOOD_PROGRAM)
        self.assertEqual(info['exe'], 'v2.4.3')
        self.assertEqual(info['apk'], 'v2.4.3')

    def test_bad_domain(self):
        bad = GOOD_PROGRAM.replace('https://gitee.com/', 'https://evil.com/')
        self.assertIsNone(parse_program(bad))

    def test_bad_sha(self):
        bad = GOOD_PROGRAM.replace('a' * 64, 'z' * 63)
        self.assertIsNone(parse_program(bad))

    def test_bad_size(self):
        bad = GOOD_PROGRAM.replace('26675535', '100')
        self.assertIsNone(parse_program(bad))

    def test_bad_mirror(self):
        bad = GOOD_PROGRAM.replace('https://cdn.jsdelivr.net', 'http://insecure')
        self.assertIsNone(parse_program(bad))


if __name__ == '__main__':
    unittest.main(verbosity=2)
