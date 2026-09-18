"""sync.py 契约测试（TDD）：dry-run 免 PIN、多看板数组语义、幂等、404 降级、主题警告。

用真实 HTTP mock 复刻 app/lib/server/api_server.dart 的响应形状
（{"ok":true,"data":{...}} / {"error":"..."} + sb_admin cookie 鉴权）。
运行: python3 -m unittest discover -s skills/sudoboard/tests -v
"""
import argparse
import json
import os
import re
import sys
import tempfile
import threading
import unittest
from http.server import BaseHTTPRequestHandler, HTTPServer

TESTS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(TESTS), "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, TESTS)

import sync  # noqa: E402
from test_bundle import make_project  # noqa: E402

PIN = "123456"
COOKIE = "sb_admin=test-token"


class MockApp:
    """极简 App API：按依赖序记录请求，供断言。"""

    def __init__(self):
        self.reqs = []          # [(method, path, body)]
        self.sources = {}       # id -> payload
        self.templates = {}
        self.dashboards = {}
        self.groups = {}
        self.assets = {}
        self.active = None
        self.seq = 0

    def nid(self, prefix):
        self.seq += 1
        return f"{prefix}{self.seq:04d}"

    def body_for(self, method, path):
        for m, p, b in reversed(self.reqs):
            if m == method and p == path:
                return b
        return None


