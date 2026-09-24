"""Deterministic structural campaigns and finite witnesses."""
from __future__ import annotations

import hashlib
from copy import deepcopy
from itertools import product
from typing import Any

from .canonical import canonical_bytes, expression_binder
from .compiler import (
    AuthenticatedEnvelopeBackend,
    ContextMarkCompiler,
    ContextMarkError,
    MarkingError,
    make_demo_program,
)
from .threshold_backend import (
    CARRIER_FIELD,
    ThresholdCarrierAdapter,
    binder as threshold_binder,
    mark as threshold_mark,
    public_authorized_derivative,
    read as threshold_read,
)


def three_stage_fixture(*, backend=None, binder=expression_binder, chain_id: str = "campaign"):
    compiler = ContextMarkCompiler.deterministic(
        ["builder", "reviewer", "packager"],
        seed=20260718,
        chain_id=chain_id,
        backend=backend,
        binder=binder,
    )
    session = compiler.begin_session(make_demo_program(32))
    artifacts = []
    for index, actor in enumerate(("builder", "reviewer", "packager")):
        chain, artifact = session.append(
            actor=actor,
            operation=("compile", "review", "package")[index],
            metadata={"issue_id": f"c{index}", "policy": "v1"},
        )
        artifacts.append(deepcopy(artifact))
    return compiler, chain, artifact, artifacts


def _flip_hex(value: str) -> str:
    return ("0" if value[0] != "0" else "1") + value[1:]


def mutation_campaign() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    fields = ("version", "chain_id", "index", "parent", "binder", "actor", "operation", "metadata", "context", "signature")
    for position in range(3):
        for field in fields:
            compiler, chain, artifact, _ = three_stage_fixture(chain_id=f"mutation-record-{position}-{field}")
            candidate = deepcopy(chain)
            record = candidate[position]
            if field in {"version", "chain_id", "operation"}:
                record[field] = str(record[field]) + "-other"
            elif field == "index":
                record[field] = int(record[field]) + 4
            elif field == "parent":
                record[field] = "11" * 32
            elif field in {"binder", "context", "signature"}:
                record[field] = _flip_hex(str(record[field]))
            elif field == "actor":
                record[field] = "mallory"
            elif field == "metadata":
                record[field] = {**record[field], "changed": True}
            accepted = compiler.verify(candidate, artifact)
            rows.append({"case": f"record-{position}-{field}", "group": "record_field", "accepted": accepted, "rejected": not accepted})

    chain_cases = []
    compiler, chain, artifact, _ = three_stage_fixture(chain_id="mutation-chain")
    chain_cases.append(("empty", []))
    chain_cases.append(("truncated", deepcopy(chain[:-1])))
    chain_cases.append(("duplicate-tip", deepcopy(chain) + [deepcopy(chain[-1])]))
    chain_cases.append(("reordered", [deepcopy(chain[1]), deepcopy(chain[0]), deepcopy(chain[2])]))
    extra = deepcopy(chain); extra[1]["extra"] = True; chain_cases.append(("extra-field", extra))
    missing = deepcopy(chain); del missing[1]["operation"]; chain_cases.append(("missing-field", missing))
    nonrecord = [deepcopy(chain[0]), "not-a-record", deepcopy(chain[2])]; chain_cases.append(("nonrecord", nonrecord))
    for name, candidate in chain_cases:
        accepted = compiler.verify(candidate, artifact)
        rows.append({"case": name, "group": "chain_language", "accepted": accepted, "rejected": not accepted})

    artifact_cases: list[tuple[str, Any]] = []
    artifact_cases.append(("not-object", []))
    missing_env = deepcopy(artifact); missing_env.pop("_contextmark"); artifact_cases.append(("missing-envelope", missing_env))
    wrong_type = deepcopy(artifact); wrong_type["_contextmark"] = []; artifact_cases.append(("envelope-type", wrong_type))
    extra_env = deepcopy(artifact); extra_env["_contextmark"]["extra"] = True; artifact_cases.append(("envelope-extra", extra_env))
    missing_tag = deepcopy(artifact); del missing_tag["_contextmark"]["tag"]; artifact_cases.append(("envelope-missing-tag", missing_tag))
    wrong_backend = deepcopy(artifact); wrong_backend["_contextmark"]["backend"] = "other"; artifact_cases.append(("backend-version", wrong_backend))
    bad_payload = deepcopy(artifact); bad_payload["_contextmark"]["payload"] = "00"; artifact_cases.append(("payload-short", bad_payload))
    bad_tag = deepcopy(artifact); bad_tag["_contextmark"]["tag"] = _flip_hex(bad_tag["_contextmark"]["tag"]); artifact_cases.append(("tag-change", bad_tag))
    changed_host = deepcopy(artifact); changed_host["module"] = "other"; artifact_cases.append(("host-change", changed_host))
    transplant = make_demo_program(33); transplant["_contextmark"] = deepcopy(artifact["_contextmark"]); artifact_cases.append(("transplant", transplant))
    for name, candidate in artifact_cases:
        accepted = compiler.verify(chain, candidate)
        rows.append({"case": name, "group": "artifact", "accepted": accepted, "rejected": not accepted})

    if len(rows) != 47:
        raise AssertionError(f"mutation campaign size changed: {len(rows)}")
    return rows


