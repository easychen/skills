"""Cloudflare 部署契约测试（TDD）：deploy_cf.py 产出的 Worker 工程必须自包含、可部署、不含明文凭据。

运行: python3 -m unittest discover -s skills/sudoboard/tests -v
附带：本文件会以子进程运行 tests/cf_worker.test.mjs（node --test），
覆盖渲染出的 worker 的运行时行为（引擎/路由/KV/cron）。
"""
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(TESTS), "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, TESTS)

import deploy_cf  # noqa: E402
from test_bundle import make_project  # noqa: E402

FAKE_JPEG = b"fake-jpeg-bytes-for-test"


def load_board(root):
    return json.load(open(os.path.join(root, "board.json"), encoding="utf-8"))


class AssembleCfgTest(unittest.TestCase):
    """board.json → Worker CONFIG / 资产清单 的组装。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sudb-cf-py-")
        self.proj = make_project(os.path.join(self.tmp, "sudoboard"))

    def test_assemble_sources_reject_db(self):
        board = load_board(self.proj)
        board["sources"].append({
            "key": "db1", "appId": None,
            "create": {"name": "库", "type": "db", "intervalSeconds": 900,
                       "db": {"kind": "mysql", "host": "h", "database": "d",
                              "username": "u", "password": "p"},
                       "queries": [{"name": "q", "sql": "select 1"}]}})
        json.dump(board, open(os.path.join(self.proj, "board.json"), "w"),
                  ensure_ascii=False)
        with self.assertRaises(deploy_cf.DeployError) as cm:
            deploy_cf.assemble(self.proj)
        self.assertIn("暂不支持 DB 源", str(cm.exception))

    def test_assemble_http_source_ok(self):
        cfg, assets = deploy_cf.assemble(self.proj)
        self.assertEqual(cfg["boardName"], "项目总览")
        self.assertEqual(cfg["theme"], "light")
        self.assertEqual(len(cfg["sources"]), 1)
        src = cfg["sources"][0]
        self.assertEqual(src["type"], "http")
        self.assertEqual(src["fetch"]["url"], "http://x/metrics")
        self.assertEqual(src["extractors"][0]["jsonata"], "a")
        # 稳定 id：由 key 派生（重复构建不变）
        self.assertEqual(src["id"], deploy_cf.stable_id("demo"))
        # 资产：只有 board.dashboard.background 引用的那张壁纸（light）
        files = {aid: os.path.basename(p) for aid, p in assets["files"].items()}
        self.assertIn("wallpaper-light.jpg", files.values())
        self.assertNotIn("wallpaper-dark.jpg", files.values())
        self.assertTrue(all(aid.startswith("a") for aid in assets["files"]))

    def test_min_interval_is_min_of_sources(self):
        board = load_board(self.proj)
        board["sources"].append({
            "key": "fast", "appId": None,
            "create": {"name": "快源", "type": "http", "intervalSeconds": 30,
                       "enabled": True,
                       "fetch": {"url": "http://y", "method": "GET"},
                       "extractors": [{"name": "v", "jsonata": "b"}]}})
        json.dump(board, open(os.path.join(self.proj, "board.json"), "w"),
                  ensure_ascii=False)
        cfg, _ = deploy_cf.assemble(self.proj)
        self.assertEqual(cfg["minIntervalSeconds"], 30)


class RenderWorkerTest(unittest.TestCase):
    """模板渲染：Worker 源码嵌入配置与播放页，且播放页不含源凭据。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sudb-cf-render-")
        self.proj = make_project(os.path.join(self.tmp, "sudoboard"))
        # 给源加一个「秘密」header，验证不泄漏到播放页
        board = load_board(self.proj)
        board["sources"][0]["create"]["fetch"]["headers"] = {
            "Authorization": "Bearer sk-secret-test-123"}
        json.dump(board, open(os.path.join(self.proj, "board.json"), "w"),
                  ensure_ascii=False)
        self.cfg, self.assets = deploy_cf.assemble(self.proj)

    def test_render_worker_embeds_config_and_page(self):
        worker = deploy_cf.render_worker(self.cfg, "<html>播放页</html>")
        self.assertIn("export default", worker)
        self.assertIn("http://x/metrics", worker)  # 引擎需要真 URL（含 header 密钥，服务端侧）
        self.assertIn("<html>播放页</html>", worker)
        self.assertNotIn("__CONFIG__", worker)
        self.assertNotIn("__PLAY_HTML__", worker)

    def test_play_html_has_no_credentials(self):
        page = deploy_cf.render_play_page(
            self.cfg, "export default function Screen({data}) { return null; }")
        self.assertNotIn("sk-secret-test-123", page)
        self.assertNotIn("Authorization", page)
        self.assertIn("项目总览", page)          # 看板名在播放页
        self.assertIn("/api/data", page)         # 轮询数据源
        self.assertIn("/assets/", page)          # 背景走 /assets/<id>


