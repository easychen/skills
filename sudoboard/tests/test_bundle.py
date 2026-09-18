"""Bundle v1 契约测试（TDD）：bundle.py 产出的 ZIP 必须与 App BundleService 同构。

运行: python3 -m unittest discover -s skills/sudoboard/tests -v
"""
import base64
import hashlib
import json
import os
import subprocess
import sys
import tempfile
import threading
import unittest
import zipfile
from http.server import BaseHTTPRequestHandler, HTTPServer

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

import bundle  # noqa: E402

PIN = "246810"
FAKE_JPEG = b"fake-jpeg-bytes-for-test"


def decrypt_payload(payload_json: str, pin: str) -> dict:
    """用 openssl 复原 App decryptConfigPayload 语义（PBKDF2 10k + AES-256-CBC）。"""
    p = json.loads(payload_json)
    assert p["kdf"] == "pbkdf2-sha256" and p["iter"] == 10000 and p["v"] == 1
    key = hashlib.pbkdf2_hmac("sha256", pin.encode(), base64.b64decode(p["salt"]), p["iter"], 32)
    out = subprocess.run(
        ["openssl", "enc", "-d", "-aes-256-cbc", "-K", key.hex(),
         "-iv", base64.b64decode(p["iv"]).hex()],
        input=base64.b64decode(p["d"]), capture_output=True, check=True)
    return json.loads(out.stdout)


def sha256(b: bytes) -> str:
    return hashlib.sha256(b).hexdigest()


def make_project(root: str) -> str:
    """标准 sudoboard 工程：board.json + 模板 + 两张壁纸。"""
    os.makedirs(os.path.join(root, "templates"), exist_ok=True)
    os.makedirs(os.path.join(root, "assets"), exist_ok=True)
    open(os.path.join(root, "templates", "main.jsx"), "w").write(
        "export default function Screen({ data }) { return null; }")
    for n in ("wallpaper-dark.jpg", "wallpaper-light.jpg"):
        open(os.path.join(root, "assets", n), "wb").write(FAKE_JPEG + n.encode())
    json.dump({
        "device": {"url": "http://127.0.0.1:8866", "pin": "123456"},
        "board": {"name": "项目总览", "theme": "light"},
        "sources": [{"key": "demo", "appId": None, "create": {
            "name": "演示源", "type": "http", "intervalSeconds": 60, "enabled": True,
            "fetch": {"url": "http://x/metrics", "method": "GET", "timeoutSeconds": 8},
            "extractors": [{"name": "v", "jsonata": "a"}]}}],
        "template": {"key": "main", "appId": None, "name": "项目总览", "file": "templates/main.jsx"},
        "dashboard": {"key": "main", "appId": None, "name": "项目总览", "templateKey": "main",
                      "sourceKeys": ["demo"],
                      "background": {"file": "assets/wallpaper-light.jpg", "opacity": 1.0, "blur": 0},
                      "refreshSeconds": 60},
        "playback": {"key": "main", "appId": None, "name": "主轮播", "dashboardKeys": ["main"],
                     "durationSeconds": 60, "transition": {"style": "fade", "durationMs": 800},
                     "activate": True},
    }, open(os.path.join(root, "board.json"), "w"), ensure_ascii=False)
    return root


class FakeDeviceHandler(BaseHTTPRequestHandler):
    """--from-device 模式的假设备：config/export 明文 + /assets/<id> 二进制。"""

    asset_id = "aFakeId123"
    log = []

    def _send(self, code, body: bytes, ctype="application/json"):
        self.send_response(code)
        self.send_header("content-type", ctype)
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def do_POST(self):
        FakeDeviceHandler.log.append(("POST", self.path))
        if self.path == "/api/auth/admin-login":
            self._send(200, json.dumps({"ok": True, "data": {}}).encode(),
                       "application/json")  # cookie 校验此测试不深究
        elif self.path == "/api/config/export":
            cfg = {
                "preferences": {"theme": "light", "locale": "zh",
                                "aiTimeoutMinutes": 10, "playerVolume": 0.6,
                                "musicQueueIds": [], "musicPlaying": False},
                "sources": [{"id": "dsDev1", "name": "设备上的源", "type": "http",
                             "fetch": {"url": "http://x", "method": "GET"},
                             "extractors": []}],
                "templates": [], "dashboards": [], "playbackGroups": [],
                "assets": [{"id": FakeDeviceHandler.asset_id, "kind": "image",
                            "name": "devwall", "fileName": "devwall.jpg",
                            "mime": "image/jpeg", "tags": [], "groups": []}],
                "ai": {"providers": []},
            }
            self._send(200, json.dumps({"ok": True, "data": {"format": "plain", "config": cfg}}).encode())
        else:
            self._send(404, b'{"ok":false}')

    def do_GET(self):
        if self.path.startswith(f"/assets/{FakeDeviceHandler.asset_id}"):
            self._send(200, FAKE_JPEG, "image/jpeg")
        else:
            self._send(404, b"{}")


