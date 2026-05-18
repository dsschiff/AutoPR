# Agent Guide

This repository is a local working copy of AutoPR / PRAgent plus Daniel-specific
paper-promotion experiments.

## Purpose

AutoPR turns academic papers into public-facing promotional content for social
platforms. The upstream implementation lives around `pragent/`, `eval/`, and the
shell scripts under `script/`. Daniel-specific ingestion and posting helpers live
at the root and in `postprocessed/`.

## Entry Points

- `README.md`: upstream project overview, installation, and benchmark workflow.
- `README-Daniel.md`: local Daniel-specific workflow notes.
- `app.py`: local app entry point.
- `ingest_paper.py`, `postprocess.py`, `typefully_explore.py`,
  `typefully_push.py`: local promotion workflow helpers.
- `script/run_generation.sh`, `script/run_eval.sh`, `script/calc_results.sh`:
  upstream benchmark scripts.

## Commands

- Install dependencies with `pip install -r requirements.txt`.
- Run local Python helpers directly from the repository root.
- Keep API keys and model endpoints in `.env`; never commit real credentials.

## Working Rules

- Preserve upstream structure unless a local Daniel workflow explicitly needs a
  small adaptation.
- Treat `papers/`, `outputs/`, `postprocessed/`, and `batch_run.log` as
  generated or data-heavy surfaces. Do not bulk rewrite them without a clear
  task.
- Prefer small, reviewable edits to root helpers and documentation before
  changing benchmark internals.
- When editing generated social posts, keep claims faithful to the source paper
  and preserve platform-specific formatting constraints.

## Validation

There is no single enforced test harness. Validate the specific path touched:

- For dependency/import changes, run the affected Python module with `--help` or
  a dry-run input when available.
- For benchmark changes, use the relevant script under `script/`.
- For documentation-only changes, inspect the rendered Markdown structure and
  run `git diff --check`.
