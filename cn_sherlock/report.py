# -*- coding: utf-8 -*-
"""结果展示与导出：终端表格、JSON、CSV、TXT。"""
from __future__ import annotations

import csv
import json
import sys
import unicodedata
from datetime import datetime
from typing import Any, Dict, List

from .engine import (STATUS_BLOCKED, STATUS_ERROR, STATUS_FOUND, STATUS_MANUAL,
                     STATUS_NOT_FOUND, STATUS_SKIPPED)

COLOR = {
    STATUS_FOUND: "32",      # 绿
    STATUS_NOT_FOUND: "90",  # 灰
    STATUS_BLOCKED: "33",    # 黄
    STATUS_ERROR: "33",
    STATUS_SKIPPED: "90",
    STATUS_MANUAL: "36",     # 青
}
MARK = {
    STATUS_FOUND: "[+]",
    STATUS_NOT_FOUND: "[-]",
    STATUS_BLOCKED: "[!]",
    STATUS_ERROR: "[x]",
    STATUS_SKIPPED: "[.]",
    STATUS_MANUAL: "[?]",
}
SORT_ORDER = {
    STATUS_FOUND: 0,
    STATUS_MANUAL: 1,
    STATUS_BLOCKED: 2,
    STATUS_ERROR: 3,
    STATUS_NOT_FOUND: 4,
    STATUS_SKIPPED: 5,
}


def _width(text: str) -> int:
    return sum(2 if unicodedata.east_asian_width(ch) in "WF" else 1 for ch in text)


def _pad(text: str, width: int) -> str:
    return text + " " * max(0, width - _width(text))


def _paint(text: str, code: str, enabled: bool) -> str:
    return f"\033[{code}m{text}\033[0m" if enabled else text


def sort_results(results: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    return sorted(results, key=lambda r: SORT_ORDER.get(r.get("status"), 9))


def print_results(username: str, results: List[Dict[str, Any]],
                  only_found: bool = False, use_color: bool = True,
                  quiet: bool = False) -> None:
    if quiet:
        return
    rows = sort_results(results)
    if only_found:
        rows = [r for r in rows if r["status"] == STATUS_FOUND]
        if not rows:
            print(f"\n[*] 用户名：{username}\n    (无命中)")
            return

    site_w = max([_width(r["site"]) for r in rows] + [8])
    state_w = max([_width(r["status_cn"]) for r in rows] + [6])

    print()
    print(f"[*] 用户名：{username}")
    print("─" * 88)
    print(f"    {'':3}{_pad('站点', site_w)}  {_pad('结果', state_w)}  "
          f"{_pad('置信度', 6)}  {'耗时':>7}  链接 / 说明")
    for r in rows:
        color = COLOR.get(r["status"], "0")
        mark = MARK.get(r["status"], "[?]")
        state = _pad(r["status_cn"], state_w)
        conf = _pad(r.get("confidence", "-"), 6)
        elapsed = f"{r.get('elapsed_ms', 0) / 1000:.2f}s"
        detail = r.get("detail") or ""
        link = r.get("profile_url") or ""
        # 已发现时优先展示主页链接；未发现/受限时补充原因，避免只看到裸 URL
        tail = link
        if r["status"] != STATUS_FOUND and detail:
            tail = f"{link}  ({detail})" if link else detail
        print(f"    {_paint(mark, color, use_color)} "
              f"{_paint(_pad(r['site'], site_w), color, use_color)}  "
              f"{_paint(state, color, use_color)}  {conf}  {elapsed:>7}  {tail}")

    counts = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    print("─" * 88)
    print(f"    命中 {counts.get(STATUS_FOUND, 0)}  |  "
          f"未发现 {counts.get(STATUS_NOT_FOUND, 0)}  |  "
          f"受限 {counts.get(STATUS_BLOCKED, 0)}  |  "
          f"错误 {counts.get(STATUS_ERROR, 0)}  |  "
          f"跳过 {counts.get(STATUS_SKIPPED, 0)}  |  "
          f"待核验 {counts.get(STATUS_MANUAL, 0)}")


def build_payload(queries: List[Dict[str, Any]], version: str) -> Dict[str, Any]:
    return {
        "tool": "cn-sherlock",
        "version": version,
        "generated_at": datetime.now().astimezone().isoformat(timespec="seconds"),
        "queries": queries,
    }


def save_json(path: str, payload: Dict[str, Any]) -> None:
    with open(path, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, ensure_ascii=False, indent=2)
        fh.write("\n")


def save_csv(path: str, queries: List[Dict[str, Any]]) -> None:
    fields = ["username", "site", "category", "status", "status_cn",
              "confidence", "profile_url", "http_status", "elapsed_ms",
              "method", "detail"]
    with open(path, "w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=fields, extrasaction="ignore")
        writer.writeheader()
        for query in queries:
            for row in query["results"]:
                writer.writerow({"username": query["username"], **row})


def save_txt(path: str, queries: List[Dict[str, Any]]) -> None:
    lines = []
    for query in queries:
        lines.append(f"用户名: {query['username']}")
        for r in sort_results(query["results"]):
            mark = MARK.get(r["status"], "[?]")
            link = r.get("profile_url") or "-"
            if r["status"] == STATUS_FOUND:
                lines.append(f"{mark} {r['site']}: {link}")
            elif r["status"] == STATUS_MANUAL:
                lines.append(f"{mark} {r['site']}: {link}  ({r.get('detail', '')})")
            else:
                lines.append(f"{mark} {r['site']}: {r['status_cn']}"
                             f"（{r.get('detail', '')}）")
        lines.append("")
    with open(path, "w", encoding="utf-8") as fh:
        fh.write("\n".join(lines).rstrip() + "\n")


def print_sites(sites: List[Dict[str, Any]], use_color: bool = True) -> None:
    print(f"\n配置内共 {len(sites)} 个站点：\n")
    name_w = max([_width(s["name"]) for s in sites] + [6])
    cat_w = max([_width(s.get("category", "")) for s in sites] + [8])
    print(f"  {_pad('站点', name_w)}  {_pad('分类', cat_w)}  "
          f"{_pad('状态', 6)}  {'默认':4}  说明")
    for s in sites:
        st = s.get("status", "stable")
        color = {"stable": "32", "experimental": "33",
                 "manual": "36"}.get(st, "0")
        label = {"stable": "稳定", "experimental": "实验", "manual": "需人工"}.get(st, st)
        default = "启用" if s.get("enabled", st == "stable") else "关闭"
        print(f"  {_pad(s['name'], name_w)}  {_pad(s.get('category', ''), cat_w)}  "
              f"{_paint(_pad(label, 6), color, use_color)}  {default:4}  "
              f"{(s.get('notes') or s.get('reason') or '')}")


def print_doctor(rows: List[Dict[str, Any]], use_color: bool = True) -> int:
    print("\n站点自检（--doctor）")
    print("─" * 80)
    name_w = max([_width(r["site"]) for r in rows] + [6])
    failed = 0
    for r in rows:
        ok = r["result"]
        color = "32" if ok == "PASS" else ("33" if ok == "SKIP" else "31")
        print(f"  {_paint(_pad(r['result'], 5), color, use_color)}  "
              f"{_pad(r['site'], name_w)}  {r['detail']}")
        if ok == "FAIL":
            failed += 1
    print("─" * 80)
    print(f"  通过 {sum(1 for r in rows if r['result'] == 'PASS')} / "
          f"失败 {failed} / 跳过 {sum(1 for r in rows if r['result'] == 'SKIP')}")
    return failed