class BundlePackTest(unittest.TestCase):
    """场景 B（Skill 端生成）——纯本地离线模式。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sudb-bundle-py-")
        self.proj = make_project(os.path.join(self.tmp, "sudoboard"))

    def test_pack_offline_bundle_structure_and_payload(self):
        out = os.path.join(self.tmp, "bundle.zip")
        bundle.cmd_pack(["--dir", self.proj, "--pin", PIN, "--out", out])

        self.assertTrue(os.path.isfile(out))
        zf = zipfile.ZipFile(out)
        names = set(zf.namelist())
        # 只有 board.json 引用的资产（light）入包；内容寻址 id
        light_id = "a" + hashlib.sha256(FAKE_JPEG + b"wallpaper-light.jpg").hexdigest()[:12]
        self.assertEqual({"manifest.json", "config/payload", f"assets/{light_id}.jpg"}, names)

        # manifest：v1 契约 + 哈希清单逐项吻合
        manifest = json.loads(zf.read("manifest.json"))
        self.assertEqual(manifest["schemaVersion"], 1)
        self.assertEqual(manifest["kind"], "sudoboard-bundle")
        self.assertTrue(manifest["hasAdminPin"])
        self.assertEqual(manifest["boardName"], "项目总览")
        for f in manifest["files"]:
            content = zf.read(f["path"])
            self.assertEqual(f["sha256"], sha256(content), f["path"])
            self.assertEqual(f["size"], len(content), f["path"])
        self.assertIn("config/payload", {f["path"] for f in manifest["files"]})

        # payload：PIN 可解密（App decryptConfigPayload 同语义），PIN 明文在内
        cfg = decrypt_payload(zf.read("config/payload").decode(), PIN)
        self.assertEqual(cfg["admin"]["pin"], PIN)
        self.assertEqual(cfg["preferences"]["theme"], "light")

        # 全量业务配置齐备且引用一致
        self.assertEqual(cfg["sources"][0]["name"], "演示源")
        self.assertEqual(cfg["templates"][0]["name"], "项目总览")
        self.assertIn("export default", cfg["templates"][0]["source"])
        dash = cfg["dashboards"][0]
        self.assertEqual(dash["templateId"], cfg["templates"][0]["id"])
        self.assertEqual(dash["sourceIds"], [cfg["sources"][0]["id"]])
        self.assertEqual(dash["backgroundId"], cfg["assets"][0]["id"])
        grp = cfg["playbackGroups"][0]
        self.assertEqual(grp["dashboards"][0]["dashboardId"], dash["id"])
        self.assertEqual(grp["dashboards"][0]["durationSeconds"], 60)
        # 资产元数据与磁盘文件一一对应
        self.assertEqual(cfg["assets"][0]["id"], dash["backgroundId"])
        self.assertEqual(cfg["assets"][0]["mime"], "image/jpeg")

    def test_pack_without_pin_fails_clearly(self):
        with self.assertRaises(bundle.BundleError) as cm:
            bundle.cmd_pack(["--dir", self.proj, "--out", os.path.join(self.tmp, "x.zip")])
        self.assertIn("pin", str(cm.exception).lower())

    def test_verify_detects_corruption(self):
        out = os.path.join(self.tmp, "bundle.zip")
        bundle.cmd_pack(["--dir", self.proj, "--pin", PIN, "--out", out])
        # 重写 ZIP：篡改 payload 内容（保持结构合法）→ verify 必须因 sha256 不符失败
        zf_in = zipfile.ZipFile(out)
        bad = os.path.join(self.tmp, "bad.zip")
        with zipfile.ZipFile(bad, "w", zipfile.ZIP_DEFLATED) as z:
            for n in zf_in.namelist():
                content = zf_in.read(n)
                if n == "config/payload":
                    content = b"X" + content[1:]
                z.writestr(n, content)
        with self.assertRaises(bundle.BundleError):
            bundle.cmd_verify([bad, "--pin", PIN])

    def test_board_without_background_has_no_assets(self):
        b = json.load(open(os.path.join(self.proj, "board.json")))
        del b["dashboard"]["background"]
        json.dump(b, open(os.path.join(self.proj, "board.json"), "w"), ensure_ascii=False)
        out = os.path.join(self.tmp, "bundle.zip")
        bundle.cmd_pack(["--dir", self.proj, "--pin", PIN, "--out", out])
        self.assertEqual({"manifest.json", "config/payload"}, set(zipfile.ZipFile(out).namelist()))


class BundleFromDeviceTest(unittest.TestCase):
    """场景 B 的 --from-device 模式：配置取自设备 export，二进制走 /assets/<id>。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sudb-bundle-dev-")
        self.httpd = HTTPServer(("127.0.0.1", 0), FakeDeviceHandler)
        self.port = self.httpd.server_address[1]
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()

    def test_pack_from_device(self):
        out = os.path.join(self.tmp, "bundle.zip")
        bundle.cmd_pack(["--dir", self.proj if False else self.tmp,  # dir 仅作输出占位
                         "--from-device", "--url", f"http://127.0.0.1:{self.port}",
                         "--pin", PIN, "--out", out])
        zf = zipfile.ZipFile(out)
        cfg = decrypt_payload(zf.read("config/payload").decode(), PIN)
        self.assertEqual(cfg["admin"]["pin"], PIN)
        self.assertEqual(cfg["sources"][0]["name"], "设备上的源")
        aid = FakeDeviceHandler.asset_id
        self.assertEqual(zf.read(f"assets/{aid}.jpg"), FAKE_JPEG)
        self.assertEqual(cfg["assets"][0]["id"], aid)