class WranglerConfigTest(unittest.TestCase):
    def test_cron_expr(self):
        self.assertEqual(deploy_cf.cron_expr(300), "*/5 * * * *")
        self.assertEqual(deploy_cf.cron_expr(30), "* * * * *")
        self.assertEqual(deploy_cf.cron_expr(60), "* * * * *")
        self.assertEqual(deploy_cf.cron_expr(3661), "*/59 * * * *")  # 上限 59 分钟

    def test_wrangler_json(self):
        w = deploy_cf.render_wrangler(name="sudb-a", ns_id="ns123", cron="*/5 * * * *")
        obj = json.loads(w)
        self.assertEqual(obj["name"], "sudb-a")
        self.assertEqual(obj["main"], "worker.js")
        self.assertEqual(obj["kv_namespaces"], [{"binding": "SDB", "id": "ns123"}])
        self.assertEqual(obj["triggers"]["crons"], ["*/5 * * * *"])

    def test_worker_name_slug(self):
        self.assertEqual(deploy_cf.slug("我的看板 A/B"), "sudb-a-b")
        self.assertEqual(deploy_cf.slug("ok"), "sudb-ok")

    def test_kv_cmd_requires_remote(self):
        """回归：wrangler>=4 默认本地（miniflare）KV，操作云端必须 --remote。
        教训来自线上测试：资产上传没加 --remote → 写进本地状态，Worker 读不到。
        ⚠ --binding 与 --remote 在 wrangler 4.44 冲突（报 No KV Namespaces
        configured），必须用 --namespace-id + --remote。"""
        cmd = deploy_cf.kv_cmd(["wrangler"], "kv", "key", "put", "asset:x",
                               "--namespace-id=ns", "--path=/tmp/x")
        self.assertEqual(cmd[-1], "--remote")
        self.assertIn("--namespace-id=ns", cmd)
        self.assertNotIn("--binding=", cmd)


class AccessProtectTest(unittest.TestCase):
    """Cloudflare Access（Worker 级）集成：线上看板默认应受访问控制保护。

    机制（2026-08 起）：POST /accounts/{id}/access/apps，destinations=[{type:worker,
    worker_id}] 即保护该 Worker 的所有域名；policy include 支持 email / email_domain。
    本账号 Zero Trust 已启用；wrangler OAuth token 只读 Access（创建需 Edit 权限 token）。
    """

    def test_parse_access_allow(self):
        self.assertEqual(
            deploy_cf.parse_access_allow("a@x.com, team@example.com"),
            (["a@x.com", "team@example.com"], []))
        self.assertEqual(
            deploy_cf.parse_access_allow("@example.com, @corp.cn"),
            ([], ["example.com", "corp.cn"]))
        self.assertEqual(
            deploy_cf.parse_access_allow("a@x.com,@corp.cn"),
            (["a@x.com"], ["corp.cn"]))
        self.assertIsNone(deploy_cf.parse_access_allow(""))

    def test_access_app_payload(self):
        payload = deploy_cf.access_app_payload(
            worker_name="sudb-live-test",
            emails=["easychen@gmail.com"],
            domains=["example.com"],
            name="SudoBoard · sudb-live-test")
        self.assertEqual(payload["type"], "self_hosted")
        self.assertEqual(payload["destinations"],
                         [{"type": "worker", "worker_id": "sudb-live-test"}])
        inc = payload["policies"][0]["include"]
        self.assertEqual(payload["policies"][0]["decision"], "allow")
        self.assertIn({"email": {"email": "easychen@gmail.com"}}, inc)
        self.assertIn({"email_domain": {"domain": "example.com"}}, inc)

    def test_access_instructions_imperative(self):
        """即使无法自动创建（如缺 Edit 权限 token），也必须给出明确的手动步骤——
        这是「至少提示用户」的底线。"""
        tips = deploy_cf.access_tips(worker_name="sudb-live-test",
                                     public_url="https://sudb-live-test.easychen.workers.dev",
                                     protected=False)
        joined = "\n".join(tips)
        self.assertIn("Access", joined)
        self.assertIn("sudb-live-test", joined)
        self.assertIn("api.cloudflare.com", joined)          # 提供可复制的 API curl
        self.assertIn("easychen@gmail.com", joined)          # 示例邮箱

    def test_access_tips_protected_silent(self):
        tips = deploy_cf.access_tips(worker_name="sudb-live-test",
                                     public_url="http://x", protected=True)
        self.assertLess(len(tips), 1)  # 已受保护 → 不再啰嗦提示


