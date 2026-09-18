#!/usr/bin/env python3
"""SudoBoard Skill · bundle.py — 看板包（Bundle v1）：生成 / 校验 / 分发。

与生成地无关的完整备份容器（与 App /api/bundle/export 产出完全同构）：

    manifest.json      { schemaVersion:1, kind:'sudoboard-bundle', boardName, createdAt,
                         hasAdminPin:true, files:[{path,sha256,size}] }
    config/payload     PBKDF2-HMAC-SHA256(10k) + AES-256-CBC（=App encryptJsonWithPassword），
                       明文为 configJson + admin.pin（PIN 明文必在 → 「解密成功即 PIN 必有」）
    assets/<id>.<ext>  资产二进制（id 与 config.assets 元数据对应；单资产 ≤5MiB）

生成模式（场景 B）：
    纯本地（默认）    board.json 离线组装 configJson（模板源码内联、id 本地铸造）
    --from-device     已同步设备：POST /api/config/export 取配置 + GET /assets/<id> 拉二进制

PIN（合二为一）：--pin 或 $SUDOBOARD_ADMIN_PIN —— 既是 ZIP 加密密码，
也是导入端（快速配置页）的管理密码。App 未初始化时无 PIN 可读，必须人工指定。

分发（deploy）：ZIP 明文上传，敏感内容全在加密 payload 内。
    auto（默认）  wrangler 已登录 → R2（用户账号，不设过期）；未登录 → 临时账号
                  （wrangler deploy --temporary，60 分钟生命周期，附 Claim URL 可转正）
    cmd           --upload-cmd 自托管兜底：环境变量 SUDOBOARD_ZIP=zip 路径，stdout 输出直链

用法：
    python3 bundle.py pack   --dir <sudoboard工程> --pin XXX [--out dist/bundle.zip]
                             [--from-device --url http://tv:8866] [--device-pin 123456]
    python3 bundle.py verify <zip> --pin XXX
    python3 bundle.py deploy <zip> [--mode auto|temporary|r2|cmd] [--upload-cmd '...']
                                   [--r2-bucket sudoboard-bundles]
"""
import base64
import hashlib
import json
import os
import re
import secrets
import shutil
import subprocess
import sys
import tempfile
import time
import zipfile
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import board_model as bm  # noqa: E402

SCHEMA_VERSION = 1
BUNDLE_KIND = "sudoboard-bundle"
MAX_ASSET_BYTES = 5 * 1024 * 1024  # Cloudflare 临时部署单资产上限

IMG_EXT = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
           "webp": "image/webp", "svg": "image/svg+xml"}
AUD_EXT = {"mp3": "audio/mpeg", "ogg": "audio/ogg", "wav": "audio/wav", "m4a": "audio/mp4"}


class BundleError(Exception):
    pass


def log(step, msg):
    print(f"[{step}] {msg}")


# ---------------- 加密（= App config_cipher.encryptJsonWithPassword） ----------------

def encrypt_payload(obj: dict, pin: str) -> str:
    """PBKDF2-HMAC-SHA256(10k) 派生 + AES-256-CBC/PKCS7（openssl，避免 pip 依赖）。"""
    salt, iv = secrets.token_bytes(16), secrets.token_bytes(16)
    key = hashlib.pbkdf2_hmac("sha256", pin.encode(), salt, 10000, 32)
    plain = json.dumps(obj, ensure_ascii=False).encode()
    r = subprocess.run(["openssl", "enc", "-aes-256-cbc", "-K", key.hex(), "-iv", iv.hex()],
                       input=plain, capture_output=True)
    if r.returncode != 0:
        raise BundleError(f"openssl 加密失败: {r.stderr.decode(errors='replace').strip()}")
    return json.dumps({
        "v": 1, "kdf": "pbkdf2-sha256", "iter": 10000,
        "salt": base64.b64encode(salt).decode(),
        "iv": base64.b64encode(iv).decode(),
        "d": base64.b64encode(r.stdout).decode(),
    })


def decrypt_payload(payload: str, pin: str) -> dict:
    p = json.loads(payload)
    if p.get("kdf") != "pbkdf2-sha256":
        raise BundleError("payload_unsupported")
    key = hashlib.pbkdf2_hmac("sha256", pin.encode(),
                              base64.b64decode(p["salt"]), int(p.get("iter", 10000)), 32)
    iv_hex = base64.b64decode(p["iv"]).hex()  # payload 存 base64（Dart IV.base64），openssl 要 hex
    r = subprocess.run(["openssl", "enc", "-d", "-aes-256-cbc", "-K", key.hex(), "-iv", iv_hex],
                       input=base64.b64decode(p["d"]), capture_output=True)
    if r.returncode != 0:
        raise BundleError("bad_password_or_payload")
    return json.loads(r.stdout)


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def _mint(prefix: str) -> str:
    return prefix + secrets.token_hex(4)


