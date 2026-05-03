# Results

This directory contains the final aggregated evaluation results included in the public release.

## Main files

- `paper_main_tables.md`
  Main paper-facing result tables.
- `paper_all_tables.md`
  Extended table dump including ablations and appendix-style summaries.
- `oracle_materialization_summary.md`
  Unified oracle-evaluable subset summary.

## Important interpretation notes

- `OracleCoverage` is normalized to the unified oracle-evaluable subset.
- `Oracle ToolAcc` remains the per-model oracle-run score.
- High-level release docs use version-normalized paper counts; appendix-style `Papers` columns copied from raw evaluation artifacts may preserve raw stored `paper_id` counts.
- Human-audit artifacts are intentionally not distributed in this public release layer.
