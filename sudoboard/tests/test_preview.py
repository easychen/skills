"""build_preview.py 契约测试（TDD）：深浅色解析、CDN 版本、渲染期错误兜底、多看板主看板选择。

运行: python3 -m unittest discover -s skills/sudoboard/tests -v
"""
import contextlib
import io
import json
import os
import re
import sys
import tempfile
import unittest

TESTS = os.path.dirname(os.path.abspath(__file__))
SCRIPTS = os.path.join(os.path.dirname(TESTS), "scripts")
sys.path.insert(0, SCRIPTS)
sys.path.insert(0, TESTS)

import build_preview as bp  # noqa: E402
from test_bundle import make_project  # noqa: E402


class CdnVersionTest(unittest.TestCase):
    def test_react_matches_app_major(self):
        """回归：预览曾用 react@18，而 App 打包的是 React 19.2.8。"""
        paths = dict(bp.CDN_PACKAGES)
        self.assertTrue(paths["react"].startswith("react@19"), paths["react"])
        self.assertTrue(paths["react-dom"].startswith("react-dom@19"), paths["react-dom"])
        self.assertIn("echarts@6", paths["echarts"])


class ErrorBoundaryTest(unittest.TestCase):
    def test_page_has_render_error_boundary(self):
        html = bp.render_page_html(
            "B", "export default function Screen(){return null;}",
            {"values": {}, "meta": {}}, "dark", False,
            {"src": "", "dark": "", "light": "", "opacity": 1.0, "blur": 0},
            bp.CDN_PACKAGES, live=None)
        self.assertIn("SBErrorBoundary", html)
        self.assertIn("componentDidCatch", html)
        # 边界必须包住模板组件
        self.assertIn("React.createElement(SBErrorBoundary", html)


class BuildTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sudb-preview-")
        self.proj = make_project(os.path.join(self.tmp, "sudoboard"))

    def write_template(self, src):
        with open(os.path.join(self.proj, "templates", "main.jsx"), "w") as f:
            f.write(src)

    def build(self):
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            info = bp.build(self.proj)
        return info, buf.getvalue()

    def test_declared_theme_wins_over_colors(self):
        self.write_template("/* sb-theme: dark */\nexport default function Screen(){"
                            "return <div style={{color:'#fff'}}/>;}")
        info, out = self.build()
        self.assertEqual(info["tone"], "dark")
        self.assertEqual(info["origin"], "declared")
        html = open(info["out"], encoding="utf-8").read()
        self.assertIn("isLight: false", html)

    def test_light_declaration_overrides_dark_colors(self):
        self.write_template("/* sb-theme: light */\nexport default function Screen(){"
                            "return <div style={{background:'#0b0e13'}}/>;}")
        info, _ = self.build()
        self.assertEqual(info["tone"], "light")
        html = open(info["out"], encoding="utf-8").read()
        self.assertIn("isLight: true", html)

    def test_mismatch_with_board_theme_warns(self):
        self.write_template("/* sb-theme: dark */\nexport default function Screen(){return null;}")
        board = json.load(open(os.path.join(self.proj, "board.json"), encoding="utf-8"))
        board["board"]["theme"] = "light"
        json.dump(board, open(os.path.join(self.proj, "board.json"), "w"), ensure_ascii=False)
        info, out = self.build()
        self.assertTrue(any("sb-theme" in w for w in info["warnings"]), info["warnings"])
        self.assertIn("sb-theme", out)

    def test_rounded_corner_warns(self):
        self.write_template("/* sb-theme: dark */\nexport default function Screen(){"
                            "return <div style={{borderRadius: 8}}/>;}")
        info, _ = self.build()
        self.assertTrue(any("border-radius" in w.lower() for w in info["warnings"]),
                        info["warnings"])

    def test_multi_dashboard_uses_primary(self):
        os.makedirs(os.path.join(self.proj, "templates"), exist_ok=True)
        open(os.path.join(self.proj, "templates", "two.jsx"), "w").write(
            "/* sb-theme: dark */\nexport default function Screen(){return null;}")
        board = json.load(open(os.path.join(self.proj, "board.json"), encoding="utf-8"))
        board["templates"] = [
            {"key": "t1", "name": "T1", "file": "templates/main.jsx"},
            {"key": "t2", "name": "T2", "file": "templates/two.jsx"},
        ]
        board["dashboards"] = [
            {"key": "one", "name": "D1", "templateKey": "t1", "sourceKeys": ["demo"],
             "refreshSeconds": 60},
            {"key": "main", "name": "D2", "templateKey": "t2", "sourceKeys": ["demo"],
             "refreshSeconds": 60},
        ]
        board.pop("template", None)
        board.pop("dashboard", None)
        json.dump(board, open(os.path.join(self.proj, "board.json"), "w"), ensure_ascii=False)
        info, _ = self.build()
        html = open(info["out"], encoding="utf-8").read()
        self.assertIn("D2", html)          # 主看板名进标题栏
        self.assertNotIn("D1", html)


class MissingFileTest(unittest.TestCase):
    def test_missing_template_raises(self):
        tmp = tempfile.mkdtemp(prefix="sudb-preview-miss-")
        proj = make_project(os.path.join(tmp, "sudoboard"))
        os.remove(os.path.join(proj, "templates", "main.jsx"))
        with self.assertRaises(bp.PreviewError):
            bp.build(proj)


if __name__ == "__main__":
    unittest.main()