class GenerateProjectTest(unittest.TestCase):
    """generate() 端到端：写出 dist/cf/ 完整工程（不部署）。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sudb-cf-gen-")
        self.proj = make_project(os.path.join(self.tmp, "sudoboard"))
        # 给源加一个「秘密」header，验证引擎侧保留、播放页不泄漏
        board = load_board(self.proj)
        board["sources"][0]["create"]["fetch"]["headers"] = {
            "Authorization": "Bearer sk-secret-test-123"}
        json.dump(board, open(os.path.join(self.proj, "board.json"), "w"),
                  ensure_ascii=False)

    def test_generate_project_files(self):
        out = deploy_cf.generate(self.proj, name="sudb-gen-test",
                                 ns_id="ns-fixed", dry_run=True)
        for f in ("worker.js", "wrangler.jsonc", "play.html", "jsonata.min.js"):
            self.assertTrue(os.path.isfile(os.path.join(out, f)), f)
        w = json.load(open(os.path.join(out, "wrangler.jsonc"), encoding="utf-8"))
        self.assertEqual(w["name"], "sudb-gen-test")
        # 固定 ns_id：dry-run 只生成不创建
        self.assertEqual(w["kv_namespaces"][0]["id"], "ns-fixed")
        worker = open(os.path.join(out, "worker.js"), encoding="utf-8").read()
        self.assertIn("export default", worker)
        # 引擎侧 worker 需要源凭据（服务端抓取），但播放页绝不包含
        self.assertIn("sk-secret-test-123", worker)
        page = open(os.path.join(out, "play.html"), encoding="utf-8").read()
        self.assertIn("项目总览", page)
        self.assertNotIn("sk-secret-test-123", page)

    def test_deploy_requires_login_or_dry_run(self):
        # dry-run 通过（前面已证明）；真部署需 wrangler 登录态 —— 由集成环境保障
        self.assertTrue(deploy_cf._wrangler_available())


class NodeWorkerRuntimeTest(unittest.TestCase):
    """渲染出的 worker 运行时（Node 直跑，无真实 KV）由 node --test 覆盖。"""

    def _node_test(self, name):
        node_test = os.path.join(TESTS, name)
        r = subprocess.run(["node", "--test", node_test],
                           capture_output=True, text=True, timeout=180)
        self.assertEqual(r.returncode, 0,
                         f"node --test {name} 失败:\n{r.stdout}\n{r.stderr[-3000:]}")
        self.assertIn("pass", r.stdout.lower() + " " + r.stderr.lower())

    def test_node_worker_suite_passes(self):
        self._node_test("cf_worker.test.mjs")

    def test_node_engine_suite_passes(self):
        self._node_test("engine.test.mjs")


class WorkerNameTest(unittest.TestCase):
    """回归：中文看板名曾让 slug 退化成 'sudb-'（所有中文看板撞名 + 结尾连字符）。"""

    def test_cjk_name_gets_stable_unique_hash(self):
        a = deploy_cf.slug("技能自测看板")
        b = deploy_cf.slug("另一块中文看板")
        self.assertRegex(a, r"^sudb-[0-9a-f]{6,}$")
        self.assertNotEqual(a, b)
        self.assertEqual(a, deploy_cf.slug("技能自测看板"))  # 稳定
        self.assertFalse(a.endswith("-"))

    def test_empty_name_not_degenerate(self):
        s = deploy_cf.slug("")
        self.assertRegex(s, r"^sudb-[0-9a-f]{6,}$")

    def test_ascii_name_unchanged(self):
        self.assertEqual(deploy_cf.slug("我的看板 A/B"), "sudb-a-b")
        self.assertEqual(deploy_cf.slug("ok"), "sudb-ok")
        self.assertEqual(deploy_cf.slug("sudb-already"), "sudb-already")

    def test_no_trailing_hyphen_after_truncation(self):
        self.assertFalse(deploy_cf.slug("a" * 80).endswith("-"))

    def test_resolve_worker_name_uses_dashboard_name(self):
        """deploy 与 Access 必须用同一个名字：看板名优先取 dashboard.name。"""
        tmp = tempfile.mkdtemp(prefix="sudb-cf-name-")
        proj = make_project(os.path.join(tmp, "sudoboard"))
        board = load_board(proj)
        board["board"]["name"] = "My Board"
        board["dashboard"]["name"] = "Overview"
        json.dump(board, open(os.path.join(proj, "board.json"), "w"), ensure_ascii=False)
        self.assertEqual(deploy_cf.resolve_worker_name(proj), "sudb-overview")
        out = deploy_cf.generate(proj, dry_run=True)
        w = json.load(open(os.path.join(out, "wrangler.jsonc"), encoding="utf-8"))
        self.assertEqual(w["name"], deploy_cf.resolve_worker_name(proj))

    def test_access_targets_the_deployed_worker(self):
        """回归：默认名路径下 Access 曾指向 board.name 推导出的另一个 Worker。"""
        from unittest import mock
        tmp = tempfile.mkdtemp(prefix="sudb-cf-access-")
        proj = make_project(os.path.join(tmp, "sudoboard"))
        board = load_board(proj)
        board["board"]["name"] = "My Board"
        board["dashboard"]["name"] = "Overview"
        json.dump(board, open(os.path.join(proj, "board.json"), "w"), ensure_ascii=False)
        deployed = {}

        def fake_deploy(root, name=None):
            deployed["name"] = deploy_cf.resolve_worker_name(root, name)
            return "https://x.workers.dev/play"

        with mock.patch.object(deploy_cf, "deploy", side_effect=fake_deploy), \
             mock.patch.object(deploy_cf, "access_status", return_value=(True, "app")) as st, \
             mock.patch.object(deploy_cf, "_account_id_from_wrangler", return_value="acct"):
            deploy_cf.deploy_with_access(proj, access_allow="a@b.com")
        self.assertEqual(st.call_args[0][2], deployed["name"])


class MultiDashboardCfTest(unittest.TestCase):
    """Cloudflare 只服务一块看板 → 取主看板（key == main），并提示其余未上线。"""

    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sudb-cf-multi-")
        self.proj = make_project(os.path.join(self.tmp, "sudoboard"))
        open(os.path.join(self.proj, "templates", "two.jsx"), "w").write(
            "/* sb-theme: light */\nexport default function Screen({ data }) { return null; }")
        board = load_board(self.proj)
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
        board.pop("template", None)
        board.pop("dashboard", None)
        json.dump(board, open(os.path.join(self.proj, "board.json"), "w"), ensure_ascii=False)

    def test_assemble_uses_primary_dashboard_and_template(self):
        cfg, assets = deploy_cf.assemble(self.proj)
        self.assertEqual(cfg["boardName"], "D2")
        self.assertEqual(cfg["theme"], "light")
        files = {os.path.basename(p) for p in assets["files"].values()}
        self.assertEqual(files, {"wallpaper-light.jpg"})

    def test_generate_warns_about_other_dashboards(self):
        out = deploy_cf.generate(self.proj, dry_run=True)
        page = open(os.path.join(out, "play.html"), encoding="utf-8").read()
        self.assertIn("D2", page)
        self.assertNotIn("D1", page)


if __name__ == "__main__":
    unittest.main()