class BundleDeployTest(unittest.TestCase):
    """deploy 的可测部分：--upload-cmd 通道与 wrangler 输出解析。"""

    def test_upload_cmd_receives_zip_and_returns_url(self):
        out = os.path.join(self.tmp2, "bundle.zip")
        bundle.cmd_pack(["--dir", self.proj2, "--pin", PIN, "--out", out])
        url = bundle.cmd_deploy([
            out, "--mode", "cmd",
            "--upload-cmd", f"cp \"$SUDOBOARD_ZIP\" {self.tmp2}/uploaded.zip && echo https://example.test/b.zip",
        ])
        self.assertEqual(url, "https://example.test/b.zip")
        self.assertTrue(os.path.isfile(os.path.join(self.tmp2, "uploaded.zip")))

    def test_parse_temporary_deploy_output(self):
        sample = """
Temporary account ready:
Account:        sudb-xyz (created)
Claim within:   60 minutes
Claim URL:      https://dash.cloudflare.com/claim-preview?claimToken=TOK123
Uploaded demo-worker
Deployed demo-worker triggers
https://sudb-xyz.sub.workers.dev
"""
        info = bundle.parse_temporary_output(sample)
        self.assertEqual(info["url"], "https://sudb-xyz.sub.workers.dev")
        self.assertEqual(info["claim_url"],
                         "https://dash.cloudflare.com/claim-preview?claimToken=TOK123")
        self.assertEqual(info["claim_minutes"], 60)

    def setUp(self):
        self.tmp2 = tempfile.mkdtemp(prefix="sudb-bundle-dep-")
        self.proj2 = make_project(os.path.join(self.tmp2, "sudoboard"))


class BundleMultiDashboardTest(unittest.TestCase):
    """多屏：templates/dashboards 数组必须完整进包（Bundle v1 payload）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sudb-bundle-multi-")
        self.proj = make_project(os.path.join(self.tmp, "sudoboard"))
        open(os.path.join(self.proj, "templates", "two.jsx"), "w").write(
            "/* sb-theme: dark */\nexport default function Screen({ data }) { return null; }")
        board = json.load(open(os.path.join(self.proj, "board.json"), encoding="utf-8"))
        board["templates"] = [
            {"key": "t1", "name": "T1", "file": "templates/main.jsx"},
            {"key": "t2", "name": "T2", "file": "templates/two.jsx"},
        ]
        board["dashboards"] = [
            {"key": "one", "name": "D1", "templateKey": "t1", "sourceKeys": ["demo"],
             "refreshSeconds": 60, "background": {"file": "assets/wallpaper-dark.jpg"}},
            {"key": "main", "name": "D2", "templateKey": "t2", "sourceKeys": ["demo"],
             "refreshSeconds": 60, "background": {"file": "assets/wallpaper-light.jpg"}},
        ]
        board["playback"]["dashboardKeys"] = ["one", "main"]
        board.pop("template", None)
        board.pop("dashboard", None)
        json.dump(board, open(os.path.join(self.proj, "board.json"), "w"), ensure_ascii=False)

    def test_pack_contains_all_screens(self):
        out = os.path.join(self.tmp, "bundle.zip")
        bundle.cmd_pack(["--dir", self.proj, "--pin", PIN, "--out", out])
        zf = zipfile.ZipFile(out)
        cfg = decrypt_payload(zf.read("config/payload").decode(), PIN)
        self.assertEqual([t["name"] for t in cfg["templates"]], ["T1", "T2"])
        self.assertEqual([d["name"] for d in cfg["dashboards"]], ["D1", "D2"])
        self.assertEqual(len(cfg["playbackGroups"][0]["dashboards"]), 2)
        ids = {d["dashboardId"] for d in cfg["playbackGroups"][0]["dashboards"]}
        self.assertEqual(len(ids), 2)
        # 两张壁纸都要进包
        self.assertEqual(len(cfg["assets"]), 2)
        # 模板 id 引用正确
        tpl_ids = {t["id"] for t in cfg["templates"]}
        for d in cfg["dashboards"]:
            self.assertIn(d["templateId"], tpl_ids)


if __name__ == "__main__":
    unittest.main()
