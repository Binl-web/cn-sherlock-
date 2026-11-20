# -*- coding: utf-8 -*-
"""命令行入口。"""
from __future__ import annotations

import argparse
import random
import string
import sys
from concurrent.futures import ThreadPoolExecutor
from typing import Any, Dict, List

from . import report
from .engine import (STATUS_BLOCKED, STATUS_FOUND, STATUS_NOT_FOUND,
                     STATUS_SKIPPED, VERSION, Engine)
from .sites import ConfigError, enable_ansi, load_config, select_sites


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="cnsherlock",
        description="cn-sherlock：面向国内平台的用户名存在性探测工具（零依赖）。",
        epilog="示例：\n"
               "  python cnsherlock.py 老番茄\n"
               "  python cnsherlock.py 老番茄 --site B站 --site 知乎\n"
               "  python cnsherlock.py 老番茄 --json out.json --csv out.csv\n"
               "  python cnsherlock.py --doctor\n"
               "  python cnsherlock.py --list-sites\n",
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )
    parser.add_argument("usernames", nargs="*", metavar="USERNAME",
                        help="一个或多个待检测的用户名/昵称")
    parser.add_argument("--site", "-s", action="append", metavar="NAME",
                        help="只检测指定站点，可重复传入")
    parser.add_argument("--exclude", "-x", action="append", metavar="NAME",
                        help="排除指定站点，可重复传入")
    parser.add_argument("--only-found", action="store_true",
                        help="终端只显示命中的站点")
    parser.add_argument("--json", metavar="PATH", help="导出 JSON 结果")
    parser.add_argument("--csv", metavar="PATH", help="导出 CSV 结果（UTF-8 BOM，Excel 可直接打开）")
    parser.add_argument("--output", "-o", metavar="PATH", help="导出 TXT 结果")
    parser.add_argument("--timeout", type=int, default=None, help="单请求超时秒数（默认 12）")
    parser.add_argument("--retries", type=int, default=None, help="失败重试次数（默认 2）")
    parser.add_argument("--workers", "-w", type=int, default=None, help="并发线程数（默认 8）")
    parser.add_argument("--proxy", "-p", metavar="URL",
                        help="HTTP/SOCKS 代理，例如 http://127.0.0.1:7890")
    parser.add_argument("--insecure", "-k", action="store_true",
                        help="跳过 TLS 证书校验（仅用于内网自签名环境）")
    parser.add_argument("--include-experimental", action="store_true",
                        help="启用实验站点（Gitee/贴吧/微博等，稳定性较低）")
    parser.add_argument("--include-manual", action="store_true",
                        help="输出需人工核验的平台（抖音/小红书/快手/微信）")
    parser.add_argument("--config", metavar="PATH", help="指定站点配置 JSON")
    parser.add_argument("--doctor", action="store_true",
                        help="对配置做在线自检（每个站点测一个已知存在/不存在的用户名）")
    parser.add_argument("--list-sites", action="store_true", help="列出配置内的站点")
    parser.add_argument("--no-color", action="store_true", help="禁用彩色输出")
    parser.add_argument("--quiet", "-q", action="store_true", help="不打印终端结果")
    parser.add_argument("--version", action="version", version=f"cn-sherlock {VERSION}")
    return parser


def expand(values: List[str]) -> List[str]:
    out = []
    for value in values or []:
        out.extend(part.strip() for part in value.split(",") if part.strip())
    return out


def run_queries(args, engine: Engine, sites, use_color: bool) -> List[Dict[str, Any]]:
    workers = args.workers or max(1, min(len(sites), 8))
    queries = []
    for username in args.usernames:
        if not args.quiet:
            print(f"[*] 检测用户名「{username}」，站点 {len(sites)} 个 ...")
        if workers == 1:
            results = [engine.check(site, username) for site in sites]
        else:
            with ThreadPoolExecutor(max_workers=workers) as pool:
                results = list(pool.map(lambda s: engine.check(s, username), sites))
        queries.append({"username": username, "results": results})
        report.print_results(username, results, args.only_found, use_color, args.quiet)
    return queries


def run_doctor(engine: Engine, sites, use_color: bool) -> int:
    miss_name = "zzqxj" + "".join(random.choice(string.ascii_lowercase) for _ in range(10))
    rows = []
    for site in sites:
        claimed = (site.get("doctor") or {}).get("claimed")
        if not claimed:
            rows.append({"site": site["name"], "result": "SKIP",
                         "detail": "未配置 doctor.claimed"})
            continue
        hit = engine.check(site, claimed)
        if hit["status"] == STATUS_SKIPPED:
            rows.append({"site": site["name"], "result": "SKIP",
                         "detail": hit["detail"]})
            continue
        missed = engine.check(site, miss_name)
        if hit["status"] == STATUS_FOUND and missed["status"] == STATUS_NOT_FOUND:
            rows.append({"site": site["name"], "result": "PASS",
                         "detail": f"存在样本命中；不存在样本正确排除（{hit['elapsed_ms']}ms）"})
        elif hit["status"] == STATUS_BLOCKED or missed["status"] == STATUS_BLOCKED:
            rows.append({"site": site["name"], "result": "SKIP",
                         "detail": f"被风控，未能完成验证：{hit['detail']} / {missed['detail']}"})
        else:
            rows.append({"site": site["name"], "result": "FAIL",
                         "detail": f"存在样本={hit['status']}，不存在样本={missed['status']}"})
    return report.print_doctor(rows, use_color)


def main(argv: List[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.reconfigure(encoding="utf-8")
        except (AttributeError, ValueError):
            pass
    enable_ansi()
    use_color = not args.no_color and sys.stdout.isatty()

    try:
        sites, defaults = load_config(args.config)
        if args.list_sites:
            report.print_sites(sites, use_color)
            return 0

        selected = select_sites(
            sites,
            include=expand(args.site),
            exclude=expand(args.exclude),
            include_experimental=args.include_experimental,
            include_manual=args.include_manual,
        )
    except ConfigError as exc:
        print(f"[x] {exc}", file=sys.stderr)
        return 2

    engine = Engine(selected, defaults, timeout=args.timeout,
                    retries=args.retries, proxy=args.proxy,
                    insecure=args.insecure)

    if args.doctor:
        return 1 if run_doctor(engine, selected, use_color) else 0

    if not args.usernames:
        parser.error("至少提供一个用户名，或使用 --doctor / --list-sites")

    queries = run_queries(args, engine, selected, use_color)

    payload = report.build_payload(queries, VERSION)
    try:
        if args.json:
            report.save_json(args.json, payload)
            print(f"[*] JSON 已写入：{args.json}")
        if args.csv:
            report.save_csv(args.csv, queries)
            print(f"[*] CSV 已写入：{args.csv}")
        if args.output:
            report.save_txt(args.output, queries)
            print(f"[*] TXT 已写入：{args.output}")
    except OSError as exc:
        print(f"[x] 写入结果失败：{exc}", file=sys.stderr)
        return 1

    # 有命中返回 0；全部未命中/受限也返回 0，避免脚本误判为执行失败
    found = sum(1 for q in queries for r in q["results"] if r["status"] == STATUS_FOUND)
    if not args.quiet:
        print(f"\n[*] 完成：共 {len(queries)} 个用户名，命中 {found} 条。"
              f" 提示：同名不等于同一人，请结合其他信息核验。")
    return 0
