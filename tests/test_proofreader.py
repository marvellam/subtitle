from __future__ import annotations

import csv
import importlib.util
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

import yaml


ROOT = Path(__file__).resolve().parents[1]


def load_module(name: str, path: Path):
    spec = importlib.util.spec_from_file_location(name, path)
    module = importlib.util.module_from_spec(spec)
    sys.modules[name] = module
    assert spec.loader is not None
    spec.loader.exec_module(module)
    return module


proof = load_module("course_proofread", ROOT / "scripts" / "proofread_srt.py")
compare = load_module("course_compare", ROOT / "scripts" / "compare_manual_srt.py")


class SkillPackageTests(unittest.TestCase):
    def test_skill_metadata_is_valid(self):
        content = (ROOT / "SKILL.md").read_text(encoding="utf-8")
        self.assertTrue(content.startswith("---\n"))
        _, frontmatter, _ = content.split("---", 2)
        metadata = yaml.safe_load(frontmatter)
        self.assertEqual(metadata["name"], "subtitle")
        self.assertTrue(metadata["description"])

    def test_public_package_contains_no_private_paths(self):
        forbidden = ("C:\\Users\\", "X:\\", "37617", ".openclaw")
        for path in ROOT.rglob("*"):
            if not path.is_file() or ".git" in path.parts:
                continue
            if path.resolve() == Path(__file__).resolve() or path.suffix == ".pyc":
                continue
            text = path.read_text(encoding="utf-8-sig")
            for marker in forbidden:
                self.assertNotIn(marker, text, f"private marker {marker!r} in {path}")


class MechanicalSafetyTests(unittest.TestCase):
    def test_legitimate_repetition_is_preserved(self):
        for text in ("刚刚", "叔叔", "妈妈", "星星", "哈哈哈"):
            self.assertEqual(proof.cleanup_repeated_chars(text)[0], text)

    def test_discourse_review_does_not_delete_prefixes(self):
        for text in ("对这个问题我们要分析", "你看这幅画", "对照这个作品"):
            self.assertEqual(proof.cleanup_fillers(text)[0], text)

    def test_only_whole_block_standalone_filler_is_blank(self):
        style = {"speech_fillers": {"standalone_blank": ["啊"]}}
        self.assertEqual(proof.cleanup_fillers("啊", style)[0], "")
        self.assertEqual(proof.cleanup_fillers("啊Q", style)[0], "啊Q")

    def test_identity_lexicon_row_is_not_a_change(self):
        rule = proof.LexiconRule("宋代", "宋代", "主题", "auto", "", "", "")
        text, applied, reviews = proof.apply_lexicon("宋代绘画", "", [rule])
        self.assertEqual(text, "宋代绘画")
        self.assertEqual(applied, [])
        self.assertEqual(reviews, [])

    def test_conflicting_lexicon_rules_are_not_forced(self):
        rules = [
            proof.LexiconRule("卷", "转", "技法", "conditional", "笔", "", ""),
            proof.LexiconRule("卷", "绢", "材料", "conditional", "笔", "", ""),
        ]
        text, applied, reviews = proof.apply_lexicon("这一卷", "笔", rules)
        self.assertEqual(text, "这一卷")
        self.assertEqual(applied, [])
        self.assertEqual(reviews[0]["risk"], "high")

    def test_conditional_rule_is_candidate_not_mechanical_change(self):
        rule = proof.LexiconRule("卷", "转", "技法", "conditional", "笔", "", "")
        text, applied, reviews = proof.apply_lexicon("这一卷", "笔法", [rule])
        self.assertEqual(text, "这一卷")
        self.assertEqual(applied, [])
        self.assertEqual(reviews[0]["suggestion"], "转")

    def test_sentence_final_filler_is_candidate_not_deleted(self):
        style = {"speech_fillers": {"sentence_final_remove": ["啊"]}}
        text, applied, reviews = proof.cleanup_fillers("这个方法啊", style)
        self.assertEqual(text, "这个方法啊")
        self.assertEqual(applied, [])
        self.assertTrue(reviews)


