"""DocLoom 冒烟测试：覆盖离线可测的核心工具与配置逻辑。

不依赖网络或本地大模型，可直接运行：

    python -m unittest tests.test_smoke      # 或 python -m pytest tests/
"""

import json
import tempfile
import unittest
import zipfile
from pathlib import Path

from docloom.config import (TaskPaths, load_settings, load_task_state,
                           migrate_legacy_keys, save_task_state)
from docloom.doctor import apply_fixes, diagnose
from docloom.refs import resolve_ref_path
from docloom.report import append_chapter_to_report
from docloom.utils import (atomic_write_text, load_json, make_zip, save_json,
                           strip_think)
from docloom.validate import validate_task
from docloom.cli import build_parser

try:
    import fastapi  # noqa: F401
    _HAS_FASTAPI = True
except ImportError:
    _HAS_FASTAPI = False


def _make_task(root: Path) -> TaskPaths:
    """在临时目录里搭一个最小合法任务。"""
    paths = TaskPaths(root)
    paths.ensure_dirs()
    save_json(paths.settings_path, {
        "model": "test-model",
        "api_url": "http://localhost:8000/v1/chat/completions",
        "output_file": "output/Final_Report.md",
        "system_prompt": "你是一个测试助手。",
    })
    save_json(paths.prompts_path, [
        {"chapter": "第一章", "prompt": "写第一章", "ref_files": [], "image_hints": []},
    ])
    return paths


