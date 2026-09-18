"""install-skill.sh 契约测试（TDD）：技能能被装进宿主技能目录，且可干净卸载。

运行: python3 -m unittest discover -s skills/sudoboard/tests -v
"""
import os
import subprocess
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
SKILL = os.path.dirname(HERE)
INSTALL = os.path.join(SKILL, "scripts", "install-skill.sh")


class InstallSkillTest(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="sudb-install-")
        self.dest_root = os.path.join(self.tmp, "skills")

    def run_install(self, *args):
        return subprocess.run(["bash", INSTALL, "--dir", self.dest_root, *args],
                              capture_output=True, text=True, timeout=60)

    def test_copy_install_is_complete(self):
        r = self.run_install("--copy")
        self.assertEqual(r.returncode, 0, r.stderr)
        dest = os.path.join(self.dest_root, "sudoboard")
        for rel in ("SKILL.md", "scripts/build_preview.py", "scripts/template_checks.py",
                    "scripts/board_model.py", "examples/kpi-dark.jsx", "references/api.md"):
            self.assertTrue(os.path.exists(os.path.join(dest, rel)), rel)

    def test_link_install_and_uninstall(self):
        r = self.run_install()
        self.assertEqual(r.returncode, 0, r.stderr)
        dest = os.path.join(self.dest_root, "sudoboard")
        self.assertTrue(os.path.islink(dest))
        self.assertEqual(os.path.realpath(dest), os.path.realpath(SKILL))
        r2 = self.run_install("--uninstall")
        self.assertEqual(r2.returncode, 0, r2.stderr)
        self.assertFalse(os.path.exists(dest) or os.path.islink(dest))

    def test_does_not_clobber_foreign_dir(self):
        os.makedirs(os.path.join(self.dest_root, "sudoboard"))
        r = self.run_install("--copy")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("已存在", r.stderr)


if __name__ == "__main__":
    unittest.main()
