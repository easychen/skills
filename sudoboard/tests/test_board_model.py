"""board.json 模型归一化（TDD）：单看板简写 与 多元素数组 两种写法必须等价可用。

契约：
- `template`/`dashboard`（对象）是单看板简写；`templates`/`dashboards`（数组）是完整写法；
- 两者同时存在时数组优先（简写被忽略）；
- 主看板：key == "main" 的那个，否则第一个；
- 主模板：主看板的 templateKey 指向的那个，否则 key == "main"，否则第一个。
运行: python3 -m unittest discover -s skills/sudoboard/tests -v
"""
import os
import sys
import unittest

SCRIPTS = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "scripts")
sys.path.insert(0, SCRIPTS)

import board_model as bm  # noqa: E402


def single():
    return {
        "board": {"name": "单看板", "theme": "dark"},
        "sources": [{"key": "s1"}],
        "template": {"key": "main", "name": "T1", "file": "templates/main.jsx"},
        "dashboard": {"key": "main", "name": "D1", "templateKey": "main", "sourceKeys": ["s1"]},
        "playback": {"key": "main", "dashboardKeys": ["main"]},
    }


def multi():
    return {
        "board": {"name": "多看板", "theme": "dark"},
        "sources": [{"key": "s1"}, {"key": "s2"}],
        "templates": [
            {"key": "t1", "name": "T1", "file": "templates/one.jsx"},
            {"key": "t2", "name": "T2", "file": "templates/two.jsx"},
        ],
        "dashboards": [
            {"key": "one", "name": "D1", "templateKey": "t1", "sourceKeys": ["s1"]},
            {"key": "main", "name": "D2", "templateKey": "t2", "sourceKeys": ["s2"]},
        ],
        "playback": {"key": "main", "dashboardKeys": ["one", "main"]},
    }


class TemplatesDashboardsTest(unittest.TestCase):
    def test_single_shorthand(self):
        b = single()
        self.assertEqual([t["name"] for t in bm.templates_of(b)], ["T1"])
        self.assertEqual([d["name"] for d in bm.dashboards_of(b)], ["D1"])

    def test_array_form(self):
        b = multi()
        self.assertEqual([t["name"] for t in bm.templates_of(b)], ["T1", "T2"])
        self.assertEqual([d["name"] for d in bm.dashboards_of(b)], ["D1", "D2"])

    def test_array_wins_over_shorthand(self):
        b = multi()
        b["template"] = {"key": "legacy", "name": "Legacy", "file": "templates/legacy.jsx"}
        b["dashboard"] = {"key": "legacy", "name": "LegacyD"}
        self.assertEqual([t["name"] for t in bm.templates_of(b)], ["T1", "T2"])
        self.assertEqual([d["name"] for d in bm.dashboards_of(b)], ["D1", "D2"])

    def test_empty(self):
        self.assertEqual(bm.templates_of({}), [])
        self.assertEqual(bm.dashboards_of({}), [])
        self.assertIsNone(bm.primary_dashboard({}))


class PrimaryTest(unittest.TestCase):
    def test_primary_dashboard_prefers_main_key(self):
        self.assertEqual(bm.primary_dashboard(multi())["name"], "D2")
        b = multi()
        b["dashboards"][1]["key"] = "other"
        self.assertEqual(bm.primary_dashboard(b)["name"], "D1")  # 无 main → 第一个

    def test_primary_template_follows_dashboard_template_key(self):
        b = multi()
        self.assertEqual(bm.primary_template(b)["name"], "T2")
        b["dashboards"][1]["templateKey"] = "t1"
        self.assertEqual(bm.primary_template(b)["name"], "T1")

    def test_primary_template_falls_back_to_main_then_first(self):
        b = multi()
        for d in b["dashboards"]:
            d.pop("templateKey", None)
        b["templates"][0]["key"] = "other"
        b["templates"][1]["key"] = "main"
        self.assertEqual(bm.primary_template(b)["name"], "T2")  # key == main
        b["templates"][1]["key"] = "other2"
        self.assertEqual(bm.primary_template(b)["name"], "T1")  # 第一个

    def test_playback_dashboard_keys(self):
        self.assertEqual(bm.playback_dashboard_keys(multi()), ["one", "main"])
        self.assertEqual(bm.playback_dashboard_keys(single()), ["main"])
        self.assertEqual(bm.playback_dashboard_keys({}), [])

    def test_dashboard_by_key(self):
        b = multi()
        self.assertEqual(bm.dashboard_by_key(b, "one")["name"], "D1")
        self.assertIsNone(bm.dashboard_by_key(b, "nope"))
        self.assertIsNone(bm.dashboard_by_key(b, None))


if __name__ == "__main__":
    unittest.main()
