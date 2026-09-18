#!/usr/bin/env python3
# SudoBoard Skill · deploy_cf.py — 直接把看板部署到 Cloudflare（带后端，无需 App）
#
# 把 sudoboard/ 工程变成一份**自包含 Cloudflare Worker 工程**（dist/cf/）：
#   - 数据引擎（HTTP 源真实抓取 + JSONATA 抽取）跑在 Worker 里；
#   - KV（binding=SDB）存最新快照与资产；cron 按源最小间隔定时抓取；
#   - 播放页（/ 与 /play）与预览页同一条渲染路径，运行时轮询 /api/data；
#   - API：/api/status（脱敏）、/api/data（快照）、/api/refresh（强制重抓）、/assets/<id>。
# 全程不依赖 SudoBoard App；App 成为可选项。
#
# 用法:
#   python3 deploy_cf.py --dir <sudoboard工程> [--name sudb-xxx] [--dry-run]
#
# 前置: 已登录的 wrangler（wrangler login）—— KV/cron 需要真实账号资源，
#       匿名临时账号（--temporary）不支持，与 bundle.py 的分发通道不同。
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys

SCRIPTS = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, SCRIPTS)

import board_model as bm  # noqa: E402
import bundle  # noqa: E402  （复用 _wrangler / _whoami_logged_in / parse_temporary_output）
import template_checks as tc  # noqa: E402
from build_preview import CDN_PACKAGES, render_page_html  # noqa: E402

MIME = {".jpg": "image/jpeg", ".jpeg": "image/jpeg", ".png": "image/png",
        ".webp": "image/webp", ".svg": "image/svg+xml"}
COMPAT_DATE = "2026-01-01"


class DeployError(Exception):
    pass


def log(step, msg):
    print(f"[{step}] {msg}")


def stable_id(key: str) -> str:
    """源在工作器里的稳定 id：由 board.key 派生，重复部署不变。"""
    return "src" + hashlib.sha256(key.encode("utf-8")).hexdigest()[:8]


def slug(name: str) -> str:
    """Worker 名称：小写 + 非字母数字折叠为 '-'，最多 63；已带 sudb- 前缀则不再重复。

    中文/全非 ASCII 名（如「技能自测看板」）折叠后为空 —— 回退到名字的稳定短哈希，
    否则所有中文看板都会撞名成 `sudb-`（且 workers.dev 主机名以 '-' 结尾）。
    """
    body = re.sub(r"[^a-z0-9]+", "-", (name or "").lower()).strip("-")
    if not body:
        body = hashlib.sha1((name or "").encode("utf-8")).hexdigest()[:6]
    if not body.startswith("sudb-"):
        body = "sudb-" + body
    return body[:63].rstrip("-")


def resolve_worker_name(root: str, name: str | None = None) -> str:
    """生成与 Access 必须共用的 Worker 名解析（默认取主看板名，其次 board.name）。"""
    if name:
        return slug(name)
    return slug(bm.board_display_name(assume_root(root)))


def _resolve(root: str, rel: str) -> str:
    return rel if os.path.isabs(rel) else os.path.join(root, rel)


def assume_root(root: str):
    path = os.path.join(root, "board.json")
    if not os.path.isfile(path):
        raise DeployError(f"找不到 {path}")
    return json.load(open(path, encoding="utf-8"))


