#!/usr/bin/env python3
"""Predeclared CPU-only evidence driver for TDSC-01."""
from __future__ import annotations

import csv
import hashlib
import json
import os
import platform
import shutil
import statistics
import subprocess
import sys
import time
from pathlib import Path
from typing import Any, Iterable

import cryptography

from contextmark.bounds import (
    PrimitiveRates,
    closed_form_union,
    enumerate_union_probability,
    independent_model,
    query_caps,
    theorem_bound,
)
from contextmark.calibration import coverage_grid, equal_marginal_history_counterexample
from contextmark.campaigns import (
    mutation_campaign,
    negative_control,
    resume_continuity_audit,
    terminal_failure_audit,
    threshold_audit,
)
from contextmark.compiler import ContextMarkCompiler, make_demo_program
from contextmark.assurance_checks import assurance_checks
from contextmark.finite_model import (
    baseline_matrix,
    omission_matrix,
    safeguard_lattice,
    validate_omission_matrix,
    validate_safeguard_lattice,
)
from contextmark.threshold_backend import ThresholdCarrierAdapter, binder as threshold_binder

ROOT = Path(__file__).resolve().parent
RAW = ROOT / "results" / "raw"
DERIVED = ROOT / "results" / "derived"
SEED = 20260718
GAMES = ("removal", "nontransfer", "unforgeability", "collusion")
EXPECTED_TESTS = 81


def write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, indent=2, sort_keys=True) + "\n", encoding="utf-8")


def write_csv(path: Path, rows: Iterable[dict[str, Any]], fieldnames: list[str] | None = None) -> None:
    rows = list(rows)
    if fieldnames is None:
        if not rows:
            raise ValueError("cannot infer fields from empty rows")
        fieldnames = list(rows[0])
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def percentile(values: list[float], fraction: float) -> float:
    ordered = sorted(values)
    if not ordered:
        raise ValueError("empty sample")
    index = max(0, min(len(ordered) - 1, int((len(ordered) * fraction + 0.999999999)) - 1))
    return ordered[index]


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1 << 20), b""):
            h.update(block)
    return h.hexdigest()