class QualityGateTests(unittest.TestCase):
    def setUp(self):
        self.items = [
            {"index": "1", "timestamp": "00:00:00,000 --> 00:00:01,000", "text": "原文"},
            {"index": "2", "timestamp": "00:00:01,000 --> 00:00:02,000", "text": "内容"},
        ]

    def test_all_accepted_is_valid_when_reasoned(self):
        payload = {
            "chunks": [{
                "chunk_items": [
                    {"index": "1", "text": "原文", "phase1_audit": {"risk": "medium"}, "phase1_decision": "accepted", "reason": "上下文确认原文正确"},
                    {"index": "2", "text": "内容", "phase1_audit": {}, "reason": ""},
                ]
            }]
        }
        proof.validate_ai_payload(payload, self.items)

    def test_missing_index_is_rejected(self):
        payload = {"chunks": [{"chunk_items": [{"index": "1", "text": "原文"}]}]}
        with self.assertRaisesRegex(ValueError, "missing"):
            proof.validate_ai_payload(payload, self.items)

    def test_protected_term_cannot_be_silently_removed(self):
        payload = {
            "chunks": [{"chunk_items": [
                {"index": "1", "text": "改文", "reason": "尝试修改"},
                {"index": "2", "text": "内容"},
            ]}]
        }
        with self.assertRaisesRegex(ValueError, "protected term"):
            proof.validate_ai_payload(payload, self.items, ["原文"])

    def test_external_context_file_is_not_marked_trusted(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            inside = project / "notes.txt"
            inside.write_text("inside", encoding="utf-8")
            external = root / "external.txt"
            external.write_text("external", encoding="utf-8")
            resolved = proof.resolve_context_files(project, {"context_files": ["notes.txt", str(external)]})
            self.assertEqual(resolved["inside_project"], [str(inside.resolve())])
            self.assertEqual(resolved["external_requires_approval"], [str(external.resolve())])

    def test_focused_mode_exports_risk_chunks_only_when_sampling_is_zero(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = root / "project"
            project.mkdir()
            source = root / "lesson_Phase1_机械校对.srt"
            items = [
                {"index": "1", "timestamp": "00:00:00,000 --> 00:00:01,000", "text": "正常内容"},
                {"index": "2", "timestamp": "00:00:01,000 --> 00:00:02,000", "text": "风险术语"},
                {"index": "3", "timestamp": "00:00:02,000 --> 00:00:03,000", "text": "其他内容"},
            ]
            out = root / "chunks.json"
            payload = proof.export_ai_chunks(
                source,
                items,
                1,
                1,
                project,
                {"speaker": "讲师A", "domain": "领域A"},
                {"asr_review_terms": ["风险术语"]},
                out,
                review_mode="focused",
                focused_sample_rate=0,
            )
            self.assertEqual(payload["selected_indices"], ["2"])
            self.assertEqual(payload["speaker"], "讲师A")
            self.assertEqual(payload["domain"], "领域A")

    def test_selected_indices_allow_partial_quality_gate(self):
        payload = {
            "selected_indices": ["1"],
            "chunks": [{"chunk_items": [{"index": "1", "text": "原文"}]}],
        }
        proof.validate_ai_payload(payload, self.items)

    def test_review_selection_cannot_be_narrowed_after_export(self):
        fingerprint = proof.items_fingerprint(self.items)
        manifest = {
            "source_fingerprint": fingerprint,
            "review_mode": "focused",
            "selected_indices": ["1", "2"],
            "total_chunks": 2,
            "selected_chunk_count": 2,
        }
        result = {
            **manifest,
            "selected_indices": ["1"],
            "chunks": [{"chunk_items": [{"index": "1", "text": "原文"}]}],
        }
        with self.assertRaisesRegex(ValueError, "selection manifest"):
            proof.validate_ai_payload(result, self.items, manifest=manifest)


class FeedbackTests(unittest.TestCase):
    def test_term_candidates_ignore_cue_resegmentation(self):
        ai = [
            {"start": 0, "end": 1000, "text": "我们讲伽缪"},
            {"start": 1000, "end": 2000, "text": "的局外人"},
        ]
        manual = [
            {"start": 0, "end": 2000, "text": "我们讲加缪的局外人"},
        ]
        rows = compare.extract_term_candidates(ai, manual)
        self.assertIn(("伽", "加"), {(row["wrong"], row["correct"]) for row in rows})

    def test_blank_feedback_decision_does_not_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            feedback = Path(tmp) / "feedback.csv"
            with feedback.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["wrong", "correct", "merge_decision"])
                writer.writeheader()
                writer.writerow({"wrong": "伽缪", "correct": "加缪", "merge_decision": ""})
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "update_lexicon.py"), "--project", str(project), "--feedback", str(feedback)],
                check=True,
                capture_output=True,
                text=True,
            )
            with (project / "lexicon.csv").open(encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows, [])

    def test_formula_like_feedback_does_not_merge(self):
        with tempfile.TemporaryDirectory() as tmp:
            project = Path(tmp) / "project"
            project.mkdir()
            feedback = Path(tmp) / "feedback.csv"
            with feedback.open("w", encoding="utf-8-sig", newline="") as f:
                writer = csv.DictWriter(f, fieldnames=["wrong", "correct", "merge_decision"])
                writer.writeheader()
                writer.writerow({"wrong": "=CMD()", "correct": "术语", "merge_decision": "approved"})
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "update_lexicon.py"), "--project", str(project), "--feedback", str(feedback)],
                check=True,
                capture_output=True,
                text=True,
            )
            with (project / "lexicon.csv").open(encoding="utf-8-sig") as f:
                rows = list(csv.DictReader(f))
            self.assertEqual(rows, [])