def _ext_mime(name: str):
    ext = os.path.splitext(name)[1].lower().lstrip(".")
    mime = {"jpg": "image/jpeg", "jpeg": "image/jpeg", "png": "image/png",
            "webp": "image/webp", "svg": "image/svg+xml", "mp3": "audio/mpeg",
            "ogg": "audio/ogg", "wav": "audio/wav", "m4a": "audio/mp4"}.get(ext)
    return ext, mime


def _board(root: str) -> dict:
    path = os.path.join(root, "board.json")
    if not os.path.isfile(path):
        raise BundleError(f"找不到 {path}")
    return json.load(open(path, encoding="utf-8"))


def _resolve(root: str, rel: str) -> str:
    return rel if os.path.isabs(rel) else os.path.join(root, rel)


def config_from_project(root: str) -> tuple[dict, list]:
    """board.json 离线组装 App 同构 configJson，返回 (configJson, 资产文件列表)。"""
    board = _board(root)
    assets, asset_files = [], []  # (meta, 本地路径)

    def add_asset(rel):
        path = _resolve(root, rel)
        if not os.path.isfile(path):
            raise BundleError(f"资产文件不存在: {rel}")
        data = open(path, "rb").read()
        if len(data) > MAX_ASSET_BYTES:
            raise BundleError(f"asset_too_large:{rel}（{len(data)}B > 5MiB，请压缩后重试）")
        ext, mime = _ext_mime(rel)
        if not mime:
            raise BundleError(f"不支持的资产类型: {rel}")
        name = os.path.splitext(os.path.basename(path))[0]
        aid = "a" + sha256(data)[:12]  # 内容寻址：重打包 id 稳定
        meta = {"id": aid, "kind": "image" if mime.startswith("image/") else "audio",
                "name": name, "fileName": f"{name}.{ext}", "mime": mime,
                "tags": [], "groups": []}
        if not any(a["id"] == aid for a in assets):
            assets.append(meta)
            asset_files.append((aid, ext, path))
        return aid

    sources, source_ids = [], {}
    for s in board.get("sources") or []:
        payload = dict(s.get("create") or {})
        payload["id"] = _mint("ds")
        source_ids[s.get("key")] = payload["id"]
        sources.append(payload)

    templates, template_ids = [], {}
    for t in bm.templates_of(board):
        if not t.get("file"):
            continue
        src_path = _resolve(root, t["file"])
        if not os.path.isfile(src_path):
            raise BundleError(f"模板文件不存在: {t['file']}")
        templates.append({"id": _mint("tpl"), "name": t.get("name") or "未命名看板",
                          "source": open(src_path, encoding="utf-8").read()})
        template_ids[t.get("key", "main")] = templates[-1]["id"]

    dashboards, dashboard_ids = [], {}
    for d in bm.dashboards_of(board):
        bg = d.get("background") or {}
        entry = {"id": _mint("dash"), "name": d.get("name") or "未命名看板",
                 "templateId": template_ids.get(d.get("templateKey")),
                 "sourceIds": [source_ids[k] for k in (d.get("sourceKeys") or []) if source_ids.get(k)],
                 "bgOpacity": float(bg.get("opacity", 1.0)), "bgBlur": float(bg.get("blur", 0)),
                 "refreshSeconds": int(d.get("refreshSeconds", 60))}
        if bg.get("file"):
            entry["backgroundId"] = add_asset(bg["file"])
        dashboards.append(entry)
        dashboard_ids[d.get("key", "main")] = entry["id"]

    pb = board.get("playback") or {}
    playback = []
    if dashboards:
        entries = [{"dashboardId": dashboard_ids[k],
                    "durationSeconds": int(pb.get("durationSeconds", 60))}
                   for k in (pb.get("dashboardKeys") or ["main"]) if dashboard_ids.get(k)]
        if not entries:   # playback 未指定 → 全部看板按顺序进轮播
            entries = [{"dashboardId": d["id"],
                        "durationSeconds": int(pb.get("durationSeconds", 60))}
                       for d in dashboards]
        playback.append({
            "id": _mint("grp"), "name": pb.get("name") or "主轮播",
            "dashboards": entries,
            "transition": pb.get("transition") or {"style": "fade", "durationMs": 800},
            "music": {"assetIds": [], "mode": "loopAll", "volume": 0.6},
            "background": {"mode": "perDashboard"},
        })

    config = {
        "preferences": {"theme": (board.get("board") or {}).get("theme", "dark"),
                        "locale": "system", "aiTimeoutMinutes": 10,
                        "playerVolume": 0.6, "musicQueueIds": [], "musicPlaying": False},
        "sources": sources, "templates": templates, "dashboards": dashboards,
        "playbackGroups": playback, "assets": assets, "ai": {"providers": []},
    }
    board_name = bm.board_display_name(board)
    return config, (asset_files, board_name)


