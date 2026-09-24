#!/usr/bin/env python3
"""Verify a sealed TDSC-01 release without modifying its tree.

Run from any directory. --skip-tests retains static manifest/PDF/citation checks.
The experiment driver is a different command: it intentionally regenerates data.
"""
from __future__ import annotations
import argparse
import csv
import hashlib
import json
import os
from pathlib import Path
import re
import stat
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
EXCLUDED = {"artifact/release-manifest.json", "artifact/release-validation.json"}

def require(condition: bool, message: str) -> None:
    if not condition:
        raise RuntimeError(message)

def sha(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()

def records() -> list[dict]:
    rows = []
    for path in sorted(ROOT.rglob("*")):
        require(not path.is_symlink(), f"symbolic link: {path.relative_to(ROOT)}")
        if path.is_file():
            info = path.stat()
            rows.append({"path": path.relative_to(ROOT).as_posix(),
                         "bytes": info.st_size,
                         "mode": f"{stat.S_IMODE(info.st_mode):04o}",
                         "sha256": sha(path)})
    return rows

def tree_digest(rows: list[dict]) -> str:
    return hashlib.sha256(("".join(json.dumps(row, sort_keys=True, separators=(",", ":")) + "\n" for row in rows)).encode()).hexdigest()

def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--skip-tests", action="store_true")
    args = parser.parse_args()
    require(sorted(p.name for p in ROOT.iterdir()) == ["CURRENT-STATE.md", "artifact", "paper", "research-plan.md"], "unexpected project root")
    before = records()
    manifest = json.loads((ROOT / "artifact/release-manifest.json").read_text())
    covered = [r for r in before if r["path"] not in EXCLUDED]
    require(manifest["entries"] == covered, "release file/hash/mode coverage mismatch")
    require(manifest["canonical_tree_digest_sha256"] == tree_digest(covered), "release tree digest mismatch")
    execution = json.loads((ROOT / "artifact/results/raw/run-manifest.json").read_text())
    for row in execution["entries"]:
        target = ROOT / "artifact" / row["path"]
        require(target.is_relative_to(ROOT / "artifact"), "execution path escape")
        require(target.is_file() and sha(target) == row["sha256"], f"execution evidence changed: {row['path']}")
    paper = (ROOT / "paper/main.tex").read_text()
    commands = re.findall(r"\\cite\{([^}]+)\}", paper)
    bib = re.findall(r"(?m)^@\w+\{([^,]+),", (ROOT / "paper/references.bib").read_text())
    require(len(commands) == len(set(commands)) == len(bib) == 66 and set(commands) == set(bib), "citation closure")
    require(not any("," in key for key in commands), "multi-key citation")
    for name in ["reference-verification.csv"]:
        rows = list(csv.DictReader((ROOT / "artifact/literature" / name).open()))
        require(len(rows) == 66 and {r["citation_key"] for r in rows} == set(commands), "reference review ledger mismatch")
    support = list(csv.DictReader((ROOT / "artifact/citation_support.csv").open()))
    require(len(support) == 66 and [r["citation_key"] for r in support] == commands, "local citation order ledger")
    require(all(r["main_tex_sha256"] == sha(ROOT / "paper/main.tex") for r in support), "citation source hash")
    require("\\bibliographystyle{IEEEtran}" in paper, "not standard citation-order IEEE style")
    authors = json.loads((ROOT / "artifact/author-metadata.json").read_text())
    require(authors["planned_slots"] == 6 and authors["identified_authors"] == 3, "author slot counts")
    require([a["name"] for a in authors["authors"][:3]] == ["Haoyi Zhang", "Huaijin Ran", "Xunzhu Tang"], "author order")
    require(all(a["name"] is None for a in authors["authors"][3:]), "invented reserved author")
    pdf_check = "unavailable: install PyMuPDF for PDF parse checks"
    try:
        import fitz
        for filename, expected in [("main", 14), ("supplement", 11)]:
            with fitz.open(ROOT / "paper" / f"{filename}.pdf") as doc:
                require(len(doc) == expected, f"page count: {filename}")
                for page in doc:
                    page.get_text("text")
        pdf_check = "14+11 pages parsed"
    except ImportError:
        pass
    test_result = "skipped by explicit flag"
    if not args.skip_tests:
        env = dict(os.environ, PYTHONDONTWRITEBYTECODE="1", PYTHONPATH=".")
        proc = subprocess.run([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-q"], cwd=ROOT / "artifact", env=env, text=True, capture_output=True, timeout=120)
        output = proc.stdout + proc.stderr
        require(proc.returncode == 0 and re.search(r"Ran 81 tests", output) is not None and "OK" in output, output)
        test_result = "81/81 PASS"
    require(before == records(), "verification modified the release tree")
    require(not list(ROOT.rglob("__pycache__")), "bytecode cache in release")
    print(json.dumps({"status": "PASS_ARTIFACT_INTEGRITY_NOT_SUBMISSION_APPROVAL",
                      "covered_files": len(covered), "execution_files": len(execution["entries"]),
                      "references": 66, "tests": test_result, "pdf": pdf_check,
                      "tree_unchanged": True, "authors": "3 named plus 3 blank slots",
                      "external_baseline": "not executed; see local_execution_gaps.json"}, indent=2))

if __name__ == "__main__":
    main()
