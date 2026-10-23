"""Bounded presentation regressions in fresh owned copies; no experiments."""
from pathlib import Path
import csv
import hashlib
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

PROJECT = Path(__file__).resolve().parents[2]


def sha(path):
    return hashlib.sha256(path.read_bytes()).hexdigest()


class BuildPipelineTests(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory(prefix="contextmark-build-")
        self.addCleanup(self.temporary.cleanup)
        self.project = Path(self.temporary.name) / "packet"
        shutil.copytree(PROJECT, self.project,
                        ignore=shutil.ignore_patterns("__pycache__", ".plot-build-*"))
        self.paper = self.project / "paper"
        self.env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONUTF8="1")

    def command(self, *args, no_site=False, env=None):
        return subprocess.run([sys.executable, "-B", *(["-S"] if no_site else []),
                               str(self.paper / "build.py"), *args],
                              cwd=self.project, env=env or self.env,
                              capture_output=True, text=True, timeout=55)

    def outputs(self):
        names = list((self.paper / "figures").glob("*.pdf"))
        names += [self.paper / "main.pdf", self.paper / "supplement.pdf"]
        return {str(p.relative_to(self.paper)): sha(p) for p in names}

    def edit_csv(self, path, action):
        with path.open(encoding="utf-8-sig", newline="") as f:
            reader = csv.DictReader(f)
            fields, rows = reader.fieldnames, list(reader)
        action(rows)
        with path.open("w", encoding="utf-8", newline="") as f:
            writer = csv.DictWriter(f, fieldnames=fields)
            writer.writeheader()
            writer.writerows(rows)

    def assert_gate(self, result, before, message):
        output = result.stdout + result.stderr
        self.assertNotEqual(result.returncode, 0, output)
        self.assertIn(message, output)
        self.assertNotIn("-halt-on-error", output, "TeX ran before the failed plot gate")
        self.assertEqual(self.outputs(), before, "Failed drawing replaced cached deliverables")

    def test_neutral_default_build_runs_real_vectors_before_tex(self):
        inputs = {str(p.relative_to(self.project)): sha(p)
                  for p in (self.project / "artifact/results").rglob("*") if p.is_file()}
        result = self.command()
        self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
        self.assertLess(result.stdout.index("draw_security.py"), result.stdout.index("-halt-on-error"))
        self.assertLess(result.stdout.index("draw_evaluation.py"), result.stdout.index("-halt-on-error"))
        self.assertIn("Build complete: fresh CSV-driven", result.stdout)
        self.assertEqual(inputs, {str(p.relative_to(self.project)): sha(p)
                                 for p in (self.project / "artifact/results").rglob("*") if p.is_file()})
        for name in ("security-bounds.pdf", "security-bounds-supplement.pdf",
                     "optional-stopping-coverage.pdf", "compiler-scaling.pdf",
                     "compiler-scaling-supplement.pdf"):
            content = (self.paper / "figures" / name).read_bytes()
            self.assertTrue(content.startswith(b"%PDF-") and b"%%EOF" in content[-1024:])

    def test_changed_finite_timing_rejects_retained_snapshot(self):
        before = self.outputs()
        self.edit_csv(self.project / "artifact/results/derived/compiler-scaling.csv",
                      lambda rows: rows[0].update(median_validated_tip_total_us="694.345"))
        self.assert_gate(self.command(), before, "Retained CSV changed")

    def test_nonfinite_probability_rejects_before_tex(self):
        before = self.outputs()
        self.edit_csv(self.project / "artifact/results/derived/security-removal.csv",
                      lambda rows: rows[0].update(theorem_bound="nan"))
        self.assert_gate(self.command(), before, "Retained security CSV changed")

    def test_bad_evaluation_schema_rejects_before_tex(self):
        before = self.outputs()
        path = self.project / "artifact/results/derived/compiler-scaling.csv"
        path.write_text(path.read_text(encoding="utf-8").replace("median_verify_us", "wrong_units", 1),
                        encoding="utf-8")
        self.assert_gate(self.command(), before, "Retained CSV changed")

    def test_missing_dependency_cannot_use_cached_figures(self):
        before = self.outputs()
        env = dict(self.env, PYTHONPATH="")
        self.assert_gate(self.command(no_site=True, env=env), before, "No module named")

    def test_zero_exit_without_output_is_not_success(self):
        before = self.outputs()
        renderer = self.paper / "figures/draw_evaluation.py"
        text = renderer.read_text(encoding="utf-8")
        # Controlled owned output-loss fault: process exits zero but draws no PDF.
        old = 'if __name__ == "__main__":\n    main()'
        self.assertIn(old, text)
        renderer.write_text(text.replace(old, 'if __name__ == "__main__":\n    pass'),
                            encoding="utf-8")
        self.assert_gate(self.command(), before, "Renderer did not produce")

    def test_current_proof_hash_cannot_remain_old(self):
        before = self.outputs()
        self.edit_csv(self.project / "artifact/claim_evidence_ledger.csv",
                      lambda rows: rows[0].update(evidence_sha256="0" * 64))
        self.assert_gate(self.command("--check-evidence"), before, "Claim evidence identity changed: C01")

    def test_existing_owner_quiescence_cannot_disappear_from_index(self):
        before = self.outputs()
        path = self.project / "artifact/proof-index.csv"
        path.write_text("".join(line for line in path.read_text(encoding="utf-8").splitlines(True)
                                if ",Live-owner quiescence," not in line), encoding="utf-8")
        self.assert_gate(self.command("--check-evidence"), before, "Proof index differs")

    def test_historical_binding_cannot_be_relabelled_current(self):
        before = self.outputs()
        self.edit_csv(self.project / "artifact/claim_evidence_ledger.csv",
                      lambda rows: rows[2].update(evidence_scope="current_manuscript"))
        self.assert_gate(self.command("--check-evidence"), before, "Incorrect evidence scope: C03")


if __name__ == "__main__":
    unittest.main()
