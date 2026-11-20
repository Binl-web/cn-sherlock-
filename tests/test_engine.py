# -*- coding: utf-8 -*-
"""判定逻辑单元测试：全部离线，用构造响应覆盖各种国内平台响应形态。"""
import json
import unittest

from cn_sherlock.engine import (STATUS_BLOCKED, STATUS_ERROR, STATUS_FOUND,
                                STATUS_NOT_FOUND, Engine, Response, dig,
                                normalize, render_url)


def make_engine():
    return Engine([], {}, timeout=1, retries=0)


def resp(code, text="", final="https://example.com/u"):
    return Response(code, final, text, 12)


SITE = {
    "name": "测试站",
    "category": "测试",
    "status": "stable",
    "confidence": "high",
    "url": "https://example.com/{username}",
    "detect": {"type": "status", "found": [200], "not_found": [404, 500],
               "blocked": [403, 412]},
}


class StatusDetectTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()

    def test_found(self):
        r = self.engine._evaluate(SITE, "alice", resp(200, "ok"))
        self.assertEqual(r["status"], STATUS_FOUND)
        self.assertEqual(r["profile_url"], "https://example.com/alice")

    def test_not_found(self):
        r = self.engine._evaluate(SITE, "alice", resp(404, "not found"))
        self.assertEqual(r["status"], STATUS_NOT_FOUND)

    def test_404_treated_as_not_found_even_if_error_code_is_500(self):
        r = self.engine._evaluate(SITE, "alice", resp(500, "internal"))
        self.assertEqual(r["status"], STATUS_NOT_FOUND)

    def test_blocked_must_not_be_negative(self):
        r = self.engine._evaluate(SITE, "alice", resp(412, "risk control"))
        self.assertEqual(r["status"], STATUS_BLOCKED)

    def test_unknown_status_is_error(self):
        r = self.engine._evaluate(SITE, "alice", resp(521, "waf"))
        self.assertEqual(r["status"], STATUS_ERROR)

    def test_page_marker_overrides_200(self):
        site = dict(SITE, detect=dict(SITE["detect"],
                                      not_found_markers=["404 Oops"]))
        r = self.engine._evaluate(site, "alice", resp(200, "<title>404 Oops</title>"))
        self.assertEqual(r["status"], STATUS_NOT_FOUND)

    def test_blocked_marker_overrides_200(self):
        site = dict(SITE, detect=dict(SITE["detect"],
                                      blocked_markers=["百度安全验证"]))
        r = self.engine._evaluate(site, "alice", resp(200, "百度安全验证"))
        self.assertEqual(r["status"], STATUS_BLOCKED)

    def test_network_error(self):
        r = self.engine._evaluate(SITE, "alice",
                                  Response(0, "u", "", 1, error="timeout"))
        self.assertEqual(r["status"], STATUS_ERROR)

    def test_resolve_json_field(self):
        site = dict(SITE, resolve={"json_field": "url_token",
                                   "url": "https://example.com/people/{value}"})
        r = self.engine._evaluate(
            site, "alice", resp(200, json.dumps({"url_token": "real-alice"})))
        self.assertEqual(r["profile_url"], "https://example.com/people/real-alice")

    def test_resolve_final_url(self):
        site = dict(SITE, resolve={"use_final_url": True})
        r = self.engine._evaluate(
            site, "alice", resp(200, "ok", final="https://www.example.com/alice"))
        self.assertEqual(r["profile_url"], "https://www.example.com/alice")


class MessageDetectTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.site = {
            "name": "科学网", "status": "stable", "confidence": "medium",
            "url": "https://blog.example/u/{username}",
            "detect": {"type": "message", "found": [200],
                       "not_found_markers": ["您指定的用户空间不存在"]},
        }

    def test_marker_means_not_found(self):
        r = self.engine._evaluate(self.site, "alice",
                                  resp(200, "<p>抱歉，您指定的用户空间不存在</p>"))
        self.assertEqual(r["status"], STATUS_NOT_FOUND)

    def test_200_means_found(self):
        r = self.engine._evaluate(self.site, "alice",
                                  resp(200, "<title>科学网—alice的个人资料</title>"))
        self.assertEqual(r["status"], STATUS_FOUND)


class SearchDetectTest(unittest.TestCase):
    def setUp(self):
        self.engine = make_engine()
        self.site = {
            "name": "B站", "status": "stable", "confidence": "high",
            "url": "https://space.example/{mid}",
            "detect": {"type": "search", "list_path": "data.result",
                       "match_fields": ["uname"], "strip_html": True,
                       "json_check": {"field": "code", "ok": [0],
                                      "blocked_values": [-412]}},
            "resolve": {"field": "mid", "url": "https://space.example/{value}"},
        }

    def payload(self, items, code=0):
        return json.dumps({"code": code, "data": {"result": items}})

    def test_exact_match_with_html_highlight(self):
        text = self.payload([{"mid": 546195,
                              "uname": '<em class="keyword">老番茄</em>'},
                             {"mid": 1, "uname": "老番茄的粉丝"}])
        r = self.engine._evaluate(self.site, "老番茄", resp(200, text))
        self.assertEqual(r["status"], STATUS_FOUND)
        self.assertEqual(r["profile_url"], "https://space.example/546195")

    def test_partial_name_is_not_match(self):
        text = self.payload([{"mid": 1, "uname": "老番茄的粉丝"}])
        r = self.engine._evaluate(self.site, "老番茄", resp(200, text))
        self.assertEqual(r["status"], STATUS_NOT_FOUND)

    def test_empty_result(self):
        text = json.dumps({"code": 0, "data": {"result": None}})
        r = self.engine._evaluate(self.site, "nobody", resp(200, text))
        self.assertEqual(r["status"], STATUS_NOT_FOUND)

    def test_risk_control_code(self):
        r = self.engine._evaluate(self.site, "nobody", resp(200, '{"code":-412}'))
        self.assertEqual(r["status"], STATUS_BLOCKED)

    def test_non_json(self):
        r = self.engine._evaluate(self.site, "nobody", resp(200, "<html>waf</html>"))
        self.assertEqual(r["status"], STATUS_ERROR)

    def test_keyword_match_only_does_not_false_positive(self):
        # 搜索结果命中关键词但无同名用户：必须判为未发现
        site = dict(self.site, detect=dict(self.site["detect"],
                                           list_path="result_vos",
                                           match_fields=["username"],
                                           json_check={"field": "total", "ok_min": 1}))
        text = json.dumps({"total": 3, "result_vos": [
            {"username": "weixin_1"}, {"username": "weixin_2"}]})
        r = self.engine._evaluate(site, "zhangsan", resp(200, text))
        self.assertEqual(r["status"], STATUS_NOT_FOUND)


class HelperTest(unittest.TestCase):
    def test_render_url_quotes_chinese(self):
        url = render_url("https://x.com/u/{username}", "张三")
        self.assertEqual(url, "https://x.com/u/%E5%BC%A0%E4%B8%89")

    def test_normalize_strips_html_and_case(self):
        self.assertEqual(normalize('<em class="k">Alice</em>'), "alice")

    def test_dig_nested_null_safe(self):
        self.assertIsNone(dig({"a": {}}, "a.b.c"))
        self.assertEqual(dig({"a": {"b": [1, 2]}}, "a.b.1"), 2)


if __name__ == "__main__":
    unittest.main()
