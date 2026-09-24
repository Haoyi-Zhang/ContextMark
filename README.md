# TDSC-01 executable artifact

The artifact checks implementation correspondences for the context-bound lineage compiler, finite threshold carrier, predictable risk bounds, and recovery discipline. It is not a production watermark or proof-assistant development.

## Run

From `artifact/`:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python -m unittest discover -s tests -q
```

The complete experiment driver is:

```bash
PYTHONDONTWRITEBYTECODE=1 PYTHONPATH=. python run_experiments.py
```

The deterministic suite and structural checks must reproduce exactly. CPU timing will vary across hosts. Do not delete slow samples, fit a complexity curve, or extrapolate beyond the measured depths.

## Structure

- `contextmark/`: canonicalization, compiler, carrier, risk, finite model, and assurance checks.
- `tests/`: deterministic interface, boundary, and regression checks.
- `results/raw/`: direct outputs and sample-level evidence.
- `results/derived/`: tables consumed by the manuscript figures.
- `literature/`: bibliography and novelty-boundary ledgers.
- `external/`: pinned external-resource metadata and source-inspection records.
- `claim_evidence_ledger.csv`, `correctness_correspondence.csv`, and `results_manifest.csv`: claim-to-evidence bindings.

## Limits

The finite carrier is visible and language-bounded. The envelope is intentionally removable. The attack lattice is a frozen factorized model, not a distribution over real attackers. The probability grid is a diagnostic; uniform validity comes from the theorem. in-toto was inspected at the source/interface level but was not executed locally because its pinned dependency could not be acquired in this environment.
