# -*- coding: utf-8 -*-
"""站点配置的静态校验：保证新增站点不会破坏整体约束。"""
import unittest

from cn_sherlock.sites import load_config, select_sites


class ConfigTest(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.sites, cls.defaults = load_config()

    def test_names_unique(self):
        names = [s["name"] for s in self.sites]
        self.assertEqual(len(names), len(set(names)))

    def test_required_fields(self):
        for site in self.sites:
            self.assertTrue(site["name"])
            self.assertIn(site["status"], ("stable", "experimental", "manual"))
            if site["status"] != "manual":
                self.assertTrue(site["probe"]["url"].startswith("http"))

    def test_status_codes_not_overlap(self):
        for site in self.sites:
            detect = site.get("detect") or {}
            if detect.get("type") != "status":
                continue
            found = set(detect.get("found") or [])
            missing = set(detect.get("not_found") or [])
            blocked = set(detect.get("blocked") or [])
            self.assertFalse(found & missing, f"{site['name']} found/not_found 重叠")
            self.assertFalse(found & blocked, f"{site['name']} found/blocked 重叠")
            self.assertFalse(missing & blocked, f"{site['name']} not_found/blocked 重叠")

    def test_search_sites_have_match_fields(self):
        for site in self.sites:
            detect = site.get("detect") or {}
            if detect.get("type") == "search":
                self.assertTrue(detect.get("list_path"), site["name"])
                self.assertTrue(detect.get("match_fields"), site["name"])

    def test_stable_sites_have_doctor_sample(self):
        for site in self.sites:
            if site["status"] == "stable":
                self.assertTrue((site.get("doctor") or {}).get("claimed"),
                                f"{site['name']} 缺少 doctor.claimed")

    def test_select_defaults_exclude_experimental_and_manual(self):
        selected = select_sites(self.sites)
        statuses = {s["status"] for s in selected}
        self.assertEqual(statuses, {"stable"})

    def test_select_by_name_overrides_default(self):
        selected = select_sites(self.sites, include=["贴吧"])
        self.assertEqual([s["name"] for s in selected], ["贴吧"])

    def test_manual_site_by_name(self):
        selected = select_sites(self.sites, include=["抖音"])
        self.assertEqual([s["name"] for s in selected], ["抖音"])

    def test_unknown_site_raises(self):
        with self.assertRaises(Exception):
            select_sites(self.sites, include=["不存在的站"])


if __name__ == "__main__":
    unittest.main()