def assemble(root: str) -> tuple[dict, dict]:
    """board.json → (worker CONFIG, 资产清单)。

    CONFIG 只含引擎需要的内容：HTTP 源（fetch/extractors/interval）、看板元信息、
    minIntervalSeconds、refreshSeconds、playUrl、assets 的 mime 表。
    资产清单: {"files": {aid: 绝对路径}, "mimes": {aid: mime}}（仅引用背景文件）。
    """
    board = assume_root(root)

    sources, intervals = [], []
    for i, s in enumerate(board.get("sources") or []):
        key = s.get("key") or f"source{i + 1}"
        create = dict(s.get("create") or {})
        if create.get("type") == "db":
            kind = (create.get("db") or {}).get("kind") or "?"
            raise DeployError(
                f"数据源 [{key}] 是 {kind} DB 源：暂不支持 DB 源直连 Cloudflare，"
                f"请改用 HTTP 源（API 抓取），DB 源请走本地预览或 App")
        if create.get("type") != "http":
            raise DeployError(f"数据源 [{key}] 类型 {create.get('type')} 不支持 Cloudflare，仅支持 http")
        fetch = dict(create.get("fetch") or {})
        if not fetch.get("url"):
            raise DeployError(f"数据源 [{key}] 缺少 fetch.url")
        interval = int(create.get("intervalSeconds") or 300)
        if create.get("enabled", True):
            intervals.append(interval)
        sources.append({
            "id": stable_id(key),
            "name": create.get("name") or key,
            "type": "http",
            "enabled": create.get("enabled", True),
            "intervalSeconds": interval,
            "fetch": fetch,
            "extractors": create.get("extractors") or [],
        })

    dash = bm.primary_dashboard(board) or {}
    board_name = bm.board_display_name(board)
    theme = (board.get("board") or {}).get("theme", "dark")
    refresh = int(dash.get("refreshSeconds") or 60)

    # 资产：仅 board.dashboard.background.file 引用的那张图（含 hash 内容寻址 id）
    assets = {"files": {}, "mimes": {}}
    bg = (dash.get("background") or {})
    if bg.get("file"):
        fpath = _resolve(root, bg["file"])
        if not os.path.isfile(fpath):
            raise DeployError(f"背景文件不存在: {fpath}")
        data = open(fpath, "rb").read()
        if len(data) > 10 * 1024 * 1024:
            raise DeployError(f"asset_too_large:{bg['file']}（>10MiB，CF 单资产上限 25MiB，请压缩）")
        ext = os.path.splitext(fpath)[1].lower()
        mime = MIME.get(ext)
        if not mime:
            raise DeployError(f"不支持的背景类型: {fpath}")
        aid = "a" + hashlib.sha256(data).hexdigest()[:12]
        assets["files"][aid] = os.path.abspath(fpath)
        assets["mimes"][aid] = mime
        background = {
            "assetId": aid, "opacity": float(bg.get("opacity", 1.0)),
            "blur": float(bg.get("blur", 0)),
        }
    else:
        background = None

    cfg = {
        "boardName": board_name,
        "theme": theme,
        "refreshSeconds": refresh,
        "minIntervalSeconds": min(intervals) if intervals else 300,
        "playUrl": "/play",
        "sources": sources,
        "assets": {aid: {"mime": mime} for aid, mime in assets["mimes"].items()},
        "background": background,
    }
    return cfg, assets


def template_source(root: str) -> str:
    board = assume_root(root)
    rel = (bm.primary_template(board) or {}).get("file", "templates/main.jsx")
    path = _resolve(root, rel)
    if not os.path.isfile(path):
        raise DeployError(f"模板文件不存在: {path}")
    return open(path, encoding="utf-8").read()


def render_worker(cfg: dict, play_html: str) -> str:
    """渲染 worker.js：把 CONFIG 与播放页注入模板。

    worker.js 是独立 JS 模块（非内联 HTML），无需 </ 转义；json.dumps 已处理引号/换行。
    """
    with open(os.path.join(SCRIPTS, "cf_worker.template.js"), encoding="utf-8") as f:
        tpl = f.read()
    cfg_js = json.dumps(cfg, ensure_ascii=False)
    page_js = json.dumps(play_html, ensure_ascii=False)
    worker = tpl.replace("__SB_CFG__", cfg_js).replace("__SB_PAGE__", page_js)
    if "__SB_CFG__" in worker or "__SB_PAGE__" in worker:
        raise DeployError("worker 渲染后仍残留占位符")
    return worker


def render_play_page(cfg: dict, source: str) -> str:
    """播放页：与预览同一渲染路径，live 模式轮询 /api/data；背景走 /assets/<id>。"""
    is_light = tc.resolve_theme(source, cfg.get("theme", "dark"))[0] == "light"
    bg = cfg.get("background")
    bg_map = {"src": "", "dark": "", "light": "", "opacity": 1.0, "blur": 0}
    if bg and bg.get("assetId"):
        href = f"/assets/{bg['assetId']}"
        bg_map = {"src": href, "dark": href, "light": href,
                  "opacity": bg.get("opacity", 1.0), "blur": bg.get("blur", 0)}
    live = {"url": "/api/data", "intervalMs": max(5000, cfg.get("refreshSeconds", 60) * 1000)}
    return render_page_html(cfg["boardName"], source,
                            {"values": {}, "meta": {}}, cfg["theme"], is_light,
                            bg_map, CDN_PACKAGES, live=live)