def fetch_config_from_device(url: str, device_pin: str) -> tuple[dict, list]:
    """--from-device：配置取自 /api/config/export（明文），二进制走 /assets/<id>。"""
    import urllib.request
    import urllib.error

    base = url.rstrip("/")

    def req(method, path, body=None, cookie="", binary=False):
        data = json.dumps(body).encode() if body is not None else None
        r = urllib.request.Request(base + path, data=data, method=method,
                                   headers={"content-type": "application/json",
                                            **({"cookie": cookie} if cookie else {})})
        with urllib.request.urlopen(r, timeout=30) as resp:
            return resp.read() if binary else json.loads(resp.read())

    cookie = ""
    try:
        lr = urllib.request.Request(base + "/api/auth/admin-login",
                                    data=json.dumps({"pin": device_pin}).encode(),
                                    method="POST", headers={"content-type": "application/json"})
        with urllib.request.urlopen(lr, timeout=30) as resp:
            sc = resp.headers.get("set-cookie", "")
            cookie = sc.split(";")[0] if sc else ""
    except (urllib.error.URLError, OSError):
        cookie = ""

    resp = req("POST", "/api/config/export", {}, cookie)
    data = resp.get("data") or {}
    if data.get("format") != "plain":
        raise BundleError("device_export_not_plain")
    config = data["config"]

    asset_files = []
    for a in config.get("assets") or []:
        aid, ext = a["id"], _ext_mime(a.get("fileName") or a.get("name") or "a.bin")[0]
        raw = req("GET", f"/assets/{aid}", None, cookie, binary=True)
        if len(raw) > MAX_ASSET_BYTES:
            raise BundleError(f"asset_too_large:{a.get('name')}")
        asset_files.append((aid, ext, raw))
    return config, (asset_files, None)


def build_zip(config: dict, pin: str, asset_files: list, board_name: str, out: str) -> None:
    config = dict(config)
    config["admin"] = {"pin": pin}  # 合二为一契约：PIN 明文必在
    files = [("config/payload", encrypt_payload(config, pin).encode())]
    for entry in asset_files:
        aid, ext, source = entry
        data = source if isinstance(source, bytes) else open(source, "rb").read()
        files.append((f"assets/{aid}.{ext}", data))

    manifest = {
        "schemaVersion": SCHEMA_VERSION, "kind": BUNDLE_KIND,
        "boardName": board_name,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "hasAdminPin": True,
        "files": [{"path": p, "sha256": sha256(c), "size": len(c)} for p, c in files],
    }
    os.makedirs(os.path.dirname(os.path.abspath(out)), exist_ok=True)
    with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
        for p, c in files:
            z.writestr(p, c)
        z.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False))
    print(f"✓ 看板包已生成: {out}")
    print(f"  内容: {len(files) - 1} 个资产 + 加密配置；加密密码 = 管理密码（{pin[:2]}****）")


def resolve_pin(args) -> str:
    pin = ""
    if "--pin" in args:
        pin = args[args.index("--pin") + 1]
    pin = pin or os.environ.get("SUDOBOARD_ADMIN_PIN") or ""
    if not pin:
        raise BundleError("缺少管理密码：--pin XXX 或环境变量 SUDOBOARD_ADMIN_PIN"
                          "（App 未初始化时无法从设备读取，必须人工指定）")
    return pin


def cmd_pack(args):
    from_device = "--from-device" in args

    def val(flag, default=None):
        return args[args.index(flag) + 1] if flag in args else default

    out = val("--out", os.path.join(val("--dir", "."), "dist", "bundle.zip"))
    pin = resolve_pin(args)
    if from_device:
        url = val("--url") or (_board(val("--dir", "."))["device"]["url"])
        device_pin = val("--device-pin")
        if device_pin is None:
            board_path = os.path.join(val("--dir", "."), "board.json")
            device_pin = (_board(val("--dir", "."))["device"]["pin"]
                          if os.path.isfile(board_path) else "")
        config, (asset_files, name) = fetch_config_from_device(url, device_pin)
        board_name = val("--name") or name or "SudoBoard"
    else:
        root = val("--dir", ".")
        config, (asset_files, name) = config_from_project(root)
        board_name = val("--name") or name
    build_zip(config, pin, asset_files, board_name, out)
    return out