def negative_control() -> dict[str, Any]:
    compiler, chain, artifact, _ = three_stage_fixture(chain_id="negative-control")
    deleted = deepcopy(artifact)
    before_binder = expression_binder(artifact)
    deleted.pop("_contextmark")
    return {
        "accepted_before": compiler.verify(chain, artifact),
        "accepted_after_deletion": compiler.verify(chain, deleted),
        "binder_equal": expression_binder(deleted) == before_binder,
        "attack_succeeds": not compiler.verify(chain, deleted),
    }


def coarse_binder_alias_witness() -> dict[str, Any]:
    def coarse(_program: dict[str, Any]) -> str:
        return "00" * 32

    compiler = ContextMarkCompiler.deterministic(
        ["builder"], seed=20260718, chain_id="coarse", binder=coarse, backend=AuthenticatedEnvelopeBackend(coarse)
    )
    compiler.issue([], {"program": "A"}, actor="builder", operation="compile", metadata={"issue_id": "same"})
    rejected = False
    try:
        compiler.issue([], {"program": "B"}, actor="builder", operation="compile", metadata={"issue_id": "same"})
    except ContextMarkError:
        rejected = True
    return {"same_binder_different_program_rejected": rejected, "status_counts": compiler.registry_status_counts()}


def terminal_failure_audit() -> dict[str, Any]:
    class FailingBackend:
        def __init__(self, fail: bool) -> None:
            self.fail = fail
            self.calls = 0
            self.delegate = AuthenticatedEnvelopeBackend(expression_binder)

        def mark(self, key: bytes, program: dict[str, Any], payload: str) -> dict[str, Any]:
            self.calls += 1
            if self.fail:
                raise RuntimeError("injected failure")
            return self.delegate.mark(key, program, payload)

        def read(self, key: bytes, artifact: dict[str, Any]) -> str | None:
            return self.delegate.read(key, artifact)

    failing = FailingBackend(True)
    compiler = ContextMarkCompiler.deterministic(
        ["builder"], seed=20260718, chain_id="terminal", backend=failing, max_contexts=1
    )
    request = dict(parent_chain=[], program=make_demo_program(8), actor="builder", operation="compile", metadata={"issue_id": "f0"})
    initial = retry = restored_retry = budget = False
    try:
        compiler.issue(**request)
    except MarkingError:
        initial = True
    calls_initial = failing.calls
    try:
        compiler.issue(**request)
    except MarkingError:
        retry = True
    calls_retry = failing.calls
    try:
        compiler.issue([], make_demo_program(9), actor="builder", operation="compile", metadata={"issue_id": "f1"})
    except ContextMarkError:
        budget = True
    snapshot = compiler.export_registry_snapshot()
    restored_backend = FailingBackend(False)
    restored = ContextMarkCompiler.deterministic(
        ["builder"], seed=20260718, chain_id="terminal", backend=restored_backend, max_contexts=1
    )
    restored.restore_registry_snapshot(snapshot)
    try:
        restored.issue(**request)
    except MarkingError:
        restored_retry = True
    return {
        "initial_failed": initial,
        "calls_after_initial": calls_initial,
        "retry_failed": retry,
        "calls_after_retry": calls_retry,
        "budget_rejected": budget,
        "restored_retry_failed": restored_retry,
        "restored_backend_calls": restored_backend.calls,
        "status_counts": restored.registry_status_counts(),
        "passed": initial and retry and budget and restored_retry and calls_initial == calls_retry == 1 and restored_backend.calls == 0,
    }