class CliIntegrationTests(unittest.TestCase):
    def make_project(self, root: Path) -> Path:
        project = root / "project"
        project.mkdir()
        (project / "project.yml").write_text(
            "project: test\ndefault_chunk_size: 7\ndefault_context_size: 2\ncontext_files: []\n",
            encoding="utf-8",
        )
        (project / "style_rules.yml").write_text(
            "speech_fillers:\n  standalone_blank: [啊]\n  sentence_start_review: [这个, 那个]\n",
            encoding="utf-8",
        )
        (project / "lexicon.csv").write_text(
            "wrong,correct,category,confidence,condition,source_lesson,note\n宋带,宋代,术语,auto,,,\n",
            encoding="utf-8-sig",
        )
        (project / "blacklist.csv").write_text("term,expected,severity,note\n", encoding="utf-8-sig")
        return project

    def test_phase1_preserves_normal_repetition_and_prefix(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root)
            source = root / "lesson.srt"
            source.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n对照这个作品\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\n刚刚讲到宋带\n\n"
                "3\n00:00:02,000 --> 00:00:03,000\n啊\n",
                encoding="utf-8-sig",
            )
            out = root / "out"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "proofread_srt.py"), "--srt", str(source), "--project", str(project), "--out-dir", str(out)],
                check=True,
                capture_output=True,
                text=True,
            )
            result = (out / "lesson_Phase1_机械校对.srt").read_text(encoding="utf-8-sig")
            self.assertIn("对照这个作品", result)
            self.assertIn("刚刚讲到宋代", result)
            status = json.loads((out / "run_status.json").read_text(encoding="utf-8"))
            self.assertTrue(status["validation"]["project_config_loaded"])
            self.assertTrue(status["validation"]["style_rules_loaded"])
            self.assertEqual(status["validation"]["chunk_size"], 7)

    def test_invalid_srt_writes_status_but_no_proofread_srt(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root)
            source = root / "broken.srt"
            source.write_text("2\nBAD TIME\n内容\n", encoding="utf-8-sig")
            out = root / "out"
            result = subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "proofread_srt.py"), "--srt", str(source), "--project", str(project), "--out-dir", str(out)],
                check=False,
                capture_output=True,
                text=True,
            )
            self.assertEqual(result.returncode, 2)
            self.assertTrue((out / "run_status.json").exists())
            self.assertEqual(list(out.glob("*.srt")), [])

    def test_phase2_all_reasoned_acceptances_can_complete(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            project = self.make_project(root)
            source = root / "lesson.srt"
            source.write_text(
                "1\n00:00:00,000 --> 00:00:01,000\n宋带绘画\n\n"
                "2\n00:00:01,000 --> 00:00:02,000\n正常内容\n",
                encoding="utf-8-sig",
            )
            debug = root / "run" / "debug"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "proofread_srt.py"), "--srt", str(source), "--project", str(project), "--out-dir", str(debug)],
                check=True,
                capture_output=True,
                text=True,
            )
            phase1 = debug / "lesson_Phase1_机械校对.srt"
            chunks_path = debug / "ai_chunks.json"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "proofread_srt.py"), "--srt", str(phase1), "--project", str(project), "--export-ai-chunks", str(chunks_path)],
                check=True,
                capture_output=True,
                text=True,
            )
            payload = json.loads(chunks_path.read_text(encoding="utf-8"))
            for chunk in payload["chunks"]:
                for item in chunk["chunk_items"]:
                    if item.get("phase1_audit"):
                        item["phase1_decision"] = "accepted"
                        item["reason"] = "课程词库确认该机械修正正确"
            results_path = debug / "ai_results.json"
            results_path.write_text(json.dumps(payload, ensure_ascii=False), encoding="utf-8")
            run = root / "run"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "proofread_srt.py"), "--srt", str(phase1), "--project", str(project), "--apply-ai-chunks", str(results_path), "--ai-chunks-manifest", str(chunks_path), "--out-dir", str(run)],
                check=True,
                capture_output=True,
                text=True,
            )
            status = json.loads((run / "run_status.json").read_text(encoding="utf-8"))
            self.assertTrue(status["validation"]["phase2_done"])
            self.assertTrue(status["validation"]["production_ready"])

    def test_init_project_creates_complete_public_schema(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp) / "projects"
            subprocess.run(
                [sys.executable, str(ROOT / "scripts" / "init_project.py"), "--name", "sample-course", "--root", str(root)],
                check=True,
                capture_output=True,
                text=True,
            )
            project = root / "sample-course"
            self.assertTrue((project / "protected_terms.csv").exists())
            self.assertTrue((project / "materials" / "course-outline.md").exists())
            config = yaml.safe_load((project / "project.yml").read_text(encoding="utf-8"))
            self.assertEqual(config["context_files"], ["materials/course-outline.md"])


if __name__ == "__main__":
    unittest.main()