def cmd_verify(args):
    zip_path, pin = args[0], resolve_pin(args)
    if not os.path.isfile(zip_path):
        raise BundleError(f"找不到 {zip_path}")
    zf = zipfile.ZipFile(zip_path)
    manifest = json.loads(zf.read("manifest.json"))
    if manifest.get("kind") != BUNDLE_KIND or manifest.get("schemaVersion") != SCHEMA_VERSION:
        raise BundleError("bundle_unsupported")
    for f in manifest.get("files") or []:
        content = zf.read(f["path"])
        if f["sha256"] != sha256(content) or f["size"] != len(content):
            raise BundleError(f"bundle_corrupt:{f['path']}")
    config = decrypt_payload(zf.read("config/payload").decode(), pin)
    if not (config.get("admin") or {}).get("pin"):
        raise BundleError("bundle_pin_missing")
    print(f"✓ 看板包校验通过: {manifest.get('boardName')}，"
          f"{len(manifest.get('files') or [])} 个文件，PIN 已内置")


def parse_temporary_output(text: str) -> dict:
    url = claim = None
    minutes = 60
    for line in text.splitlines():
        line = line.strip()
        m = re.match(r"https?://\S+workers\.dev\S*$", line)
        if m and not url:
            url = m.group(0)
        if line.startswith("Claim URL:"):
            claim = line.split(":", 1)[1].strip()
        m2 = re.search(r"Claim within:\s*(\d+)\s*minutes", line)
        if m2:
            minutes = int(m2.group(1))
    return {"url": url, "claim_url": claim, "claim_minutes": minutes}


def _wrangler(min_version=None):
    """找到可用的 wrangler；min_version 如 (4,102,0) 不满足则自动尝试 npx wrangler@latest。"""
    candidates = [["wrangler"], ["npx", "-y", "wrangler@latest"]]
    for candidate in candidates:
        try:
            v = subprocess.run(candidate + ["--version"], capture_output=True, timeout=180)
            if v.returncode != 0:
                continue
            m = re.search(r"(\d+)\.(\d+)\.(\d+)", v.stdout.decode(errors="replace"))
            if m and min_version and tuple(map(int, m.groups())) < min_version:
                continue  # 版本不够，尝试下一个候选
            return candidate
        except (OSError, subprocess.TimeoutExpired):
            continue
    raise BundleError("未找到可用 wrangler"
                      + (f"（需 >= {'.'.join(map(str, min_version))}）" if min_version else "")
                      + "：npm i -g wrangler 或允许 npx 拉取")


def _whoami_logged_in(wr) -> bool:
    try:
        r = subprocess.run(wr + ["whoami"], capture_output=True, timeout=30)
        out = (r.stdout + r.stderr).decode(errors="replace")
        return r.returncode == 0 and "not authenticated" not in out.lower()
    except Exception:
        return False


