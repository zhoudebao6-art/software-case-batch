import base64
import importlib.util
import base64
import json
import os
import subprocess
import sys
import tempfile
import unittest
import zipfile
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

MODULE = Path(__file__).resolve().parents[1] / "scripts" / "caseflow.py"
spec = importlib.util.spec_from_file_location("caseflow", MODULE)
flow = importlib.util.module_from_spec(spec)
spec.loader.exec_module(flow)

PNG = base64.b64decode('iVBORw0KGgoAAAANSUhEUgAAACAAAAAgCAIAAAD8GO2jAAAAN0lEQVR4nO3RwQ0AMAjDwJT9d05HMB9+vgGCZF7bXJrT9XhgwR8gEyETIRMhEyETIRMhEyEThXzH8QM9OMM6fAAAAABJRU5ErkJggg==')


def docx(path):
    with zipfile.ZipFile(path, "w") as z:
        z.writestr("[Content_Types].xml", '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types"><Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/><Override PartName="/word/document.xml" ContentType="application/vnd.openxmlformats-officedocument.wordprocessingml.document.main+xml"/></Types>')
        z.writestr("_rels/.rels", '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="r1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="word/document.xml"/></Relationships>')
        z.writestr("word/document.xml", '<w:document xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main"><w:body><w:p><w:r><w:t>fixture</w:t></w:r></w:p></w:body></w:document>')