def resume_continuity_audit() -> dict[str, Any]:
    compiler = ContextMarkCompiler.deterministic(["builder", "packager"], seed=20260718, chain_id="resume")
    chain, artifact = compiler.issue([], make_demo_program(12), actor="builder", operation="compile", metadata={"issue_id": "r0"})
    snapshot = compiler.export_registry_snapshot()
    fresh = ContextMarkCompiler.deterministic(["builder", "packager"], seed=20260718, chain_id="resume")
    issue_rejected = resume_rejected = False
    try:
        fresh.issue(chain, artifact, actor="packager", operation="package", metadata={"issue_id": "r1"})
    except ContextMarkError:
        issue_rejected = True
    try:
        fresh.begin_session(chain=chain, artifact=artifact)
    except ContextMarkError:
        resume_rejected = True
    fresh.restore_registry_snapshot(snapshot)
    session = fresh.begin_session(chain=chain, artifact=artifact)
    chain2, artifact2 = session.append(actor="packager", operation="package", metadata={"issue_id": "r1"})
    return {
        "issue_without_registry_rejected": issue_rejected,
        "resume_without_registry_rejected": resume_rejected,
        "restored_continuation_accepted": fresh.verify(chain2, artifact2),
        "passed": issue_rejected and resume_rejected and fresh.verify(chain2, artifact2),
    }


def threshold_audit() -> dict[str, Any]:
    key = hashlib.sha256(b"threshold-audit-key").digest()
    base = make_demo_program(8)
    payloads = [hashlib.sha256(f"payload-{i}".encode()).digest() for i in range(3)]
    issued = threshold_mark(key, base, payloads[0], n=5, t=3)
    deletion_rows = []
    carriers = issued[CARRIER_FIELD]
    for bits in product((0, 1), repeat=5):
        candidate = deepcopy(issued)
        candidate[CARRIER_FIELD] = [deepcopy(carrier) for bit, carrier in zip(bits, carriers) if bit]
        recovered = threshold_read(key, candidate)
        expected = sum(bits) >= 3
        deletion_rows.append({
            "mask": "".join(map(str, bits)),
            "kept": sum(bits),
            "read_success": recovered == payloads[0],
            "expected_success": expected,
            "public_authorized": public_authorized_derivative(issued, candidate, threshold=3),
        })

    # One changed field for each carrier and field family: 5 carriers x 5 mutations.
    mutation_rows = []
    for position in range(5):
        for field in ("tag", "value", "index", "commitment", "version"):
            candidate = deepcopy(issued)
            carrier = candidate[CARRIER_FIELD][position]
            if field in {"tag", "commitment"}:
                carrier[field] = _flip_hex(carrier[field])
            elif field == "value":
                carrier[field] = format(int(carrier[field], 16) + 1, "x")
            elif field == "index":
                carrier[field] = 99
            else:
                carrier[field] = "other"
            mutation_rows.append({
                "position": position,
                "field": field,
                "still_reads": threshold_read(key, candidate) == payloads[0],
            })

    contributors = [threshold_mark(key, base, payload, n=4, t=3) for payload in payloads]
    two_cells = three_cells = bad_two = bad_three = canonical_multi = 0
    for masks in product(range(16), repeat=2):
        candidate = deepcopy(base); candidate[CARRIER_FIELD] = []
        present = []
        for group, mask in enumerate(masks):
            chosen = [c for index, c in enumerate(contributors[group][CARRIER_FIELD]) if mask & (1 << index)]
            candidate[CARRIER_FIELD].extend(deepcopy(chosen))
            if len(chosen) >= 3:
                present.append(payloads[group])
        result = threshold_read(key, candidate)
        if result is not None and result not in present:
            bad_two += 1
        if len(present) > 1 and result in present:
            canonical_multi += 1
        two_cells += 1
    for masks in product(range(16), repeat=3):
        candidate = deepcopy(base); candidate[CARRIER_FIELD] = []
        present = []
        for group, mask in enumerate(masks):
            chosen = [c for index, c in enumerate(contributors[group][CARRIER_FIELD]) if mask & (1 << index)]
            candidate[CARRIER_FIELD].extend(deepcopy(chosen))
            if len(chosen) >= 3:
                present.append(payloads[group])
        result = threshold_read(key, candidate)
        if result is not None and result not in present:
            bad_three += 1
        three_cells += 1
    return {
        "deletion_rows": deletion_rows,
        "single_mutation_rows": mutation_rows,
        "deletion_cases": len(deletion_rows),
        "single_mutation_cases": len(mutation_rows),
        "two_contributor_cells": two_cells,
        "three_contributor_cells": three_cells,
        "noncontributor_two": bad_two,
        "noncontributor_three": bad_three,
        "canonical_multi_candidate_returns": canonical_multi,
        "passed": all(row["read_success"] == row["expected_success"] == row["public_authorized"] for row in deletion_rows)
        and bad_two == 0 and bad_three == 0,
    }
