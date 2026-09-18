"""模板契约共享校验（TDD）：深浅色判定 + 静态阻断项 + 观感警告。

契约（App web/src/lib/boardTone.ts 与本模块必须一致）：
  优先级：模板源码显式声明 `/* sb-theme: dark|light */` > 旧的颜色启发式 > 兜底主题。
运行: python3 -m unittest discover -s skills/sudoboard/tests -v
"""
import os
import sys
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

import template_checks as tc  # noqa: E402


class DeclaredThemeTest(unittest.TestCase):
    def test_declaration_forms(self):
        for src, want in [
            ("/* sb-theme: dark */\nexport default function Screen(){}", "dark"),
            ("/* sb-theme: light */\nexport default function Screen(){}", "light"),
            ("/* SB-THEME:DARK */\nexport default function Screen(){}", "dark"),
            ("/*   sb-theme  :  light   */\nexport default function Screen(){}", "light"),
            ("// sb-theme: light\nexport default function Screen(){}", "light"),
        ]:
            self.assertEqual(tc.declared_theme(src), want, src)

    def test_no_declaration(self):
        self.assertIsNone(tc.declared_theme("export default function Screen(){}"))
        self.assertIsNone(tc.declared_theme(""))
        self.assertIsNone(tc.declared_theme(None))
        # 非法值不算声明
        self.assertIsNone(tc.declared_theme("/* sb-theme: blue */"))


class ResolveThemeTest(unittest.TestCase):
    def test_declared_wins_over_heuristic(self):
        src = "/* sb-theme: dark */\nexport default function Screen(){return <div style={{color:'#fff'}}/>;}"
        self.assertEqual(tc.resolve_theme(src, "dark"), ("dark", "declared"))
        # 声明与 board.theme 冲突时，仍以声明为准（由 style_warnings 负责提醒）
        self.assertEqual(tc.resolve_theme(src, "light"), ("dark", "declared"))

    def test_heuristic_fallback(self):
        light = "export default function Screen(){return <div style={{background:'rgba(255,255,255,0.9)'}}/>;}"
        dark = "export default function Screen(){return <div style={{background:'#0b0e13'}}/>;}"
        self.assertEqual(tc.resolve_theme(light, "dark"), ("light", "heuristic"))
        self.assertEqual(tc.resolve_theme(dark, "light"), ("dark", "heuristic"))

    def test_empty_source_uses_fallback(self):
        self.assertEqual(tc.resolve_theme("", "light"), ("light", "fallback"))
        self.assertEqual(tc.resolve_theme(None, "dark"), ("dark", "fallback"))
        self.assertEqual(tc.resolve_theme(None), ("dark", "fallback"))

    def test_red_and_yellow_hex_are_not_light_hints(self):
        """回归：#f87171（红）/#F6E500（黄）曾把深色模板误判为浅色（内置模板库 7/8 中招）。"""
        for src in (
            "export default function Screen(){return <div style={{color:'#f87171',background:'#0b0e13'}}/>;}",
            "export default function Screen(){return <div style={{color:'#F6E500',background:'#0b0e13'}}/>;}",
            # 深色模板常见的半透明白描边也不该判成浅色
            "export default function Screen(){return <div style={{border:'1px solid rgba(255,255,255,0.08)'}}/>;}",
            # 近白「文字色」是深色模板最常见的写法，不能当浅色底
            "export default function Screen(){return <div style={{color:'#e8eaf0',background:'#0f1218'}}/>;}",
            "export default function Screen(){return <div style={{color:'#e5e7eb'}}/>;}",
            "export default function Screen(){return <div style={{color:'#cfd6e0'}}/>;}",
        ):
            self.assertEqual(tc.heuristic_theme(src), "dark", src)

    def test_true_light_hints_still_detected(self):
        for src in (
            "export default function Screen(){return <div style={{background:'#fff'}}/>;}",
            "export default function Screen(){return <div style={{background:'#ffffff'}}/>;}",
            "export default function Screen(){return <div style={{background:'#f5f6f8'}}/>;}",
            "export default function Screen(){return <div style={{background:'#FAFAFA'}}/>;}",
            "export default function Screen(){return <div style={{background:'#f0f0f0'}}/>;}",
            "export default function Screen(){return <div style={{background:'#fefefe'}}/>;}",
            "export default function Screen(){return <div style={{background:'rgba(255, 255, 255, 0.92)'}}/>;}",
            "export default function Screen(){return <div style={{background:'rgba(255,255,255,0.6)'}}/>;}",
        ):
            self.assertEqual(tc.heuristic_theme(src), "light", src)


class StaticChecksTest(unittest.TestCase):
    def test_ok_template(self):
        src = "export default function Screen({ data }) { return null; }"
        self.assertEqual(tc.static_checks(src), [])

    def test_blocking_rules(self):
        cases = {
            "import React from 'react';": "import",
            "const x = require('y');": "require",
            "fetch('http://x');": "fetch",
            "new XMLHttpRequest();": "XMLHttpRequest",
            "const a = 1;": "export default",
        }
        for src, needle in cases.items():
            bad = tc.static_checks(src)
            self.assertTrue(any(needle in b for b in bad), f"{src!r} → {bad}")

    def test_size_limit(self):
        src = "export default function Screen(){}" + " " * (200 * 1024)
        self.assertTrue(any("200KB" in b for b in tc.static_checks(src)))


class StyleWarningsTest(unittest.TestCase):
    def test_theme_mismatch_warns(self):
        src = "/* sb-theme: dark */\nexport default function Screen(){return null;}"
        warns = tc.style_warnings(src, board_theme="light")
        self.assertTrue(any("深浅" in w or "theme" in w for w in warns), warns)
        self.assertEqual(tc.style_warnings(src, board_theme="dark"), [])

    def test_heuristic_mismatch_warns(self):
        src = "export default function Screen(){return <div style={{color:'#fff'}}/>;}"
        warns = tc.style_warnings(src, board_theme="dark")
        self.assertTrue(any("sb-theme" in w for w in warns), warns)

    def test_rounded_corner_and_tailwind_warn(self):
        src = ("export default function Screen(){return <div className='p-4' "
               "style={{borderRadius: 8}}/>;}")
        warns = "\n".join(tc.style_warnings(src, board_theme=None))
        self.assertIn("border-radius", warns.lower())
        self.assertIn("tailwind", warns.lower())

    def test_clean_template_no_warning(self):
        src = ("/* sb-theme: dark */\nexport default function Screen(){return "
               "<div style={{background:'#0b0e13'}}/>;}")
        self.assertEqual(tc.style_warnings(src, board_theme="dark"), [])


class ExampleTemplatesTest(unittest.TestCase):
    """示例骨架必须自己遵守契约（防文档与示例漂移）。"""

    def test_examples_declare_theme_and_pass_checks(self):
        import glob
        examples = os.path.join(os.path.dirname(SCRIPTS), "examples", "*.jsx")
        files = sorted(glob.glob(examples))
        self.assertTrue(files, "examples/ 下应有骨架模板")
        for path in files:
            name = os.path.basename(path)
            with open(path, encoding="utf-8") as f:
                src = f.read()
            self.assertEqual(tc.static_checks(src), [], name)
            tone = tc.declared_theme(src)
            self.assertIn(tone, ("dark", "light"), f"{name} 必须显式声明 sb-theme")
            if "dark" in name:
                self.assertEqual(tone, "dark", name)
            if "light" in name:
                self.assertEqual(tone, "light", name)
            # 声明优先，且与颜色启发式不矛盾
            self.assertEqual(tc.resolve_theme(src)[0], tone, name)


if __name__ == "__main__":
    unittest.main()