class UtilsTest(unittest.TestCase):
    def test_atomic_write_and_json_roundtrip(self):
        with tempfile.TemporaryDirectory() as tmp:
            target = Path(tmp) / "sub" / "note.txt"
            atomic_write_text(target, "你好\nDocLoom")
            self.assertEqual(target.read_text(encoding="utf-8"), "你好\nDocLoom")
            jp = Path(tmp) / "data.json"
            save_json(jp, {"a": 1, "中文": [1, 2]})
            self.assertEqual(load_json(jp, {}), {"a": 1, "中文": [1, 2]})
            self.assertEqual(load_json(Path(tmp) / "missing.json", {"d": 9}), {"d": 9})

    def test_strip_think(self):
        self.assertEqual(strip_think("<think>推理</think>正文"), "正文")
        self.assertEqual(strip_think("没有思维链"), "没有思维链")

    def test_make_zip(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = Path(tmp) / "a.txt"
            src.write_text("hi", encoding="utf-8")
            out = Path(tmp) / "pack.zip"
            ok = make_zip(out, {"output/a.txt": src}, log=lambda *a: None)
            self.assertTrue(ok)
            with zipfile.ZipFile(out) as zf:
                self.assertIn("output/a.txt", zf.namelist())


class ConfigTest(unittest.TestCase):
    def test_migrate_legacy_keys(self):
        migrated = migrate_legacy_keys({"state_chain_depth": 5})
        self.assertEqual(migrated["state_chain_limit"], 5)
        # 新字段已存在时不覆盖
        kept = migrate_legacy_keys({"state_chain_depth": 5, "state_chain_limit": 2})
        self.assertEqual(kept["state_chain_limit"], 2)

    def test_load_settings_fills_defaults(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_task(Path(tmp))
            settings = load_settings(paths)
            self.assertEqual(settings["model"], "test-model")
            # 默认字段被补齐
            self.assertIn("temperature", settings)
            self.assertIn("state_chain_limit", settings)


class RefsSafetyTest(unittest.TestCase):
    def test_resolve_ref_path_blocks_traversal(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_task(Path(tmp))
            (paths.processed_dir / "notes.txt").write_text("素材", encoding="utf-8")
            # 正常解析
            self.assertIsNotNone(resolve_ref_path(paths, "notes.txt"))
            self.assertIsNotNone(resolve_ref_path(paths, "processed/notes.txt"))
            # 路径穿越 / 绝对路径一律拒绝
            self.assertIsNone(resolve_ref_path(paths, "../secret.txt"))
            self.assertIsNone(resolve_ref_path(paths, "../../etc/passwd"))
            self.assertIsNone(resolve_ref_path(paths, str(Path(tmp) / "notes.txt")))
            # 不存在的文件
            self.assertIsNone(resolve_ref_path(paths, "nope.txt"))


class ValidateTest(unittest.TestCase):
    def test_valid_task_passes(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_task(Path(tmp))
            errors, _ = validate_task(paths)
            self.assertEqual(errors, [])

    def test_missing_prompt_reports_error(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_task(Path(tmp))
            save_json(paths.prompts_path, [{"chapter": "无正文"}])
            errors, _ = validate_task(paths)
            self.assertTrue(any("prompt" in e for e in errors))

    def test_duplicate_chapter_titles_reported(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = _make_task(Path(tmp))
            save_json(paths.prompts_path, [
                {"chapter": "同名", "prompt": "a"},
                {"chapter": "同名", "prompt": "b"},
            ])
            errors, _ = validate_task(paths)
            self.assertTrue(any("重复" in e for e in errors))


class CliTest(unittest.TestCase):
    def test_parser_builds_and_has_version(self):
        parser = build_parser()
        with self.assertRaises(SystemExit) as ctx:
            parser.parse_args(["--version"])
        self.assertEqual(ctx.exception.code, 0)


class DoctorTest(unittest.TestCase):
    def _setup_drift(self, tmp: Path) -> TaskPaths:
        """两章任务，state_chain 开启：
        第 1 章有正文但缺状态链缓存；第 2 章 completed 却无正文。"""
        paths = _make_task(Path(tmp))
        save_json(paths.settings_path, {
            "model": "test-model",
            "api_url": "http://localhost:8000/v1/chat/completions",
            "output_file": "output/Final_Report.md",
            "state_chain": True,
        })
        save_json(paths.prompts_path, [
            {"chapter": "第一章", "prompt": "a", "ref_files": [], "image_hints": []},
            {"chapter": "第二章", "prompt": "b", "ref_files": [], "image_hints": []},
        ])
        settings = load_settings(paths)
        append_chapter_to_report(paths.output_path(settings), "第一章", "第一章的正文内容。")
        save_task_state(paths, {"0": "completed", "1": "completed"})
        return paths

    def test_diagnose_flags_both_drifts(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._setup_drift(Path(tmp))
            diags = diagnose(paths)
            self.assertTrue(diags[0].rebuild_cache)      # 有正文缺缓存
            self.assertIsNone(diags[0].fix_state)
            self.assertEqual(diags[1].fix_state, "pending")  # completed 却无正文
            self.assertFalse(diags[1].has_content)

    def test_apply_fixes_reconciles(self):
        with tempfile.TemporaryDirectory() as tmp:
            paths = self._setup_drift(Path(tmp))
            fixed = apply_fixes(paths, diagnose(paths), log=lambda *a: None)
            self.assertEqual(fixed, 2)
            # 缓存已从报告重建
            self.assertTrue((paths.processed_dir / "generated_chapter_1.txt").exists())
            # 无正文的章被改回 pending
            state = load_task_state(paths, 2)
            self.assertEqual(state["1"], "pending")
            self.assertEqual(state["0"], "completed")
            # 修复后再诊断应干净
            self.assertEqual([d for d in diagnose(paths) if d.issues], [])


# 拆分成多个 router 后，断言最终装配的路由集合与预期完全一致（防重构漏挂/错挂）。
_EXPECTED_ROUTES = {
    ("GET", "/"),
    ("GET", "/api/templates"),
    ("GET", "/api/tasks"), ("POST", "/api/tasks"),
    ("POST", "/api/tasks/{name}/save-template"),
    ("GET", "/api/tasks/{name}/settings"), ("PUT", "/api/tasks/{name}/settings"),
    ("GET", "/api/tasks/{name}/prompts"), ("PUT", "/api/tasks/{name}/prompts"),
    ("GET", "/api/tasks/{name}/chapters"), ("POST", "/api/tasks/{name}/chapters"),
    ("GET", "/api/tasks/{name}/chapters/{index}"),
    ("DELETE", "/api/tasks/{name}/chapters/{index}"),
    ("POST", "/api/tasks/{name}/chapters/{index}/move"),
    ("POST", "/api/tasks/{name}/chapters/{index}/accept"),
    ("POST", "/api/tasks/{name}/chapters/{index}/reject"),
    ("PUT", "/api/tasks/{name}/chapters/{index}/refs"),
    ("POST", "/api/tasks/{name}/ingest"),
    ("POST", "/api/tasks/{name}/run"),
    ("POST", "/api/tasks/{name}/modify"),
    ("POST", "/api/tasks/{name}/research"),
    ("POST", "/api/tasks/{name}/reset"),
    ("GET", "/api/tasks/{name}/log"),
    ("GET", "/api/tasks/{name}/output"),
    ("GET", "/api/tasks/{name}/refs"),
    ("GET", "/api/tasks/{name}/review"),
}


@unittest.skipUnless(_HAS_FASTAPI, "需要 fastapi（可选依赖，本地未装则跳过）")
class WebappRouteTest(unittest.TestCase):
    def test_route_parity(self):
        from docloom.webapp.server import create_app
        with tempfile.TemporaryDirectory() as tmp:
            app = create_app(Path(tmp) / "workspace")
        actual = set()
        for r in app.routes:
            path = getattr(r, "path", "")
            for m in (getattr(r, "methods", None) or set()):
                if m in ("GET", "POST", "PUT", "DELETE") and path != "/openapi.json":
                    actual.add((m, path))
        self.assertEqual(actual, _EXPECTED_ROUTES)


if __name__ == "__main__":
    unittest.main()