def cmd_deploy(args):
    zip_path = args[0]
    mode = "auto"
    upload_cmd = r2_bucket = None
    i = 1
    while i < len(args):
        if args[i] == "--mode":
            mode = args[i + 1]; i += 2
        elif args[i] == "--upload-cmd":
            upload_cmd = args[i + 1]; i += 2
        elif args[i] == "--r2-bucket":
            r2_bucket = args[i + 1]; i += 2
        else:
            i += 1
    if not os.path.isfile(zip_path):
        raise BundleError(f"找不到 {zip_path}")

    if mode == "cmd":
        if not upload_cmd:
            raise BundleError("--mode cmd 需要 --upload-cmd（环境变量 SUDOBOARD_ZIP=zip 路径，stdout 输出直链）")
        r = subprocess.run(["sh", "-c", upload_cmd], env={**os.environ, "SUDOBOARD_ZIP": zip_path},
                           capture_output=True, text=True, timeout=300)
        if r.returncode != 0:
            raise BundleError(f"upload-cmd 失败: {r.stderr.strip()}")
        url = r.stdout.strip().splitlines()[-1].strip() if r.stdout.strip() else ""
        if not url.startswith("http"):
            raise BundleError(f"upload-cmd 未输出直链: {r.stdout!r}")
        print(f"✓ 已上传: {url}")
        return url

    wr = _wrangler()
    logged_in = _whoami_logged_in(wr)
    if mode == "auto":
        mode = "r2" if logged_in else "temporary"
    if mode == "temporary" and logged_in:
        # --temporary 不允许在登录态使用（官方约束）→ 已登录走 r2
        mode = "r2"

    name = "sudb-" + re.sub(r"[^a-z0-9-]", "", zip_path and
                            os.path.splitext(os.path.basename(zip_path))[0].lower())[:24] + "-" + \
        datetime.now().strftime("%m%d%H%M")

    if mode == "temporary":
        wr = _wrangler((4, 102, 0))  # --temporary 需 4.102.0+
        with tempfile.TemporaryDirectory(prefix="sudb-cf-") as td:
            pub = os.path.join(td, "public")
            os.makedirs(pub)
            shutil.copy(zip_path, os.path.join(pub, "bundle.zip"))
            json.dump({"name": name, "compatibility_date": "2026-01-01",
                       "assets": {"directory": "./public"}},
                      open(os.path.join(td, "wrangler.jsonc"), "w"))
            print("→ 未检测到 Cloudflare 登录态：使用匿名临时账号部署（60 分钟生命周期）...")
            r = subprocess.run(wr + ["deploy", "--temporary"], cwd=td,
                               capture_output=True, text=True, timeout=600)
            out = (r.stdout or "") + (r.stderr or "")
            if r.returncode != 0:
                raise BundleError(f"临时部署失败:\n{out.strip()[-800:]}")
            info = parse_temporary_output(out)
            if not info["url"]:
                raise BundleError(f"未解析到部署 URL:\n{out.strip()[-800:]}")
            url = info["url"].rstrip("/") + "/bundle.zip"
            print(f"✓ 已发布（{info['claim_minutes']} 分钟内有效）: {url}")
            if info["claim_url"]:
                print(f"  如需转永久账号请 60 分钟内领取: {info['claim_url']}")
            return url

    if mode == "r2":
        bucket = r2_bucket or "sudoboard-bundles"
        key = os.path.basename(zip_path)
        print(f"→ 已登录 Cloudflare：上传到 R2（{bucket}/{key}，不设过期）...")
        for cmd in (wr + ["r2", "bucket", "create", bucket],):
            subprocess.run(cmd, capture_output=True, timeout=120)  # 已存在则忽略
        r = subprocess.run(wr + ["r2", "object", "put", f"{bucket}/{key}",
                                 "--file", zip_path, "--remote"],
                           capture_output=True, text=True, timeout=600)
        if r.returncode != 0:
            raise BundleError(f"R2 上传失败: {(r.stderr or r.stdout).strip()[-500:]}")
        worker = os.path.join(tempfile.gettempdir(), "sudb-r2-servicer")
        os.makedirs(worker, exist_ok=True)
        open(os.path.join(worker, "worker.js"), "w").write(
            "export default{async fetch(req,env){const k=new URL(req.url).pathname.slice(1);"
            "if(!k)return new Response('usage: /<key>',{status:404});"
            "const o=await env.B.get(k);if(!o)return new Response('not_found',{status:404});"
            "return new Response(o.body,{headers:{'content-type':'application/zip',"
            "'content-disposition':'attachment; filename=\"'+k+'\"'}});}}")
        json.dump({"name": "sudb-bundle-servicer", "main": "worker.js",
                   "compatibility_date": "2026-01-01",
                   "wrangler": {"r2_buckets": None},
                   "r2_buckets": [{"binding": "B", "bucket_name": bucket}]},
                  open(os.path.join(worker, "wrangler.jsonc"), "w"))
        rw = subprocess.run(wr + ["deploy"], cwd=worker, capture_output=True,
                            text=True, timeout=600)
        out = (rw.stdout or "") + (rw.stderr or "")
        if rw.returncode != 0:
            raise BundleError(f"R2 下载 Worker 部署失败:\n{out.strip()[-500:]}")
        base = None
        for line in out.splitlines():
            m = re.match(r"(https?://\S+workers\.dev)\s*$", line.strip())
            if m:
                base = m.group(1)
        if not base:
            raise BundleError(f"未解析到 Worker URL:\n{out.strip()[-500:]}")
        url = f"{base}/{key}"
        print(f"✓ 已上传: {url}")
        return url

    raise BundleError(f"未知分发模式: {mode}")


def main(argv):
    if not argv:
        print(__doc__)
        return 2
    try:
        if argv[0] == "pack":
            cmd_pack(argv[1:])
        elif argv[0] == "verify":
            cmd_verify(argv[1:])
        elif argv[0] == "deploy":
            cmd_deploy(argv[1:])
        else:
            print(__doc__)
            return 2
        return 0
    except BundleError as e:
        print(f"✗ {e}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