def cron_expr(min_interval_seconds: int) -> str:
    """源最小抓取间隔 → Cloudflare cron（分钟粒度，1..59）。"""
    minutes = max(1, min(59, min_interval_seconds // 60))
    if minutes <= 1:
        return "* * * * *"
    return f"*/{minutes} * * * *"


def render_wrangler(name: str, ns_id: str, cron: str) -> str:
    obj = {
        "name": name,
        "main": "worker.js",
        "compatibility_date": COMPAT_DATE,
    }
    if ns_id:
        obj["kv_namespaces"] = [{"binding": "SDB", "id": ns_id}]
    if cron:
        obj["triggers"] = {"crons": [cron]}
    return json.dumps(obj, ensure_ascii=False, indent=2)


def generate(root: str, name: str | None = None, ns_id: str | None = None,
             dry_run: bool = True) -> str:
    """生成 dist/cf/ 完整工程（不部署）。返回工程目录。"""
    root = os.path.abspath(root)
    cfg, assets = assemble(root)
    source = template_source(root)
    for v in tc.static_checks(source):
        print(f"  ⚠ 模板静态检查: {v}")
    for w in tc.style_warnings(source, cfg.get("theme")):
        print(f"  ⚠ 模板观感: {w}")
    others = [d.get("name") or d.get("key") for d in bm.dashboards_of(assume_root(root))[1:]]
    if others:
        log("gen", f"⚠ Cloudflare 只服务一块看板：已选主看板「{cfg['boardName']}」，"
                   f"其余 {others} 请用 App 部署（sync.py）")
    worker_name = resolve_worker_name(root, name)
    cron = cron_expr(cfg["minIntervalSeconds"])

    play_html = render_play_page(cfg, source)
    worker = render_worker(cfg, play_html)

    out_dir = os.path.join(root, "dist", "cf")
    os.makedirs(out_dir, exist_ok=True)
    for fname, content in (
        ("worker.js", worker),
        ("play.html", play_html),
        ("wrangler.jsonc", render_wrangler(worker_name, ns_id or "", cron)),
        ("config.json", json.dumps(cfg, ensure_ascii=False, indent=2)),
    ):
        with open(os.path.join(out_dir, fname), "w", encoding="utf-8") as f:
            f.write(content)
    shutil.copyfile(os.path.join(SCRIPTS, "vendor", "jsonata.min.js"),
                    os.path.join(out_dir, "jsonata.min.js"))
    for aid, path in assets["files"].items():
        shutil.copyfile(path, os.path.join(out_dir, f"asset-{aid}{os.path.splitext(path)[1]}"))

    log("gen", f"Worker 工程已生成: {out_dir}")
    log("gen", f"  name={worker_name}  cron={cron}  sources={len(cfg['sources'])}")
    log("gen", f"  资产 {len(assets['files'])} 个: {list(assets['files'])}")
    if dry_run:
        log("gen", "[dry-run] 不执行 KV 创建 / 资产上传 / deploy")
    return out_dir


def kv_cmd(wr, *parts):
    """>= wrangler 4 的 kv key 命令默认走本地（miniflare）存储；必须显式 --remote 才对云端操作。
    kv namespace *（create/list）是账号级资源操作，不接受 --remote。"""
    cmd = list(wr) + list(parts)
    if len(parts) >= 2 and parts[1] == "key":
        cmd.append("--remote")
    return cmd


def deploy(root: str, name: str | None = None) -> str:
    """生成 → KV namespace → 上传资产 → wrangler deploy → 预热 → 返回 URL。"""
    out_dir = generate(root, name=name, dry_run=False)

    # 1) wrangler 可用 + 已登录（KV/cron 需要真实账号）
    wr = bundle._wrangler()
    if not bundle._whoami_logged_in(wr):
        raise DeployError("wrangler 未登录：请先 wrangler login（KV/cron 需要真实账号，"
                          "匿名临时账号不支持本部署）")

    # 2) KV namespace：已有 id 则复用（幂等）
    cfg_path = os.path.join(out_dir, "wrangler.jsonc")
    wrangler_cfg = json.load(open(cfg_path, encoding="utf-8"))
    nss = (wrangler_cfg.get("kv_namespaces") or [])
    ns_id = nss[0]["id"] if nss else ""
    if not ns_id:
        ns_name = wrangler_cfg["name"] + "-kv"
        # 幂等：已存在同名 namespace 则复用（namespace 是账号级资源，无 --remote）
        rl = subprocess.run(wr + ["kv", "namespace", "list"],
                            capture_output=True, text=True, timeout=120, cwd=out_dir)
        if rl.returncode == 0:
            lout = (rl.stdout or "") + (rl.stderr or "")
            m_arr = re.search(r"\[", lout)
            if m_arr:
                try:
                    decoder = json.JSONDecoder()
                    arr, _ = decoder.raw_decode(lout[m_arr.start():])
                    for item in arr:
                        if item.get("title") == ns_name and item.get("id"):
                            ns_id = item["id"]
                            log("kv", f"复用已有 namespace: {ns_name} id={ns_id}")
                            break
                except json.JSONDecodeError:
                    pass
        if not ns_id:
            log("kv", f"创建 KV namespace: {ns_name}")
            r = subprocess.run(wr + ["kv", "namespace", "create", ns_name],
                               capture_output=True, text=True, timeout=120, cwd=out_dir)
            out = (r.stdout or "") + (r.stderr or "")
            if r.returncode != 0:
                raise DeployError(f"KV namespace 创建失败:\n{out.strip()[-800:]}")
            ns_id = None
            for line in out.splitlines():
                try:
                    obj = json.loads(line)
                    if isinstance(obj, dict) and obj.get("id"):
                        ns_id = obj["id"]
                        break
                except json.JSONDecodeError:
                    continue
            if not ns_id:
                m = re.search(r'"id"\s*:\s*"([0-9a-f]{16,})"', out)
                if m:
                    ns_id = m.group(1)
            if not ns_id:
                raise DeployError(f"无法从 wrangler 输出解析 namespace id:\n{out.strip()[-800:]}")
        wrangler_cfg["kv_namespaces"] = [{"binding": "SDB", "id": ns_id}]
        with open(cfg_path, "w", encoding="utf-8") as f:
            json.dump(wrangler_cfg, f, ensure_ascii=False, indent=2)
        log("kv", f"✓ namespace id={ns_id}")

    # 3) 上传资产（内容寻址 id → asset:<id>）
    #    wrangler>=4 必须 --namespace-id + --remote 才会写云端（--binding 配 --remote 会报
    #    "No KV Namespaces configured"；不带 --remote 则写进本地 miniflare 状态，Worker 读不到）
    cfg_board, assets = assemble(os.path.abspath(root))
    for aid in assets["files"]:
        log("kv", f"上传资产 {aid} → asset:{aid}")
        r = subprocess.run(
            wr + ["kv", "key", "put", f"asset:{aid}",
                  "--namespace-id=" + ns_id, "--path=" + str(assets["files"][aid]),
                  "--remote"],
            capture_output=True, text=True, timeout=180, cwd=out_dir)
        if r.returncode != 0:
            raise DeployError(f"资产上传失败 {aid}:\n{((r.stderr or r.stdout).strip())[-500:]}")

    # 4) deploy
    log("deploy", f"wrangler deploy（{wrangler_cfg['name']}）...")
    r = subprocess.run(wr + ["deploy"], capture_output=True, text=True,
                       timeout=600, cwd=out_dir)
    out = (r.stdout or "") + (r.stderr or "")
    if r.returncode != 0:
        raise DeployError(f"wrangler deploy 失败:\n{out.strip()[-800:]}")
    info = bundle.parse_temporary_output(out)
    base = info["url"]
    if not base:
        raise DeployError(f"未解析到部署 URL:\n{out.strip()[-800:]}")
    base = base.rstrip("/")

    # 5) 预热：强制抓一次数据（不等 cron）。优先 curl（urllib 会受代理影响）
    try:
        r = subprocess.run(["curl", "-s", "--max-time", "60", "-X", "POST",
                            base + "/api/refresh"],
                           capture_output=True, text=True, timeout=75)
        data = json.loads(r.stdout or "{}")
        status = data.get("data", {}).get("meta", {}).get("sourceStatus", {})
        ok = sum(1 for s in status.values() if s.get("ok"))
        log("warm", f"✓ 预热完成: {ok}/{len(status)} 源抓取成功")
    except Exception as e:
        log("warm", f"⚠ 预热失败（cron 会自动重试）: {e}")

    log("done", f"播放地址: {base}/play")
    log("done", f"API 状态: {base}/api/status")
    return f"{base}/play"


def _wrangler_available() -> bool:
    try:
        bundle._wrangler()
        return True
    except bundle.BundleError:
        return False


# ================= Cloudflare Access（Worker 级，2026-08 起支持） =================

ACCESS_API = "https://api.cloudflare.com/client/v4/accounts/{account}/access/apps"


def parse_access_allow(spec: str) -> tuple[list, list] | None:
    """解析 --access-allow：'a@x.com,@example.com,@corp.cn,b@y.com'
    → (邮箱列表, 邮箱域名列表)。空/None → None（不启用 Access）。
    邮箱域名写法：@example.com（带 @ 前缀）或 example.com（省略 @ 也按域名算）。"""
    if not spec or not spec.strip():
        return None
    emails, domains = [], []
    for raw in spec.split(","):
        item = raw.strip()
        if not item:
            continue
        if item.startswith("@"):
            domains.append(item[1:])
        elif "@" not in item:
            domains.append(item)  # 裸域名也按域名放行
        else:
            emails.append(item)
    if not emails and not domains:
        return None
    return emails, domains


def access_app_payload(worker_name, emails, domains, name=None) -> dict:
    """Worker 级 Access 应用：保护该 Worker 的所有域名（workers.dev/自定义域/路由）。"""
    include = [{"email": {"email": e}} for e in emails] \
        + [{"email_domain": {"domain": d}} for d in domains]
    if not include:
        raise DeployError("Access 允许名单为空：--access-allow 至少要给一个邮箱或域名")
    return {
        "type": "self_hosted",
        "name": name or f"SudoBoard · {worker_name}",
        "destinations": [{"type": "worker", "worker_id": worker_name}],
        "policies": [{"decision": "allow", "include": include, "exclude": []}],
    }


def _http_json(method, url, token, body=None, timeout=30):
    import urllib.request
    import urllib.error
    data = json.dumps(body).encode() if body is not None else None
    req = urllib.request.Request(url, data=data, method=method)
    req.add_header("authorization", f"Bearer {token}")
    if body is not None:
        req.add_header("content-type", "application/json")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return json.loads(resp.read())
    except urllib.error.HTTPError as e:
        try:
            return json.loads(e.read())
        except Exception:
            return {"success": False, "errors": [{"code": e.code, "error": str(e)}]}


def access_status(api_token: str, account_id: str, worker_name: str) -> tuple[bool, str]:
    """探测目标 Worker 是否已被 Worker 级 Access 保护。返回 (protected, app_name|'')。"""
    if not api_token:
        return False, ""
    url = ACCESS_API.format(account=account_id)
    data = _http_json("GET", url, api_token)
    if not data.get("success"):
        return False, ""
    for app in data.get("result") or []:
        for dest in app.get("destinations") or []:
            if dest.get("type") == "worker" and \
                    dest.get("worker_id") == worker_name:
                return True, app.get("name") or ""
    return False, ""


def enable_access(api_token: str, account_id: str, worker_name: str,
                  emails: list, domains: list) -> tuple[bool, str]:
    """尝试创建 Worker 级 Access。返回 (ok, message)。失败只报错不抛（部署本身已成功）。"""
    if not api_token:
        return False, "未提供 CLOUDFLARE_API_TOKEN（需含 Access: Apps and Policies Edit 权限）"
    payload = access_app_payload(worker_name, emails, domains)
    url = ACCESS_API.format(account=account_id)
    data = _http_json("POST", url, api_token, body=payload)
    if data.get("success"):
        app = data.get("result") or {}
        return True, f"已创建 Access 应用「{app.get('name') or payload['name']}」"
    errs = data.get("errors") or [{}]
    return False, f"创建 Access 失败: {json.dumps(errs, ensure_ascii=False)[:300]}"


def access_tips(worker_name, public_url, protected, example_emails=None) -> list:
    """「至少提示用户」的兜底：未受保护时给出精确的启用步骤（含可复制的 API curl）。"""
    if protected:
        return []
    emails = example_emails or [_owner_email_from_wrangler() or "you@example.com"]
    quoted = ",".join(f"@{e.split('@')[-1]}" for e in emails[:1])
    curl = ("curl 'https://api.cloudflare.com/client/v4/accounts/$ACCOUNT_ID/access/apps' "
            "-X POST -H 'Authorization: Bearer $CLOUDFLARE_API_TOKEN' "
            "-H 'content-type: application/json' "
            f"--data '{json.dumps(access_app_payload(worker_name, emails, []), ensure_ascii=False)}'")
    return [
        f"⚠ 线上看板 {public_url} 当前对公网完全公开！",
        "  建议启用 Cloudflare Access（Worker 级，2026-08+ 支持），只允许指定邮箱访问：",
        "  ① 自动（推荐，需含 Access Edit 权限的 token）：",
        "     export CLOUDFLARE_API_TOKEN=<含 Access: Apps and Policies Edit 的 token>",
        f"     export CLOUDFLARE_ACCOUNT_ID=$ACCOUNT_ID；重跑 deploy_cf.py --access-allow {emails[0]}",
        "  ② 手动（Dashboard）：Workers & Pages → 对应 Worker → Access tab →",
        f"    Enable Access → All traffic → policy 选 Email，输入 {emails[0]}",
        "  ③ 手动（API，可复制）：",
        f"     {curl}",
    ]


def _owner_email_from_wrangler() -> str:
    """从 wrangler whoami 解析账号邮箱（作提示示例用）。"""
    try:
        r = subprocess.run(["wrangler", "whoami"], capture_output=True,
                           text=True, timeout=60)
        out = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"email\s+([\w.+-]+@[\w.-]+)", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def _account_id_from_wrangler() -> str:
    """从 wrangler whoami 解析 Account ID（CLOUDFLARE_ACCOUNT_ID 优先）。"""
    env = os.environ.get("CLOUDFLARE_ACCOUNT_ID")
    if env:
        return env.strip()
    try:
        r = subprocess.run(["wrangler", "whoami"], capture_output=True,
                           text=True, timeout=60)
        out = (r.stdout or "") + (r.stderr or "")
        m = re.search(r"Account ID\s+\|\s+([0-9a-f]{20,})", out)
        if m:
            return m.group(1)
    except Exception:
        pass
    return ""


def deploy_with_access(root: str, name: str | None = None,
                       access_allow: str | None = None) -> tuple[str, bool]:
    """部署（deploy）+ 访问控制：线上看板默认应受保护。
    返回 (play_url, access_protected)。Access 创建失败不阻断部署，但必须提示用户。"""
    url = deploy(root, name=name)
    worker_name = resolve_worker_name(root, name)
    api_token = os.environ.get("CLOUDFLARE_API_TOKEN") or ""
    account_id = _account_id_from_wrangler()

    protected, app_name = access_status(api_token, account_id, worker_name)
    allowed = parse_access_allow(access_allow) if access_allow else None
    if allowed and not protected:
        emails, domains = allowed
        ok, msg = enable_access(api_token, account_id, worker_name, emails, domains)
        if ok:
            protected = True
            print(f"[access] ✓ {msg}（仅以下邮箱/域名可访问: "
                  f"{','.join(allowed[0] + ['@'+d for d in allowed[1]])}）")
        else:
            print(f"[access] ✗ {msg}")
    if not protected:
        for line in access_tips(worker_name, url, protected=False,
                                example_emails=(allowed[0] if allowed else None)):
            print(line)
    else:
        print(f"[access] ✓ 该 Worker 受 Cloudflare Access 保护"
              + (f"（应用「{app_name}」）" if app_name else ""))
    return url, protected


def path_slug_from_board(root: str) -> str:
    """（保留）按 board.json 推导 Worker 名；与 generate/deploy 共用 resolve_worker_name。"""
    try:
        return resolve_worker_name(root)
    except DeployError:
        return "sudoboard"


def main(argv=None):
    ap = argparse.ArgumentParser(
        description="部署 SudoBoard 看板到 Cloudflare（无需 App；默认提示启用 Access 限邮箱）")
    ap.add_argument("--dir", default="./sudoboard", help="sudoboard 工程目录")
    ap.add_argument("--name", default=None, help="Worker 名称（默认由看板名生成）")
    ap.add_argument("--dry-run", action="store_true", help="只生成 dist/cf/ 工程，不部署")
    ap.add_argument("--access-allow", default=None, metavar="EMAILS",
                    help="允许访问的邮箱/邮箱域名，逗号分隔，如 you@x.com,@corp.cn。"
                         "部署后自动创建 Worker 级 Cloudflare Access（需 CLOUDFLARE_API_TOKEN "
                         "含 Access Apps and Policies Edit 权限）；无法自动时给出手动步骤。")
    args = ap.parse_args(argv)

    root = os.path.abspath(args.dir)
    try:
        if args.dry_run:
            generate(root, name=args.name, dry_run=True)
            return 0
        url, protected = deploy_with_access(root, name=args.name,
                                            access_allow=args.access_allow)
        print(f"\n✓ 已上线（无需 App，浏览器打开即看）: {url}")
        if not protected:
            print("  🔒 提示：看板当前公网公开；建议用上面的步骤启用 Cloudflare Access 限邮箱。")
        return 0
    except DeployError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())