def put(path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def fake_runtime(root):
    """Runtime paths for mocked execution; never reads the user's local config."""
    runtime = {}
    for name in ('python', 'ffmpeg', 'ffprobe', 'soffice', 'pdftoppm', 'docx_renderer', 'node'):
        target = root / 'fixture-tools' / (name + '.exe')
        target.parent.mkdir(exist_ok=True)
        target.write_bytes(b'fixture, not executable')
        runtime[name] = str(target)
    package = root / 'fixture-tools/node_modules/playwright/package.json'
    package.parent.mkdir(parents=True, exist_ok=True)
    package.write_text('{}')
    runtime['node_modules'] = str(package.parent.parent)
    return runtime


class FakeExecutor:
    def __init__(self, revise_visual=False, revise_video=False, bad_build=False, permanent_visual=False):
        self.stages = []
        self.video_calls = 0
        self.revise_visual = revise_visual
        self.revise_video = revise_video
        self.bad_build = bad_build
        self.permanent_visual = permanent_visual

    def __call__(self, cfg, case, stage, context, output=None):
        self.stages.append((case.name, stage))
        if stage == "build":
            if self.bad_build and context["case_name"] == "bad":
                raise flow.Blocked("fake build failure")
            revised = case / "deliverable" / Path(context["source_docx"]).name
            revised.parent.mkdir(exist_ok=True)
            docx(revised)
            put(case / "evidence/ui/overview.png", PNG)
            put(case / "evidence/docx-render/page-1.png", PNG)
            put(case / "exports/fig.png", PNG)
            put(case / "exports/fig.csv", b"x,y\n1,2\n")
            put(case / "exports/fig.md", b"Figure explanation")
            report = {"rendered_docx_sha256": flow.sha256(revised), "rendered_page_count": 1,
                      "source_sha256": context["source_sha256"],
                      "tests": [{"command": "fixture-check", "exit_code": 0, "log": "evidence/tests.log"}]}
            put(case / "evidence/tests.log", b"fixture check passed")
            put(case / "evidence/formula_registry.json", b'{"formulas":[],"reason":"fixture"}')
            put(case / "evidence/source_trace.json", b'{"source":"fixture"}')
            put(case / "evidence/docx-render/document.pdf", b"%PDF-fixture")
            flow.atomic_json(case / "evidence/preservation.json", {"original_sha256": context["source_sha256"], "revised_sha256": flow.sha256(revised), "structural_preservation_ok": True, "all_requested_figures_embedded": True})
            flow.atomic_json(case / "evidence/render.json", {"docx_sha256": flow.sha256(revised), "page_count": 1,
                             "page_hashes": {"evidence/docx-render/page-1.png": flow.sha256(case / "evidence/docx-render/page-1.png")},
                             "pdf": "evidence/docx-render/document.pdf", "pdf_sha256": flow.sha256(case / "evidence/docx-render/document.pdf")})
            put(case / "evidence/verification.json", json.dumps(report).encode())
            manifest = {"source_sha256": context["source_sha256"], "revised_docx": revised.relative_to(case).as_posix(),
                        "charts": [{"figure_id": "fig-1", "formula_ids": [], "snapshot_id": "fixture-1",
                                    "png": "exports/fig.png", "csv": "exports/fig.csv", "explanation": "exports/fig.md"}],
                        "ui_screenshots": ["evidence/ui/overview.png"], "rendered_pages": ["evidence/docx-render/page-1.png"],
                        "test_report": "evidence/verification.json", "formula_registry": "evidence/formula_registry.json", "source_trace": "evidence/source_trace.json",
                        "preservation_report": "evidence/preservation.json", "render_report": "evidence/render.json"}
            put(case / "exports/fig-2.png", PNG + b"second fixture figure")
            put(case / "exports/fig-2.csv", b"x,y\n1,3\n")
            put(case / "exports/fig-2.md", b"Second figure explanation")
            manifest['charts'].append({"figure_id": "fig-2", "formula_ids": [], "snapshot_id": "fixture-1",
                                       "png": "exports/fig-2.png", "csv": "exports/fig-2.csv", "explanation": "exports/fig-2.md"})
            manifest['chart_design'] = 'evidence/chart-design.json'
            flow.atomic_json(case / manifest['chart_design'], {'rules_version': '2026-09-24', 'figures': [
                {'figure_id': c['figure_id'], **{k + '_sha256': flow.sha256(case / c[k]) for k in ('png', 'csv', 'explanation')},
                 **{k: 'Fixture: chart quality is not inferred by this test.' for k in ('business_question', 'reader_takeaway', 'chart_type', 'selection_reason', 'scenario_coverage', 'calculation_basis')},
                 'explanation_outline': {k: 'Fixture section' for k in ('purpose', 'reading', 'calculation', 'findings', 'decision')}}
                for c in manifest['charts']]})
            flow.atomic_json(case / "evidence/artifact-manifest.json", manifest)
        elif stage == "video":
            self.video_calls += 1
            a = flow.read_json(case / "evidence/artifact-manifest.json")
            put(case / "recording/final.mp4", b"\x00\x00\x00\x18ftypisomfake mp4 for mocked ffprobe " + str(self.video_calls).encode())
            put(case / "recording/evidence/contact.png", PNG)
            frames = []
            for i in range(40):
                name = f"recording/evidence/frame-{i:03d}.png"
                put(case / name, PNG)
                frames.append({"file": name, "seconds": i / 5, "sha256": flow.sha256(case / name), "type": "uniform_sample"})
            for label, seconds in (("first", 0), ("last", 7.9667)):
                name = f"recording/evidence/{label}.png"
                put(case / name, PNG)
                frames.append({"file": name, "seconds": seconds, "sha256": flow.sha256(case / name), "type": label})
            timeline = {"video_sha256": flow.sha256(case / "recording/final.mp4"), "duration": 8.0,
                        "width": 1920, "height": 1080, "codec": "h264", "fps": 30, "decode_ok": True,
                        "frames": frames, "contact_sheets": [{"file": "recording/evidence/contact.png",
                        "sha256": flow.sha256(case / "recording/evidence/contact.png")}]}
            flow.atomic_json(case / "recording/evidence/timeline.json", timeline)
            a.update(video="recording/final.mp4", video_contact_sheets=["recording/evidence/contact.png"],
                     video_timeline="recording/evidence/timeline.json")
            flow.atomic_json(case / "evidence/artifact-manifest.json", a)
        elif stage.startswith("review_"):
            kind = stage.removeprefix("review_")
            revise = (self.revise_visual or self.revise_video) if kind == "final" else self.revise_visual if kind == "visual" else self.revise_video
            files = context["snapshot_files"]
            report = {"verdict": "revise" if revise else "pass",
                      "rules_version": "2026-09-24",
                      "chart_reviews": [{"figure_id": c['figure_id'], "png": c['png'], "png_sha256": files[c['png']],
                           "checks": {k: {"passed": True, "evidence": "Fixture only; no visual approval."} for k in ('meaning', 'data', 'legibility', 'layout', 'explanation')},
                           "evidence_files": [c['png'], c['csv'], c['explanation'], 'evidence/ui/overview.png', 'evidence/docx-render/page-1.png']}
                          for c in context['artifact_manifest']['charts']],
                      "coverage": "fixture only", "limitations": ["not a real visual review"],
                      "issues": [{"severity": "major", "artifact": "evidence/ui/overview.png", "evidence": "fixture", "fix": "fix"}] if revise else [],
                      "reviewed_files": [{"path": p, "sha256": files[p]} for p in context["required_review_files"]],
                      "snapshot_sha256": context["snapshot_sha256"]}
            flow.atomic_json(output, report)
        elif stage in {"repair_visual", "repair_final"}:
            if not self.permanent_visual:
                self.revise_visual = False
            if stage == "repair_final":
                self.revise_video = False
            put(case / "evidence/ui/overview.png", PNG + b"fixed")
        elif stage == "repair_video":
            self.revise_video = False
            put(case / "recording/evidence/contact.png", PNG + b"fixed")
            timeline_path = case / "recording/evidence/timeline.json"
            t = flow.read_json(timeline_path)
            t["contact_sheets"][0]["sha256"] = flow.sha256(case / "recording/evidence/contact.png")
            flow.atomic_json(timeline_path, t)
        selected=flow.model_for_stage(cfg, stage)
        return {"stage": stage, "model": selected['model'],
                "reasoning_effort": selected['reasoning_effort'],
                "sandbox": "read-only" if stage.startswith("review_") else "workspace-write",
                "thread_id": "fixture-" + stage, "exit_code": 0}


class CaseflowTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        self.source = self.root / "incoming"
        self.source.mkdir()
        self.config_path = self.root / "config.json"
        (self.root / "prompts").mkdir()
        for name in ("build", "repair", "review_visual", "video", "review_video", "review_final"):
            (self.root / "prompts" / f"{name}.md").write_text(name)
        self.exe = self.root / "codex.exe"
        self.exe.write_bytes(b"fixture")
        cfg = {"runner": {"workspace_root": str(self.root / "cases"), "prompts_dir": "prompts", "codex_executable": str(self.exe),
                          "model_timeout_seconds": 1, "max_repairs_per_review": 2},
               "models": {"builder": {"model": "gpt-6-sol", "reasoning_effort": "high"},
                          "reviewer": {"model": "gpt-6-sol", "reasoning_effort": "ultra"}, "allow_fallback": False},
               "video": {"min_seconds": 8, "max_seconds": 12, "width": 1920, "height": 1080, "fps": 30, "sample_fps": 5}}
        self.config_path.write_text(json.dumps(cfg))
        self.cfg = flow.config_at(self.config_path)

    def tearDown(self):
        self.tmp.cleanup()

    def make_source(self, name="a.docx"):
        p = self.source / name
        p.parent.mkdir(parents=True, exist_ok=True)
        docx(p)
        return p

    def run_fake(self, fake, **kwargs):
        with patch.object(flow.subprocess, "run", return_value=SimpleNamespace(stdout='{"format":{"duration":"8.0"},"streams":[{"codec_name":"h264","width":1920,"height":1080,"avg_frame_rate":"30/1"}]}')):
            return flow.run_batch(self.cfg, str(self.source), executor=fake, **kwargs)

    def test_plan_dry_run_routing_and_no_execution(self):
        p = self.make_source()
        m = flow.plan(self.cfg, self.source)
        dry = flow.run_batch(self.cfg, str(self.source), dry_run=True)
        commands = dry["cases"][0]["commands"]
        self.assertIn("gpt-6-sol", commands["review_visual"])
        self.assertIn("model_reasoning_effort=ultra", commands["review_visual"])
        self.assertIn("read-only", commands["review_visual"])
        self.assertIn("gpt-6-sol", commands["build"])
        self.assertIn("model_reasoning_effort=high", commands["build"])
        self.assertIn("workspace-write", commands["build"])
        self.assertIn("approval_policy=never", commands["review_visual"])
        self.assertIn("--output-schema", commands["review_visual"])
        self.assertFalse((flow.case_workspace(flow.batch_folder(self.cfg, m), m["cases"][0])).exists())
        self.assertEqual(flow.sha256(p), m["cases"][0]["source_sha256"])

    def test_batch_specific_inner_delivery_survives_replan(self):
        self.make_source()
        planned = flow.plan(self.cfg, self.source)
        folder = flow.batch_folder(self.cfg, planned)
        manifest = flow.read_json(folder / "manifest.json")
        manifest["output_root"] = str(self.source / "_成品")
        flow.atomic_json(folder / "manifest.json", manifest)
        (self.source / "_成品").mkdir()
        docx(self.source / "_成品" / "completed.docx")
        self.assertEqual(flow.plan(self.cfg, self.source)["batch_id"], planned["batch_id"])
        loaded, _ = flow.load_batch(self.cfg, planned["batch_id"])
        self.assertEqual(loaded["output_root"], str(self.source / "_成品"))
        self.assertEqual(len(loaded["cases"]), 1)

    def test_cli_plan_status_and_dry_run(self):
        self.make_source()
        base = [sys.executable, str(MODULE), "--config", str(self.config_path)]
        planned = subprocess.run(base + ["plan", str(self.source)], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(planned.returncode, 0, planned.stderr)
        batch_id = json.loads(planned.stdout)["batch_id"]
        status = subprocess.run(base + ["status", batch_id], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(json.loads(status.stdout)["cases"][0]["stage"], "planned")
        dry = subprocess.run(base + ["run", batch_id, "--dry-run"], capture_output=True, text=True, encoding="utf-8")
        self.assertEqual(dry.returncode, 0, dry.stderr)
        self.assertTrue(json.loads(dry.stdout)["dry_run"])
        self.assertFalse((flow.case_workspace(flow.batch_folder(self.cfg, batch_id), json.loads(planned.stdout)["cases"][0])).exists())

    def test_delivery_recovery_and_source_integrity(self):
        p = self.make_source()
        before = flow.sha256(p)
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor()
        result = self.run_fake(fake)
        state = result["cases"][0]
        self.assertEqual(state["stage"], "delivered")
        dest = Path(state["delivery"])
        self.assertEqual(flow.sha256(dest / "原始文件" / p.name), before)
        self.assertEqual(flow.sha256(p), before)
        calls = len(fake.stages)
        again = self.run_fake(fake)
        self.assertEqual(again["cases"][0]["stage"], "delivered")
        self.assertEqual(len(fake.stages), calls)

    def test_resume_after_publish_rename_and_changed_delivery_rejected(self):
        self.make_source()
        m = flow.plan(self.cfg, self.source)
        fake = FakeExecutor()
        first = self.run_fake(fake)["cases"][0]
        state_path = flow.state_at(flow.batch_folder(self.cfg, m), m["cases"][0]["case_id"])
        state = flow.read_json(state_path)
        state["stage"] = "visual_pass"
        flow.atomic_json(state_path, state)
        count = len(fake.stages)
        recovered = self.run_fake(fake)["cases"][0]
        self.assertEqual(recovered["stage"], "delivered")
        self.assertEqual(len(fake.stages), count)
        state = flow.read_json(state_path)
        state["stage"] = "visual_pass"
        flow.atomic_json(state_path, state)
        put(Path(first["delivery"]) / "foreign.txt", b"foreign")
        refused = self.run_fake(fake)["cases"][0]
        self.assertEqual(refused["stage"], "blocked")
        self.assertEqual((Path(first["delivery"]) / "foreign.txt").read_bytes(), b"foreign")

    def test_reject_review_blocks_delivery(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor(revise_visual=True)
        with patch.object(fake, "__call__", wraps=fake.__call__):
            result = self.run_fake(fake)
        self.assertEqual(result["cases"][0]["stage"], "delivered")
        self.assertIn("repair_visual", [x[1] for x in fake.stages])
        self.assertGreaterEqual([x[1] for x in fake.stages].count("review_visual"), 2)

    def test_stale_review_hash_rejected(self):
        self.make_source()
        m = flow.plan(self.cfg, self.source)
        case = flow.case_workspace(flow.batch_folder(self.cfg, m), m["cases"][0])
        case.mkdir(parents=True)
        put(case / "a.png", PNG)
        files = flow.snapshot(case, video=False)
        report = {"verdict": "pass", "issues": [], "coverage": "fixture", "limitations": [], "reviewed_files": [{"path": p, "sha256": h} for p,h in files.items()], "snapshot_sha256": flow.snapshot_id(files)}
        put(case / "a.png", PNG + b"mutated")
        with self.assertRaises(flow.Blocked):
            flow.verify_review(report, flow.snapshot(case, video=False), {"a.png"})

    def test_failure_isolation_and_legacy_doc(self):
        self.make_source("good.docx")
        self.make_source("bad.docx")
        put(self.source / "old.doc", b"legacy")
        flow.plan(self.cfg, self.source)
        result = self.run_fake(FakeExecutor(bad_build=True))
        states = {e["case_id"]: e for e in result["cases"]}
        self.assertEqual(sorted(s["stage"] for s in states.values()), ["blocked", "blocked", "delivered"])
        self.assertTrue(any("legacy .doc" in (s.get("reason") or "") for s in states.values()))

    def test_source_change_prevents_run(self):
        p = self.make_source()
        m = flow.plan(self.cfg, self.source)
        with zipfile.ZipFile(p, "a") as z:
            z.writestr("extra", "changed")
        with self.assertRaises(flow.Blocked):
            flow.load_batch(self.cfg, m["batch_id"])

    def test_path_traversal_and_lock(self):
        self.make_source()
        m = flow.plan(self.cfg, self.source)
        folder = flow.batch_folder(self.cfg, m)
        case = flow.case_workspace(folder, m["cases"][0])
        case.mkdir(parents=True)
        with self.assertRaises(flow.Blocked):
            flow.artifact(case, "../outside")
        with flow.BatchLock(folder):
            with self.assertRaises(flow.Busy):
                with flow.BatchLock(folder):
                    pass

    def test_nonempty_existing_delivery_refused(self):
        self.make_source()
        m = flow.plan(self.cfg, self.source)
        out = Path(m["output_root"])
        out.mkdir()
        put(out / "prior.txt", b"preserve")
        with self.assertRaises(flow.Blocked):
            self.run_fake(FakeExecutor())
        self.assertEqual((out / "prior.txt").read_bytes(), b"preserve")

    def test_permanent_review_veto_stops_after_two_repairs(self):
        self.make_source()
        flow.plan(self.cfg, self.source)
        fake = FakeExecutor(revise_visual=True, permanent_visual=True)
        result = self.run_fake(fake)
        self.assertEqual(result["cases"][0]["stage"], "blocked")
        self.assertEqual([s for _, s in fake.stages].count("repair_visual"), 2)
        self.assertNotIn("video", [s for _, s in fake.stages])
        self.assertFalse((self.source.parent / "incoming1").exists())

    def test_changed_artifact_forces_new_reviews_on_resume(self):
        self.make_source()
        m = flow.plan(self.cfg, self.source)
        out = Path(m["output_root"])
        fake = FakeExecutor()
        def arrive_during_review(cfg, case, stage, context, output=None):
            record = fake(cfg, case, stage, context, output)
            if stage == "review_video":
                put(out / "prior.txt", b"external")
            return record
        first = self.run_fake(arrive_during_review)
        self.assertEqual(first["cases"][0]["stage"], "blocked")
        visual_count = [s for _, s in fake.stages].count("review_visual")
        case = flow.case_workspace(flow.batch_folder(self.cfg, m), m["cases"][0])
        put(case / "evidence/ui/overview.png", PNG + b"changed")
        (out / "prior.txt").unlink()
        out.rmdir()
        second = self.run_fake(fake)
        self.assertEqual(second["cases"][0]["stage"], "delivered")
        self.assertGreater([s for _, s in fake.stages].count("review_visual"), visual_count)

    def test_csv_and_video_final_frame_fail_closed(self):
        self.make_source()
        m = flow.plan(self.cfg, self.source)
        self.run_fake(FakeExecutor())
        case = flow.case_workspace(flow.batch_folder(self.cfg, m), m["cases"][0])
        put(case / "exports/fig.csv", b"x,y\n")
        with self.assertRaises(flow.Blocked):
            flow.validate_manifest(case, m["cases"][0]["source_sha256"], video=False, cfg=self.cfg)
        put(case / "exports/fig.csv", b"x,y\n1,2\n")
        timeline = case / "recording/evidence/timeline.json"
        data = flow.read_json(timeline)
        data["frames"][-1]["seconds"] = 6.0
        flow.atomic_json(timeline, data)
        with patch.object(flow.subprocess, "run", return_value=SimpleNamespace(stdout='{"format":{"duration":"8.0"},"streams":[{"codec_name":"h264","width":1920,"height":1080,"avg_frame_rate":"30/1"}]}')):
            with self.assertRaises(flow.Blocked):
                flow.validate_manifest(case, m["cases"][0]["source_sha256"], video=True, cfg=self.cfg)

    def test_cross_process_lock(self):
        self.make_source()
        m = flow.plan(self.cfg, self.source)
        folder = flow.batch_folder(self.cfg, m)
        code = "import importlib.util,sys;from pathlib import Path;s=importlib.util.spec_from_file_location('f',sys.argv[1]);m=importlib.util.module_from_spec(s);s.loader.exec_module(m);\ntry:\n with m.BatchLock(Path(sys.argv[2])): sys.exit(0)\nexcept m.Busy: sys.exit(3)"
        with flow.BatchLock(folder):
            result = subprocess.run([sys.executable, "-c", code, str(MODULE), str(folder)], capture_output=True, text=True)
        self.assertEqual(result.returncode, 3, result.stderr)


if __name__ == "__main__":
    unittest.main()
