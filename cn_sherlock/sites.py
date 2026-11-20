# -*- coding: utf-8 -*-
"""配置加载与站点筛选。"""
from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

DEFAULT_CONFIG = Path(__file__).resolve().parent / "resources" / "sites_cn.json"


class ConfigError(Exception):
    pass


def load_config(path: Optional[str] = None) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    config_path = Path(path) if path else DEFAULT_CONFIG
    if not config_path.exists():
        raise ConfigError(f"找不到站点配置：{config_path}")
    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError as exc:
        raise ConfigError(f"站点配置不是合法 JSON：{exc}") from exc

    sites = data.get("sites")
    if not isinstance(sites, list) or not sites:
        raise ConfigError("站点配置缺少有效的 sites 列表")
    for site in sites:
        for key in ("name", "status"):
            if not site.get(key):
                raise ConfigError(f"站点缺少必填字段 {key}: {site}")
        if site["status"] not in ("stable", "experimental", "manual"):
            raise ConfigError(f"{site['name']} 的 status 非法：{site['status']}")
        if site["status"] != "manual" and not site.get("probe"):
            raise ConfigError(f"{site['name']} 缺少 probe 配置")
    return sites, data.get("defaults", {})


def select_sites(sites: List[Dict[str, Any]],
                 include: Optional[List[str]] = None,
                 exclude: Optional[List[str]] = None,
                 include_experimental: bool = False,
                 include_manual: bool = False) -> List[Dict[str, Any]]:
    include_set = {s.strip().lower() for s in (include or []) if s.strip()}
    exclude_set = {s.strip().lower() for s in (exclude or []) if s.strip()}

    known = {s["name"].lower() for s in sites}
    unknown = (include_set | exclude_set) - known
    if unknown:
        raise ConfigError(f"未知站点：{', '.join(sorted(unknown))}；"
                          f"可用站点：{', '.join(s['name'] for s in sites)}")

    selected = []
    for site in sites:
        name = site["name"].lower()
        if include_set and name not in include_set:
            continue
        if name in exclude_set:
            continue
        status = site["status"]
        if status == "manual" and not (include_manual or name in include_set):
            continue
        if status == "experimental":
            # 显式点名必须执行；否则只有开启开关或配置 enabled 才执行
            if not (name in include_set or include_experimental or site.get("enabled")):
                continue
        selected.append(site)
    if not selected:
        raise ConfigError("筛选后没有可执行的站点")
    return selected


def enable_ansi() -> None:
    """Windows 控制台尽量开启 ANSI 颜色支持。"""
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        kernel32.SetConsoleMode(kernel32.GetStdHandle(-11), 7)
    except Exception:
        pass
