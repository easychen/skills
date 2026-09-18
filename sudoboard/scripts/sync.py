#!/usr/bin/env python3
# SudoBoard Skill · sync.py — 把 sudoboard/ 工程幂等同步到 App
#
# 依赖序：壁纸资产 → 数据源(+抓取验证) → 模板(静态校验) → 看板 → 轮播方案(+激活) → play/active 回读。
# App 侧 id 回填进 board.json（appId / hash 字段），重复执行不产生重复资源。
#
# 多屏：board.json 可用 `templates` / `dashboards` 数组 + playback.dashboardKeys（见 board_model.py）。
#
# 用法:
#   python3 sync.py [--dir <sudoboard工程目录>] [--url URL] [--pin PIN]
#                   [--dry-run] [--no-activate] [--force]
#   python3 sync.py snapshot [--dir D] [--url URL] [--pin PIN]   # 只拉真实快照 → preview/data.json
#
# 环境变量: SUDOBOARD_URL / SUDOBOARD_ADMIN_PIN（被命令行参数覆盖）
import argparse
import base64
import hashlib
import json
import os
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board_model as bm  # noqa: E402
import template_checks as tc  # noqa: E402

MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".svg": "image/svg+xml"}


class SyncError(Exception):
    pass


def log(step, msg):
    print(f"[{step}] {msg}")


def static_checks(source):
    """阻断项（与 build_preview/deploy_cf 共用 template_checks）。"""
    return tc.static_checks(source)


class Client:
    """极简 REST 客户端：手动维护 sb_admin Cookie。"""

    def __init__(self, base):
        self.base = base.rstrip("/")
        self.cookie = None

    def req(self, method, path, body=None, timeout=60):
        url = self.base + path
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(url, data=data, method=method)
        r.add_header("content-type", "application/json")
        if self.cookie:
            r.add_header("cookie", self.cookie)
        try:
            resp = urllib.request.urlopen(r, timeout=timeout)
        except urllib.error.HTTPError as e:
            detail = ""
            try:
                detail = json.loads(e.read().decode()).get("error", "")
            except Exception:
                pass
            raise SyncError(f"{method} {path} → HTTP {e.status} {detail}".strip()) from None
        except urllib.error.URLError as e:
            raise SyncError(f"{method} {path} → 连接失败: {e.reason}") from None
        setc = resp.headers.get("set-cookie")
        if setc and "sb_admin=" in setc:
            self.cookie = setc.split(";")[0]
        raw = resp.read().decode()
        return json.loads(raw) if raw else {}

    def must_ok(self, res, what):
        if not res.get("ok"):
            raise SyncError(f"{what} 失败: {json.dumps(res, ensure_ascii=False)[:200]}")
        return res.get("data") or {}


def load_board(root):
    path = os.path.join(root, "board.json")
    if not os.path.isfile(path):
        raise SyncError(f"找不到 {path}")
    with open(path, encoding="utf-8") as f:
        return json.load(f), path