class Handler(BaseHTTPRequestHandler):
    app: MockApp = None

    def log_message(self, *a):
        pass

    def _read(self):
        n = int(self.headers.get("content-length") or 0)
        return json.loads(self.rfile.read(n) or b"{}") if n else {}

    def _send(self, obj, status=200, cookie=False):
        body = json.dumps(obj, ensure_ascii=False).encode()
        self.send_response(status)
        self.send_header("content-type", "application/json")
        if cookie:
            self.send_header("set-cookie", COOKIE + "; Path=/; Max-Age=1800")
        self.send_header("content-length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _auth(self):
        return COOKIE.split("=", 1)[1] in (self.headers.get("cookie") or "")

    def _handle(self, method):
        app = type(self).app
        p = self.path.split("?")[0]
        body = self._read() if method in ("POST", "PUT") else {}
        app.reqs.append((method, p, body))

        if p == "/api/auth/admin-login":
            if body.get("pin") != PIN:
                return self._send({"error": "invalid_pin"}, 401)
            return self._send({"ok": True, "data": {"scope": "admin"}}, cookie=True)
        if not self._auth():
            return self._send({"error": "unauthorized"}, 401)

        if method == "GET" and p == "/api/assets":
            return self._send({"ok": True, "data": {"assets": list(app.assets.values())}})
        if method == "POST" and p == "/api/assets/upload":
            aid = app.nid("a")
            app.assets[aid] = {"id": aid, "name": body.get("name")}
            return self._send({"ok": True, "data": {"asset": app.assets[aid]}})

        if p == "/api/datasources" and method == "POST":
            sid = app.nid("src")
            app.sources[sid] = body
            return self._send({"ok": True, "data": {"source": {"id": sid, **body}}})
        m = re.fullmatch(r"/api/datasources/(src\d+)", p)
        if m and method == "PUT":
            if m.group(1) not in app.sources:
                return self._send({"error": "not_found"}, 404)
            app.sources[m.group(1)] = body
            return self._send({"ok": True, "data": {"source": {"id": m.group(1), **body}}})
        m = re.fullmatch(r"/api/datasources/(src\d+)/fetch", p)
        if m and method == "POST":
            return self._send({"ok": True, "data": {"sourceId": m.group(1), "ok": True,
                                                    "values": {"v": 1}}})

        if p == "/api/templates" and method == "POST":
            tid = app.nid("tpl")
            app.templates[tid] = body
            return self._send({"ok": True, "data": {"template": {"id": tid, **body}}})
        m = re.fullmatch(r"/api/templates/(tpl\d+)", p)
        if m and method == "PUT":
            if m.group(1) not in app.templates:
                return self._send({"error": "not_found"}, 404)
            app.templates[m.group(1)] = body
            return self._send({"ok": True, "data": {"template": {"id": m.group(1), **body}}})
        if m and method == "DELETE":
            app.templates.pop(m.group(1), None)
            return self._send({"ok": True, "data": {}})

        if p == "/api/dashboards" and method == "POST":
            did = app.nid("dash")
            app.dashboards[did] = body
            return self._send({"ok": True, "data": {"dashboard": {"id": did, **body}}})
        m = re.fullmatch(r"/api/dashboards/(dash\d+)", p)
        if m and method == "PUT":
            if m.group(1) not in app.dashboards:
                return self._send({"error": "not_found"}, 404)
            app.dashboards[m.group(1)] = body
            return self._send({"ok": True, "data": {"dashboard": {"id": m.group(1), **body}}})

        if p == "/api/playback-groups" and method == "POST":
            gid = app.nid("grp")
            app.groups[gid] = body
            return self._send({"ok": True, "data": {"group": {"id": gid, **body}}})
        m = re.fullmatch(r"/api/playback-groups/(grp\d+)", p)
        if m and method == "PUT":
            if m.group(1) not in app.groups:
                return self._send({"error": "not_found"}, 404)
            app.groups[m.group(1)] = body
            return self._send({"ok": True, "data": {"group": {"id": m.group(1), **body}}})
        m = re.fullmatch(r"/api/playback-groups/(grp\d+)/activate", p)
        if m and method == "POST":
            if m.group(1) not in app.groups:
                return self._send({"error": "not_found"}, 404)
            app.active = m.group(1)
            return self._send({"ok": True, "data": {"activeId": m.group(1)}})

        if p == "/api/play/active":
            dashes = []
            if app.active:
                for d in app.groups[app.active].get("dashboards", []):
                    dashes.append({"id": d["dashboardId"], "name": "mock"})
            return self._send({"ok": True, "data": {"group": {"id": app.active},
                                                    "dashboards": dashes, "assetUrls": {}}})
        return self._send({"error": "not_found"}, 404)

    def do_GET(self):
        self._handle("GET")

    def do_POST(self):
        self._handle("POST")

    def do_PUT(self):
        self._handle("PUT")

    def do_DELETE(self):
        self._handle("DELETE")


class SyncTestBase(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sudb-sync-")
        self.proj = make_project(os.path.join(self.tmp, "sudoboard"))
        self.app = MockApp()
        Handler.app = self.app
        self.httpd = HTTPServer(("127.0.0.1", 0), Handler)
        self.url = f"http://127.0.0.1:{self.httpd.server_address[1]}"
        threading.Thread(target=self.httpd.serve_forever, daemon=True).start()

    def tearDown(self):
        self.httpd.shutdown()

    def board(self):
        return json.load(open(os.path.join(self.proj, "board.json"), encoding="utf-8"))

    def write_board(self, b):
        json.dump(b, open(os.path.join(self.proj, "board.json"), "w"),
                  ensure_ascii=False, indent=2)

    def run_sync(self, **kw):
        args = argparse.Namespace(dir=self.proj, url=self.url, pin=PIN, dry_run=False,
                                  no_activate=False, force=False, command=None)
        for k, v in kw.items():
            setattr(args, k, v)
        sync.do_sync(args)

    def counts(self, method, path):
        return sum(1 for m, p, _ in self.app.reqs if m == method and p == path)


class DryRunTest(SyncTestBase):
    def test_dry_run_without_pin_prints_plan(self):
        """--dry-run 不连设备，不应强制要 PIN（回归：曾直接报缺 PIN 退出）。"""
        b = self.board()
        b["device"].pop("pin", None)
        self.write_board(b)
        self.run_sync(dry_run=True, pin=None)   # 不应抛异常

    def test_dry_run_makes_no_requests(self):
        self.run_sync(dry_run=True, pin=None)
        self.assertEqual(self.app.reqs, [])


class SingleBoardSyncTest(SyncTestBase):
    def test_full_sync_and_backfill(self):
        self.run_sync()
        b = self.board()
        self.assertTrue(b["sources"][0]["appId"].startswith("src"))
        self.assertTrue(b["template"]["appId"].startswith("tpl"))
        self.assertTrue(b["dashboard"]["appId"].startswith("dash"))
        self.assertTrue(b["playback"]["appId"].startswith("grp"))
        self.assertTrue(b["dashboard"]["background"]["assetAppId"].startswith("a"))
        self.assertEqual(self.counts("POST", f"/api/playback-groups/{b['playback']['appId']}/activate"), 1)

    def test_second_run_is_idempotent(self):
        self.run_sync()
        n_before = (self.counts("POST", "/api/datasources"), self.counts("POST", "/api/templates"),
                    self.counts("POST", "/api/dashboards"), self.counts("POST", "/api/playback-groups"))
        self.run_sync()
        n_after = (self.counts("POST", "/api/datasources"), self.counts("POST", "/api/templates"),
                   self.counts("POST", "/api/dashboards"), self.counts("POST", "/api/playback-groups"))
        self.assertEqual(n_before, n_after, "重复同步不应重复创建资源")
        self.assertEqual(self.counts("PUT", f"/api/templates/{self.board()['template']['appId']}"), 1)

    def test_recreates_when_device_lost_resource(self):
        self.run_sync()
        tid = self.board()["template"]["appId"]
        self.app.templates.pop(tid)
        self.run_sync()
        new_tid = self.board()["template"]["appId"]
        self.assertNotEqual(new_tid, tid)
        self.assertTrue(new_tid.startswith("tpl"))


class MultiDashboardSyncTest(SyncTestBase):
    """多看板：templates/dashboards 数组 + playback.dashboardKeys 引用多个 key。"""

    def setUp(self):
        super().setUp()
        b = self.board()
        os.makedirs(os.path.join(self.proj, "templates"), exist_ok=True)
        open(os.path.join(self.proj, "templates", "two.jsx"), "w").write(
            "/* sb-theme: dark */\nexport default function Screen({ data }) { return null; }")
        b["templates"] = [
            {"key": "t1", "appId": None, "name": "T1", "file": "templates/main.jsx"},
            {"key": "t2", "appId": None, "name": "T2", "file": "templates/two.jsx"},
        ]
        b["dashboards"] = [
            {"key": "one", "appId": None, "name": "D1", "templateKey": "t1",
             "sourceKeys": ["demo"], "refreshSeconds": 60},
            {"key": "main", "appId": None, "name": "D2", "templateKey": "t2",
             "sourceKeys": ["demo"], "refreshSeconds": 60},
        ]
        b["playback"]["dashboardKeys"] = ["one", "main"]
        b.pop("template", None)
        b.pop("dashboard", None)
        self.write_board(b)

    def test_syncs_all_templates_and_dashboards(self):
        self.run_sync()
        b = self.board()
        self.assertEqual(len(b["templates"]), 2)
        self.assertEqual(len(b["dashboards"]), 2)
        for t in b["templates"]:
            self.assertTrue(t["appId"].startswith("tpl"), t)
        for d in b["dashboards"]:
            self.assertTrue(d["appId"].startswith("dash"), d)
        self.assertEqual(self.counts("POST", "/api/templates"), 2)
        self.assertEqual(self.counts("POST", "/api/dashboards"), 2)

    def test_playback_group_contains_both_screens(self):
        self.run_sync()
        gid = self.board()["playback"]["appId"]
        payload = self.app.groups[gid]
        self.assertEqual(len(payload["dashboards"]), 2)
        ids = [d["dashboardId"] for d in payload["dashboards"]]
        self.assertEqual(len(set(ids)), 2)

    def test_multi_is_idempotent(self):
        self.run_sync()
        self.run_sync()
        self.assertEqual(self.counts("POST", "/api/dashboards"), 2)
        first = self.board()["dashboards"][0]["appId"]
        self.assertEqual(self.counts("PUT", f"/api/dashboards/{first}"), 1)


class ThemeWarningTest(SyncTestBase):
    def test_theme_mismatch_warns_but_syncs(self):
        src = "/* sb-theme: dark */\nexport default function Screen({ data }) { return null; }"
        open(os.path.join(self.proj, "templates", "main.jsx"), "w").write(src)
        b = self.board()
        b["board"]["theme"] = "light"
        self.write_board(b)
        import io
        import contextlib
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            self.run_sync()
        self.assertIn("sb-theme", buf.getvalue())
        self.assertTrue(self.board()["template"]["appId"].startswith("tpl"))


class BlockingCheckTest(SyncTestBase):
    def test_import_is_rejected(self):
        open(os.path.join(self.proj, "templates", "main.jsx"), "w").write(
            "import React from 'react';\nexport default function Screen() { return null; }")
        with self.assertRaises(sync.SyncError):
            self.run_sync()


if __name__ == "__main__":
    unittest.main()
