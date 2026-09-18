#!/usr/bin/env python3
# SudoBoard Skill · board_model.py — board.json 归一化（单看板简写 / 多元素数组）
#
# 两种写法等价可用：
#   简写：  "template": {...}, "dashboard": {...}
#   数组：  "templates": [{...}], "dashboards": [{...}]   ← 数组优先（同时存在时忽略简写）
#
# 多屏轮播：dashboards 多个 + playback.dashboardKeys 引用各自的 key。
# 供 build_preview.py / sync.py / deploy_cf.py / bundle.py 共用，避免各写一套取法。


def templates_of(board):
    """返回模板列表（dict 列表）。"""
    arr = board.get("templates")
    if isinstance(arr, list) and arr:
        return [t for t in arr if isinstance(t, dict)]
    one = board.get("template")
    return [one] if isinstance(one, dict) else []


def dashboards_of(board):
    """返回看板列表（dict 列表）。"""
    arr = board.get("dashboards")
    if isinstance(arr, list) and arr:
        return [d for d in arr if isinstance(d, dict)]
    one = board.get("dashboard")
    return [one] if isinstance(one, dict) else []


def dashboard_by_key(board, key):
    if not key:
        return None
    for d in dashboards_of(board):
        if (d.get("key") or "") == key:
            return d
    return None


def primary_dashboard(board):
    """主看板：key == 'main' 优先，否则第一个。"""
    dashes = dashboards_of(board)
    if not dashes:
        return None
    for d in dashes:
        if (d.get("key") or "") == "main":
            return d
    return dashes[0]


def primary_template(board, dashboard=None):
    """主模板：主看板 templateKey 指向的 → key == 'main' → 第一个。"""
    temps = templates_of(board)
    if not temps:
        return None
    dash = dashboard if dashboard is not None else primary_dashboard(board)
    want = (dash or {}).get("templateKey")
    if want:
        for t in temps:
            if (t.get("key") or "") == want:
                return t
    for t in temps:
        if (t.get("key") or "") == "main":
            return t
    return temps[0]


def playback_dashboard_keys(board):
    pb = board.get("playback") or {}
    keys = pb.get("dashboardKeys")
    if isinstance(keys, list) and keys:
        return [str(k) for k in keys]
    dash = primary_dashboard(board)
    return [dash.get("key") or "main"] if dash else []


def board_display_name(board):
    """看板展示名：主看板名 > board.name > 'SudoBoard'。"""
    dash = primary_dashboard(board) or {}
    return (dash.get("name") or (board.get("board") or {}).get("name") or "SudoBoard")