def save_board(path, board):
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(board, f, ensure_ascii=False, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def login(cli, pin):
    res = cli.req("POST", "/api/auth/admin-login", {"pin": pin})
    if not res.get("ok"):
        raise SyncError("管理员登录失败：PIN 错误或服务不可用")


def upsert(cli, base_path, app_id, payload, what, data_key, log_tag):
    """appId 存在则 PUT 更新；404（设备重置/资源已被删）自动降级为重新创建。返回最终 id。"""
    if app_id:
        try:
            cli.must_ok(cli.req("PUT", f"{base_path}/{app_id}", payload), f"更新{what}")
            return app_id
        except SyncError as e:
            if "404" not in str(e):
                raise
            log(log_tag, f"⚠ {what} {app_id} 在设备上已不存在（配置可能被重置），改为重新创建")
    res = cli.must_ok(cli.req("POST", base_path, payload), f"创建{what}")
    return res[data_key]["id"]


def resolve_url(args, board):
    return (args.url or os.environ.get("SUDOBOARD_URL")
            or (board.get("device") or {}).get("url") or "http://127.0.0.1:8866")


def resolve_target(args, board):
    """真实同步用：URL + PIN（dry-run 不要用它，否则无设备也会强制要 PIN）。"""
    pin = args.pin or os.environ.get("SUDOBOARD_ADMIN_PIN") \
        or (board.get("device") or {}).get("pin")
    if not pin:
        raise SyncError("缺少管理员 PIN：用 --pin、环境变量 SUDOBOARD_ADMIN_PIN，或写在 board.json device.pin")
    return resolve_url(args, board), pin


def sync_assets(cli, board, root, dry):
    """上传所有被 dashboard 引用的壁纸（去重）；返回 {相对路径: assetAppId}。"""
    refs = {}
    for dash in bm.dashboards_of(board):
        bg = dash.get("background") or {}
        rel = bg.get("file")
        if rel and rel not in refs:
            refs[rel] = bg
    out = {}
    for rel, bg in refs.items():
        fpath = os.path.join(root, rel)
        if not os.path.isfile(fpath):
            raise SyncError(f"背景文件不存在: {fpath}")
        with open(fpath, "rb") as f:
            data = f.read()
        digest = hashlib.sha256(data).hexdigest()
        if dry:
            if bg.get("assetAppId") and bg.get("hash") == digest:
                log("1/6", f"[dry-run] 壁纸 {rel} 未变化，将跳过上传")
            else:
                log("1/6", f"[dry-run] 将上传壁纸 {rel}")
            out[rel] = bg.get("assetAppId")
            continue
        if bg.get("assetAppId") and bg.get("hash") == digest:
            try:
                assets = cli.must_ok(cli.req("GET", "/api/assets"), "读取素材列表").get("assets") or []
            except SyncError:
                assets = None  # 列表读不到时保守跳过
            if assets is None or any(a.get("id") == bg["assetAppId"] for a in assets):
                log("1/6", f"壁纸未变化，跳过上传（asset={bg['assetAppId']}）")
                out[rel] = bg["assetAppId"]
                continue
            log("1/6", f"⚠ 壁纸 {bg['assetAppId']} 在设备上已不存在（配置可能被重置），重新上传")
        ext = os.path.splitext(fpath)[1].lower()
        mime = MIME.get(ext, "image/jpeg")
        b64 = base64.b64encode(data).decode()
        name = os.path.splitext(os.path.basename(fpath))[0]
        theme_tag = "dark" if (board.get("board") or {}).get("theme") == "dark" else "light"
        res = cli.must_ok(cli.req("POST", "/api/assets/upload", {
            "name": name, "kind": "image", "mime": mime, "base64": b64,
            "tags": ["wallpaper", theme_tag, "sudoboard-skill"],
        }), "上传壁纸")
        bg["assetAppId"] = res["asset"]["id"]
        bg["hash"] = digest
        log("1/6", f"✓ 壁纸 {rel} 已上传 asset={bg['assetAppId']} ({len(b64) // 1024}KB base64)")
        out[rel] = bg["assetAppId"]
    return out


def sync_sources(cli, board, dry):
    out = {}
    for i, src in enumerate(board.get("sources") or [], 1):
        key = src.get("key") or f"source{i}"
        payload = dict(src.get("create") or {})
        if not payload.get("name"):
            raise SyncError(f"数据源 [{key}] 缺少 create.name")
        if dry:
            act = "更新" if src.get("appId") else "创建"
            log("2/6", f"[dry-run] {act}数据源 {key}（{payload['name']}）")
            out[key] = src.get("appId")
            continue
        sid = upsert(cli, "/api/datasources", src.get("appId"), payload, f"数据源 {key}", "source", "2/6")
        src["appId"] = sid
        # 立即抓取并验证
        snap = cli.req("POST", f"/api/datasources/{sid}/fetch")
        data = (snap.get("data") or {}) if snap.get("ok") else {}
        if data.get("ok"):
            vals = list((data.get("values") or {}).keys())
            log("2/6", f"✓ 数据源 {key} → {sid}  抓取成功，命名值: {vals}")
        else:
            warn = data.get("lastError") or "无数据（检查 URL/凭据/网络，设备端引擎稍后会自动重试）"
            log("2/6", f"⚠ 数据源 {key} → {sid}  抓取未成功: {warn}")
        out[key] = sid
    return out


def sync_templates(cli, board, root, dry, force):
    """同步全部模板；返回 {模板 key: appId}。"""
    out = {}
    theme = (board.get("board") or {}).get("theme")
    for tpl in bm.templates_of(board):
        key = tpl.get("key") or "main"
        rel = tpl.get("file") or "templates/main.jsx"
        tpl_path = os.path.join(root, rel)
        if not os.path.isfile(tpl_path):
            raise SyncError(f"模板文件不存在: {tpl_path}")
        with open(tpl_path, encoding="utf-8") as f:
            source = f.read()
        bad = static_checks(source)
        if bad:
            for v in bad:
                print(f"  ⚠ 模板静态检查 [{key}]: {v}", file=sys.stderr)
            if not force:
                raise SyncError(f"模板 {key} 静态校验未通过（--force 可跳过）")
        for w in tc.style_warnings(source, theme):
            print(f"  ⚠ 模板观感 [{key}]: {w}", file=sys.stderr)
        if dry:
            act = "更新" if tpl.get("appId") else "创建"
            log("3/6", f"[dry-run] {act}模板 {tpl.get('name')}")
            out[key] = tpl.get("appId")
            continue
        payload = {"name": tpl.get("name") or "未命名看板", "source": source}
        tpl["appId"] = upsert(cli, "/api/templates", tpl.get("appId"), payload,
                              f"模板 {tpl.get('name')}", "template", "3/6")
        log("3/6", f"✓ 模板 {key} 已同步 tpl={tpl['appId']}")
        out[key] = tpl["appId"]
    return out


def sync_dashboards(cli, board, source_ids, template_ids, asset_ids, dry):
    """同步全部看板；返回 {看板 key: appId}。"""
    out = {}
    for dash in bm.dashboards_of(board):
        key = dash.get("key") or "main"
        tpl_key = dash.get("templateKey")
        tpl_id = template_ids.get(tpl_key) if tpl_key else None
        if tpl_id is None and len(template_ids) == 1:
            tpl_id = next(iter(template_ids.values()))
        bg = dash.get("background") or {}
        bg_id = asset_ids.get(bg.get("file")) if bg.get("file") else None
        payload = {
            "name": dash.get("name") or "未命名看板",
            "templateId": tpl_id,
            "sourceIds": [source_ids[k] for k in (dash.get("sourceKeys") or []) if source_ids.get(k)],
            "bgOpacity": float(bg.get("opacity", 1.0)),
            "bgBlur": float(bg.get("blur", 0)),
            "refreshSeconds": int(dash.get("refreshSeconds", 60)),
        }
        if bg_id:
            payload["backgroundId"] = bg_id
        if dry:
            act = "更新" if dash.get("appId") else "创建"
            log("4/6", f"[dry-run] {act}看板 {payload['name']}（sources={payload['sourceIds']}, bg={bg_id}）")
            out[key] = dash.get("appId")
            continue
        dash["appId"] = upsert(cli, "/api/dashboards", dash.get("appId"), payload,
                               f"看板 {payload['name']}", "dashboard", "4/6")
        log("4/6", f"✓ 看板 {key} 已同步 dash={dash['appId']}")
        out[key] = dash["appId"]
    return out


def sync_playback(cli, board, dry, no_activate):
    pb = board.get("playback") or {}
    dashboards = []
    missing = []
    for key in bm.playback_dashboard_keys(board):
        d = bm.dashboard_by_key(board, key)
        if d is None:
            raise SyncError(f"playback.dashboardKeys 里的 '{key}' 在 dashboards 中不存在")
        if d.get("appId"):
            dashboards.append({"dashboardId": d["appId"],
                               "durationSeconds": int(pb.get("durationSeconds", 30))})
        else:
            missing.append(key)
    if missing:
        if dry:
            log("5/6", f"[dry-run] ⚠ 看板 {missing} 将在本次同步中创建，随后加入轮播")
            dashboards.append({"dashboardId": "<新建>", "durationSeconds": int(pb.get("durationSeconds", 30))})
        else:
            raise SyncError("看板尚未同步成功，无法加入轮播")
    if not dashboards:
        raise SyncError("playback.dashboardKeys 为空或未匹配到任何看板")
    payload = {
        "name": pb.get("name") or "主轮播",
        "dashboards": dashboards,
        "transition": pb.get("transition") or {"style": "fade", "durationMs": 800},
        "music": {"assetIds": [], "mode": "loopAll", "volume": 0.6},
        "background": {"mode": "perDashboard"},
    }
    if dry:
        act = "更新" if pb.get("appId") else "创建"
        log("5/6", f"[dry-run] {act}轮播方案 {payload['name']}（{len(dashboards)} 屏）")
        return
    gid = upsert(cli, "/api/playback-groups", pb.get("appId"), payload, f"轮播方案 {payload['name']}", "group", "5/6")
    pb["appId"] = gid
    log("5/6", f"✓ 轮播方案已保存 grp={gid}")
    should_activate = (not no_activate) and (pb.get("activate", True))
    if should_activate:
        cli.must_ok(cli.req("POST", f"/api/playback-groups/{gid}/activate", {}), "激活轮播方案")
        log("5/6", f"✓ 已设为激活组（设备 /play 将播放它）")


def verify(cli, board):
    want = [d["appId"] for d in bm.dashboards_of(board) if d.get("appId")]
    res = cli.must_ok(cli.req("GET", "/api/play/active"), "读取激活播放状态")
    active = [d.get("id") for d in (res.get("dashboards") or [])]
    missing = [d for d in want if d not in active]
    if want and not missing:
        log("6/6", f"✓ 验证通过：{len(want)} 块看板都在激活轮播中（共 {len(active)} 屏）")
    else:
        log("6/6", f"⚠ 激活组当前不含 {missing or want}（激活组屏: {active}）")
    log("6/6", "设备屏幕 ≤1s 自动更新，无需重启 App；局域网预览: http://<设备IP>:8866/play")


def do_sync(args):
    root = os.path.abspath(args.dir)
    board, board_path = load_board(root)

    if args.dry_run:
        # dry-run 不连设备：不解析 PIN，只打印计划（含 URL）
        log("0/6", f"[dry-run] 目标 {resolve_url(args, board)}（不连接，仅打印计划）")
        sync_assets(None, board, root, True)
        sync_sources(None, board, True)
        tids = sync_templates(None, board, root, True, args.force)
        sync_dashboards(None, board, {}, tids, {}, True)
        sync_playback(None, board, True, args.no_activate)
        log("6/6", "[dry-run] 计划完毕。去掉 --dry-run 执行真实同步。")
        return

    url, pin = resolve_target(args, board)
    cli = Client(url)
    log("0/6", f"目标 {url}")
    login(cli, pin)
    log("0/6", "✓ 管理员登录成功")
    asset_ids = sync_assets(cli, board, root, False)
    source_ids = sync_sources(cli, board, False)
    template_ids = sync_templates(cli, board, root, False, args.force)
    sync_dashboards(cli, board, source_ids, template_ids, asset_ids, False)
    sync_playback(cli, board, False, args.no_activate)
    save_board(board_path, board)
    log("—", "board.json 已回填 appIds（重复同步不会产生重复资源）")
    verify(cli, board)


def do_snapshot(args):
    root = os.path.abspath(args.dir)
    board, _ = load_board(root)
    url, pin = resolve_target(args, board)
    cli = Client(url)
    login(cli, pin)
    values, status, ts = {}, {}, None
    for src in board.get("sources") or []:
        sid = src.get("appId")
        if not sid:
            log("snap", f"⚠ 数据源 {src.get('key')} 尚未同步（无 appId），跳过")
            continue
        res = cli.must_ok(cli.req("GET", f"/api/data/{sid}"), f"读取 {src.get('key')} 快照")
        ok = bool(res.get("ok"))
        status[src.get("key") or sid] = {"ok": ok, "lastError": res.get("lastError")}
        for k, v in (res.get("values") or {}).items():
            if k in values:
                log("snap", f"⚠ 命名值 '{k}' 在多个源中重复，后者覆盖")
            values[k] = v
        if res.get("fetchedAt"):
            ts = max(ts or "", res["fetchedAt"])
    theme = (board.get("board") or {}).get("theme", "dark")
    out_dir = os.path.join(root, "preview")
    os.makedirs(out_dir, exist_ok=True)
    out = {"values": values,
           "meta": {"updatedAt": ts or datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
                    "sourceStatus": status, "theme": theme}}
    out_path = os.path.join(out_dir, "data.json")
    with open(out_path, "w", encoding="utf-8") as f:
        json.dump(out, f, ensure_ascii=False, indent=2)
    log("snap", f"✓ 真实快照已写入 {out_path}（命名值 {len(values)} 个）")
    log("snap", "下一步: python3 build_preview.py --dir ... --open")


def main():
    ap = argparse.ArgumentParser(description="SudoBoard 幂等同步 / 快照")
    ap.add_argument("--dir", default="./sudoboard", help="sudoboard 工程目录")
    ap.add_argument("--url", default=None, help="覆盖设备地址（默认取 $SUDOBOARD_URL / board.json）")
    ap.add_argument("--pin", default=None, help="管理员 PIN（默认取 $SUDOBOARD_ADMIN_PIN）")
    ap.add_argument("--dry-run", action="store_true", help="只打印计划，不连接不执行（无需 PIN）")
    ap.add_argument("--no-activate", action="store_true", help="不同步后激活轮播组")
    ap.add_argument("--force", action="store_true", help="跳过模板静态校验")
    ap.add_argument("command", nargs="?", default=None, choices=[None, "snapshot"])
    args = ap.parse_args()
    try:
        if args.command == "snapshot":
            do_snapshot(args)
        else:
            do_sync(args)
    except SyncError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