def run_tests() -> dict[str, Any]:
    command = [sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"]
    completed = subprocess.run(
        command,
        cwd=ROOT,
        env={**os.environ, "PYTHONPATH": str(ROOT), "PYTHONDONTWRITEBYTECODE": "1"},
        capture_output=True,
        text=True,
        check=False,
    )
    output = completed.stdout + completed.stderr
    (RAW / "test-output.txt").write_text(output, encoding="utf-8")
    marker = f"Ran {EXPECTED_TESTS} tests"
    valid = completed.returncode == 0 and marker in output and output.rstrip().endswith("OK")
    summary = {
        "command": "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m unittest discover -s tests -v",
        "deterministic_test_count": EXPECTED_TESTS,
        "passed": EXPECTED_TESTS if valid else 0,
        "failed": 0 if valid else 1,
        "returncode": completed.returncode,
        "valid": valid,
    }
    write_json(RAW / "test-summary.json", summary)
    if not valid:
        raise RuntimeError("unit test contract failed")
    return summary


def environment_record() -> dict[str, Any]:
    cpu_model = "unknown"
    cpuinfo = Path("/proc/cpuinfo")
    if cpuinfo.exists():
        for line in cpuinfo.read_text(errors="replace").splitlines():
            if line.lower().startswith("model name"):
                cpu_model = line.split(":", 1)[1].strip()
                break
    return {
        "timestamp_utc": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        "seed": SEED,
        "python": platform.python_version(),
        "python_implementation": platform.python_implementation(),
        "cryptography": cryptography.__version__,
        "platform": platform.platform(),
        "machine": platform.machine(),
        "cpu_model": cpu_model,
        "logical_cpu_count": os.cpu_count(),
        "gpu_used": False,
        "model_api_used": False,
        "learned_model_used": False,
        "private_data_used": False,
        "human_evidence_used": False,
    }


def run_structural_campaigns() -> dict[str, Any]:
    mutations = mutation_campaign()
    write_csv(RAW / "mutation-campaign.csv", mutations)
    mutation_summary = {
        "case_count": len(mutations),
        "record_field_cases": sum(row["group"] == "record_field" for row in mutations),
        "chain_language_cases": sum(row["group"] == "chain_language" for row in mutations),
        "artifact_cases": sum(row["group"] == "artifact" for row in mutations),
        "rejected": sum(row["rejected"] for row in mutations),
        "valid": len(mutations) == 47 and all(row["rejected"] for row in mutations),
    }
    write_json(RAW / "mutation-campaign-summary.json", mutation_summary)

    omission = omission_matrix()
    omission_summary = validate_omission_matrix(omission)
    write_csv(RAW / "finite-attack-harness.csv", omission)
    write_json(RAW / "finite-attack-harness-summary.json", omission_summary)

    lattice = safeguard_lattice()
    lattice_summary = validate_safeguard_lattice(lattice)
    write_csv(RAW / "safeguard-lattice.csv", lattice)
    write_json(RAW / "safeguard-lattice-summary.json", lattice_summary)

    baselines = baseline_matrix()
    write_csv(RAW / "architecture-baselines.csv", baselines)
    baseline_counts = {
        name: sum(row["attack_succeeds"] for row in baselines if row["configuration"] == name)
        for name in ("detached_records", "host_bound_owner_mark", "signed_owner_mark", "context_mark_without_parents", "complete")
    }
    write_json(RAW / "architecture-baseline-summary.json", baseline_counts)

    threshold = threshold_audit()
    deletion_rows = threshold.pop("deletion_rows")
    mutation_rows = threshold.pop("single_mutation_rows")
    write_csv(RAW / "threshold-deletion-authorization.csv", deletion_rows)
    write_csv(RAW / "threshold-single-mutations.csv", mutation_rows)
    write_json(RAW / "threshold-audit-summary.json", threshold)

    terminal = terminal_failure_audit()
    resume = resume_continuity_audit()
    negative = negative_control()
    write_json(RAW / "terminal-failure-registry-audit.json", terminal)
    write_json(RAW / "resume-registry-continuity-audit.json", resume)
    write_json(RAW / "negative-control-envelope-deletion.json", negative)

    if not (mutation_summary["valid"] and omission_summary["valid"] and lattice_summary["valid"] and threshold["passed"] and terminal["passed"] and resume["passed"] and negative["attack_succeeds"]):
        raise RuntimeError("structural campaign failed")
    return {
        "mutation_campaign": mutation_summary,
        "finite_attack_harness": omission_summary,
        "safeguard_lattice": lattice_summary,
        "architecture_baseline_success_counts": baseline_counts,
        "threshold_audit": threshold,
        "terminal_failure_registry": terminal,
        "resume_registry_continuity": resume,
        "negative_control": negative,
    }


def run_exact_probability_checks() -> list[dict[str, Any]]:
    rows = []
    for event_count in (4, 8, 12, 16, 20):
        probabilities = [1e-6 * (index + 1) for index in range(event_count)]
        enumerated, states, elapsed_ms = enumerate_union_probability(probabilities)
        closed = closed_form_union(probabilities)
        rows.append({
            "event_count": event_count,
            "states_enumerated": states,
            "enumerated_probability": f"{enumerated:.18g}",
            "closed_form_probability": f"{closed:.18g}",
            "absolute_error": f"{abs(enumerated - closed):.18g}",
            "elapsed_ms": f"{elapsed_ms:.6f}",
        })
    write_csv(RAW / "exact-probability-checks.csv", rows)
    if int(rows[-1]["states_enumerated"]) != 1_048_576 or max(float(row["absolute_error"]) for row in rows) > 1e-12:
        raise RuntimeError("exact probability check failed")
    return rows


def run_calibration_checks() -> dict[str, Any]:
    rows = coverage_grid((index / 100 for index in range(1, 100)), horizon=64, alpha=0.05)
    write_csv(DERIVED / "optional-stopping-coverage.csv", rows)
    fixed_max = max(rows, key=lambda row: row["fixed_level_noncoverage"])
    anytime_max = max(rows, key=lambda row: row["anytime_noncoverage"])
    counterexample = equal_marginal_history_counterexample()
    write_json(RAW / "equal-marginal-history-counterexample.json", counterexample)
    summary = {
        "horizon": 64,
        "family_alpha": 0.05,
        "grid_points": len(rows),
        "fixed_level_max_noncoverage": fixed_max["fixed_level_noncoverage"],
        "fixed_level_argmax_probability": fixed_max["true_probability"],
        "anytime_max_noncoverage": anytime_max["anytime_noncoverage"],
        "anytime_argmax_probability": anytime_max["true_probability"],
        "analytic_anytime_upper_bound": 0.05,
        "equal_marginal_counterexample": counterexample,
        "valid": fixed_max["fixed_level_noncoverage"] > 0.1 and anytime_max["anytime_noncoverage"] <= 0.05 + 1e-12,
    }
    write_json(RAW / "optional-stopping-summary.json", summary)
    if not summary["valid"]:
        raise RuntimeError("calibration audit failed")
    return summary


def run_bound_curves() -> dict[str, Any]:
    rates = PrimitiveRates()
    q_values = (1, 2, 4, 8, 16, 32, 64, 128, 256)
    rows = []
    for game in GAMES:
        game_rows = []
        for q in q_values:
            n = 4 * q
            theorem = theorem_bound(game, q, n, rates)
            independent = independent_model(game, q, n, rates)
            if theorem + 1e-15 < independent:
                raise RuntimeError("bound curve is not conservative")
            row = {
                "game": game,
                "queries": q,
                "records": n,
                "theorem_bound": theorem,
                "independent_model": independent,
            }
            game_rows.append(row)
            rows.append(row)
        write_csv(DERIVED / f"security-{game}.csv", game_rows)
    caps = query_caps(4.0, 0.01, rates)
    inputs = {
        "rates": rates.as_dict(),
        "records_per_context": 4.0,
        "target_probability": 0.01,
        "integer_query_caps": caps,
    }
    write_json(RAW / "bound-inputs-and-caps.json", inputs)
    write_csv(DERIVED / "query-caps.csv", [{"game": game, "integer_query_cap": value} for game, value in caps.items()])
    return inputs


def build_session_chain(chain_length: int, sample: int):
    actors = ["builder", "reviewer", "packager", "release"]
    compiler = ContextMarkCompiler.deterministic(actors, seed=SEED, chain_id=f"session-{chain_length}-{sample}")
    session = compiler.begin_session(make_demo_program(16))
    started = time.perf_counter_ns()
    for index in range(chain_length):
        session.append_private(
            actor=actors[index % len(actors)],
            operation=f"stage-{index}",
            metadata={"issue_id": f"s-{chain_length}-{sample}-{index}", "policy": "v1"},
        )
    elapsed_us = (time.perf_counter_ns() - started) / 1000
    chain, artifact = session.snapshot()
    return compiler, chain, artifact, elapsed_us


def build_replay_chain(chain_length: int, sample: int):
    actors = ["builder", "reviewer", "packager", "release"]
    compiler = ContextMarkCompiler.deterministic(actors, seed=SEED, chain_id=f"replay-{chain_length}-{sample}")
    chain: list[dict[str, Any]] = []
    artifact = make_demo_program(16)
    started = time.perf_counter_ns()
    for index in range(chain_length):
        chain, artifact = compiler.issue(
            chain,
            artifact,
            actor=actors[index % len(actors)],
            operation=f"stage-{index}",
            metadata={"issue_id": f"r-{chain_length}-{sample}-{index}", "policy": "v1"},
        )
    elapsed_us = (time.perf_counter_ns() - started) / 1000
    return compiler, chain, artifact, elapsed_us


def run_compiler_benchmark() -> list[dict[str, Any]]:
    chain_lengths = (1, 2, 4, 8, 16, 32, 64, 128, 256, 512, 1024, 2048)
    aggregate = []
    samples = []
    for length in chain_lengths:
        print(f"benchmark depth={length}", flush=True)
        session_total = []
        session_per_stage = []
        for sample in range(31):
            _compiler, chain, artifact, elapsed_us = build_session_chain(length, sample)
            session_total.append(elapsed_us)
            session_per_stage.append(elapsed_us / length)
            samples.append({"chain_length": length, "sample_kind": "validated_tip_total", "sample_index": sample, "elapsed_us": elapsed_us})
        replay_total = []
        if length <= 256:
            for sample in range(7):
                _compiler, chain, artifact, elapsed_us = build_replay_chain(length, sample)
                replay_total.append(elapsed_us)
                samples.append({"chain_length": length, "sample_kind": "full_prefix_replay_total", "sample_index": sample, "elapsed_us": elapsed_us})
        compiler, chain, artifact, _ = build_session_chain(length, 999)
        for _ in range(10):
            if not compiler.verify(chain, artifact):
                raise RuntimeError("warm-up verification failed")
            compiler.serialize_manifest(chain)
        verify = []
        serialize = []
        for sample in range(31):
            started = time.perf_counter_ns()
            accepted = compiler.verify(chain, artifact)
            elapsed = (time.perf_counter_ns() - started) / 1000
            if not accepted:
                raise RuntimeError("benchmark verification failed")
            verify.append(elapsed)
            samples.append({"chain_length": length, "sample_kind": "verify", "sample_index": sample, "elapsed_us": elapsed})
            started = time.perf_counter_ns()
            manifest = compiler.serialize_manifest(chain)
            elapsed = (time.perf_counter_ns() - started) / 1000
            serialize.append(elapsed)
            samples.append({"chain_length": length, "sample_kind": "serialize", "sample_index": sample, "elapsed_us": elapsed})
        row = {
            "chain_length": length,
            "session_samples": len(session_total),
            "median_validated_tip_total_us": statistics.median(session_total),
            "p95_validated_tip_total_us": percentile(session_total, 0.95),
            "median_validated_tip_us_per_stage": statistics.median(session_per_stage),
            "replay_samples": len(replay_total),
            "median_replay_total_us": statistics.median(replay_total) if replay_total else "",
            "replay_to_tip_speedup": (statistics.median(replay_total) / statistics.median(session_total)) if replay_total else "",
            "verify_samples": len(verify),
            "median_verify_us": statistics.median(verify),
            "p95_verify_us": percentile(verify, 0.95),
            "serialize_samples": len(serialize),
            "median_serialize_us": statistics.median(serialize),
            "p95_serialize_us": percentile(serialize, 0.95),
            "manifest_bytes": len(manifest),
            "artifact_bytes": len(compiler.serialize_artifact(artifact)),
            "all_verifications_passed": True,
        }
        aggregate.append(row)
    write_csv(RAW / "compiler-scaling-samples.csv", samples)
    write_csv(DERIVED / "compiler-scaling.csv", aggregate)
    write_csv(DERIVED / "compiler-replay-scaling.csv", [row for row in aggregate if row["replay_samples"]])
    return aggregate


def run_threshold_timing() -> list[dict[str, Any]]:
    rows = []
    base = make_demo_program(16)
    for groups in (1, 2, 3):
        mark_times = []
        read_times = []
        for sample in range(31):
            adapter = ThresholdCarrierAdapter(n=5, t=3)
            compiler = ContextMarkCompiler.deterministic(
                ["builder"],
                seed=SEED + sample,
                chain_id=f"threshold-timing-{groups}-{sample}",
                binder=threshold_binder,
                backend=adapter,
            )
            artifact = base
            key = hashlib.sha256(f"timing-key-{sample}".encode()).digest()
            started = time.perf_counter_ns()
            for group in range(groups):
                payload = hashlib.sha256(f"timing-payload-{sample}-{group}".encode()).hexdigest()
                artifact = adapter.mark(key, artifact, payload)
            mark_times.append((time.perf_counter_ns() - started) / 1000)
            started = time.perf_counter_ns()
            recovered = adapter.read(key, artifact)
            read_times.append((time.perf_counter_ns() - started) / 1000)
            if recovered is None:
                raise RuntimeError("threshold timing read failed")
        rows.append({
            "payload_groups": groups,
            "samples": 31,
            "median_mark_total_us": statistics.median(mark_times),
            "p95_mark_total_us": percentile(mark_times, 0.95),
            "median_read_us": statistics.median(read_times),
            "p95_read_us": percentile(read_times, 0.95),
        })
    write_csv(DERIVED / "threshold-carrier-timing.csv", rows)
    return rows


def build_run_manifest() -> dict[str, Any]:
    manifest_path = RAW / "run-manifest.json"
    paths = [ROOT / "requirements.txt", ROOT / "run_experiments.py"]
    paths.extend((ROOT / "contextmark").glob("*.py"))
    paths.extend((ROOT / "tests").glob("*.py"))
    paths.extend(path for path in (ROOT / "results").rglob("*") if path.is_file() and path != manifest_path)
    entries = []
    for path in sorted(set(paths), key=lambda p: p.relative_to(ROOT).as_posix()):
        entries.append({
            "path": path.relative_to(ROOT).as_posix(),
            "bytes": path.stat().st_size,
            "sha256": sha256_file(path),
        })
    manifest = {
        "schema": "contextmark-run-manifest",
        "seed": SEED,
        "command": "PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python run_experiments.py",
        "entry_count": len(entries),
        "entries": entries,
    }
    write_json(manifest_path, manifest)
    return manifest


def main() -> int:
    for directory in (RAW, DERIVED):
        if directory.exists():
            shutil.rmtree(directory)
        directory.mkdir(parents=True)
    environment = environment_record()
    write_json(RAW / "environment.json", environment)
    tests = run_tests()
    structural = run_structural_campaigns()
    exact = run_exact_probability_checks()
    calibration = run_calibration_checks()
    assurance = assurance_checks()
    if not assurance["passed"]:
        raise RuntimeError("assurance regression campaign failed")
    write_json(RAW / "proof-implementation-checks.json", assurance)
    bounds = run_bound_curves()
    scaling = run_compiler_benchmark()
    threshold_timing = run_threshold_timing()
    summary = {
        "schema": "contextmark-experiment-summary",
        "environment": environment,
        "tests": tests,
        "structural_campaigns": structural,
        "exact_probability_max_error": max(float(row["absolute_error"]) for row in exact),
        "exact_probability_m20_elapsed_ms": float(exact[-1]["elapsed_ms"]),
        "calibration": calibration,
        "query_caps": bounds["integer_query_caps"],
        "compiler_scaling": scaling,
        "threshold_timing": threshold_timing,
        "assurance_checks": {k: v for k, v in assurance.items() if k not in {"closure_rows", "threshold_parameter_pairs"}},
    }
    write_json(RAW / "run-summary.json", summary)
    manifest = build_run_manifest()
    print(json.dumps(summary, indent=2, sort_keys=True))
    print(f"run_manifest_entries={manifest['entry_count']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
