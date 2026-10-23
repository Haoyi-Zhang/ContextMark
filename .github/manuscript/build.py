"""Build the current retained-data paper: checked evidence, Python vectors, TeX.

No experiments run here. Changed measurement inputs require an explicit reviewed
snapshot update; this build never substitutes cached figures for failed drawing.
"""
from pathlib import Path
import argparse
import csv
import hashlib
import json
import os
import re
import subprocess
import sys
import tempfile

PAPER = Path(__file__).resolve().parent
FIGURES = ("security-bounds.pdf", "security-bounds-supplement.pdf",
           "optional-stopping-coverage.pdf", "compiler-scaling.pdf",
           "compiler-scaling-supplement.pdf")


def proof_rows(project):
    """Index existing declarations, not proof validity or mechanization."""
    rows = []
    pattern = re.compile(r"^\\begin\{(definition|theorem|lemma|proposition|corollary)\}\[([^\]]+)\]")
    for document in ("paper/main.tex", "paper/supplement.tex"):
        entry = 0
        for line, text in enumerate((project / document).read_text(encoding="utf-8").splitlines(), 1):
            match = pattern.match(text.strip())
            if match:
                entry += 1
                rows.append(dict(document=document, entry=str(entry), kind=match[1],
                                 title=match[2], line=str(line), mechanized="False"))
    return rows


def verify_evidence(project):
    """Keep current proof pointers separate from immutable retained executions."""
    with (project / "artifact/claim_evidence_ledger.csv").open(encoding="utf-8", newline="") as f:
        claims = list(csv.DictReader(f))
    current = set()
    historical = 0
    for row in claims:
        relative = row["evidence_path"]
        path = (project / relative).resolve()
        if not path.is_relative_to(project.resolve()) or not path.is_file():
            raise ValueError("Missing/out-of-root claim evidence: " + relative)
        if relative == "paper/supplement.tex":
            current.add(row["claim_id"])
            expected_scope = "current_manuscript"
        elif relative.startswith("artifact/results/"):
            historical += 1
            expected_scope = "retained_execution"
        else:
            raise ValueError("Unclassified claim evidence: " + relative)
        if row.get("evidence_scope") != expected_scope:
            raise ValueError("Incorrect evidence scope: " + row["claim_id"])
        if hashlib.sha256(path.read_bytes()).hexdigest() != row["evidence_sha256"]:
            raise ValueError("Claim evidence identity changed: " + row["claim_id"])
    if current != {"C01", "C02", "C05", "C07", "C10"}:
        raise ValueError("Current proof claim set differs")
    with (project / "artifact/proof-index.csv").open(encoding="utf-8", newline="") as f:
        indexed = list(csv.DictReader(f))
    expected = proof_rows(project)
    if indexed != expected:
        raise ValueError("Proof index differs from current TeX declarations/lines")
    print(f"Evidence checked: {len(current)} current proof bindings, "
          f"{historical} retained execution bindings, {len(expected)} declarations.", flush=True)


def check_security_snapshot(project):
    # Only these four input identities are read from the historical manifest.
    # Its historical source-code bindings and execution results are not rewritten
    # or asserted to have been rerun by this presentation build.
    manifest = json.loads((project / "artifact/results/raw/run-manifest.json").read_text(encoding="utf-8"))
    entries = {r["path"]: r["sha256"] for r in manifest["entries"]}
    for game in ("removal", "nontransfer", "unforgeability", "collusion"):
        relative = f"results/derived/security-{game}.csv"
        if hashlib.sha256((project / "artifact" / relative).read_bytes()).hexdigest() != entries.get(relative):
            raise ValueError("Retained security CSV changed: " + relative)


def run(command):
    print("[build] " + subprocess.list2cmdline([str(x) for x in command]), flush=True)
    subprocess.run([str(x) for x in command], cwd=PAPER, check=True)


def vectors():
    check_security_snapshot(PAPER.parent)
    # Both real renderers must finish in an empty staging directory before any
    # installed figure is replaced or any TeX command is invoked.
    with tempfile.TemporaryDirectory(prefix=".plot-build-", dir=PAPER) as temporary:
        stage = Path(temporary)
        python = [sys.executable, "-B"] + (["-S"] if sys.flags.no_site else [])
        run([*python, PAPER / "figures/draw_security.py", "--outdir", stage])
        run([*python, PAPER / "figures/draw_evaluation.py", "--outdir", stage])
        for name in FIGURES:
            path = stage / name
            if not path.is_file():
                raise ValueError("Renderer did not produce " + name)
            content = path.read_bytes()
            if not content.startswith(b"%PDF-") or b"%%EOF" not in content[-1024:]:
                raise ValueError("Renderer produced an invalid/empty PDF: " + name)
        for name in FIGURES:
            source, target = stage / name, PAPER / "figures" / name
            if not target.exists() or source.read_bytes() != target.read_bytes():
                os.replace(source, target)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--check-evidence", action="store_true",
                        help="read-only current proof/index and retained claim identity check")
    args = parser.parse_args()
    verify_evidence(PAPER.parent)
    if args.check_evidence:
        return
    os.environ.setdefault("SOURCE_DATE_EPOCH", "1784332800")
    os.environ["FORCE_SOURCE_DATE"] = "1"
    os.environ["TZ"] = "UTC"
    os.environ["PYTHONDONTWRITEBYTECODE"] = "1"
    vectors()
    # Remove only this build's named outputs, after all vector gates passed.
    for stem in ("main", "supplement"):
        for suffix in (".aux", ".bbl", ".blg", ".log", ".out", ".toc", ".pdf"):
            (PAPER / (stem + suffix)).unlink(missing_ok=True)
    latex = os.environ.get("PDFLATEX", "pdflatex")
    bibtex = os.environ.get("BIBTEX", "bibtex")
    tex = lambda name: run([latex, "-interaction=nonstopmode", "-halt-on-error", name + ".tex"])
    tex("main")
    run([bibtex, "main"])
    tex("main")
    tex("main")
    tex("supplement")
    tex("supplement")
    for name in ("main.pdf", "supplement.pdf"):
        if not (PAPER / name).is_file() or (PAPER / name).stat().st_size == 0:
            raise ValueError("Missing/empty TeX output: " + name)
    print("Build complete: fresh CSV-driven vector plots and both TeX documents.", flush=True)


if __name__ == "__main__":
    try:
        main()
    except (OSError, ValueError, subprocess.CalledProcessError) as exc:
        print("Build failed; cached figures/PDFs are not a successful build: " + str(exc),
              file=sys.stderr)
        raise SystemExit(1)
