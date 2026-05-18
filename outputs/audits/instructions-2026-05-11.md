# Instruction-Quality Audit - AutoPR

**Date:** 2026-05-11
**Tool:** npx @reporails/cli check + agentic-workflow/guides/instruction-file-audit-rubric.md manual pass
**Mode:** Anonymous tier, deterministic rules only. Reporails OpenGrep install was repaired locally before this run because the installed opengrep.exe was a ZIP archive.
**Scope:** Root instruction surface for AutoPR; command/skill surfaces noted where present. No fixes applied in this audit report.

---

## Executive Summary

| Agent | Score | Level | Friction | Violations | High | Medium |
|-------|------:|-------|----------|-----------:|-----:|-------:|
| claude | n/a | n/a | n/a | n/a | n/a | n/a |
| codex | n/a | n/a | n/a | n/a | n/a | n/a |
| manual rubric | 45 / 100 | D | - | - | - | - |

**Manual rubric note:** Only a .claude command shim was found. For an active repo, add a root AGENTS.md/CLAUDE.md before expecting cross-agent work.

**Headline finding:** No root AGENTS.md/CLAUDE.md fallback, so non-Claude agents have no durable repo orientation.

---

## Pass 1 - Claude profile (`--agent claude`)

Not run or no score returned for this repo/surface.

## Pass 2 - Codex profile (`--agent codex`)

Not run or no score returned for this repo/surface.

## Pass 3 - Copilot profile (`--agent copilot`)

Not run or no score returned for this repo/surface.

## Pass 4 - Gemini profile (`--agent gemini`)

Not run or no score returned for this repo/surface.

## Pass 5 - Cursor profile (`--agent cursor`)

Not run or no score returned for this repo/surface.

## Pass 6 - Manual Rubric

| Surface | Manual assessment |
|---------|-------------------|
| Root/platform instructions | D (45/100): Only a .claude command shim was found. For an active repo, add a root AGENTS.md/CLAUDE.md before expecting cross-agent work. |
| Redundancy check | Thin adapters are acceptable when they point to a canonical file; duplicated full workflow prose should stay out of adapters. |

## 4 Cross-Pass Synthesis

| Count | Rule / finding |
|------:|----------------|
| 0 | No reporails rule results; command-only/manual audit. |

The same universal content rules dominate the automated output across the fleet. Treat Ask Not Guess, Has Boundaries, Has Constraints and Pitfalls, and Explain Reasoning as real candidate fixes. Treat broad Has X adapter findings as likely false positives when a thin adapter points to a canonical cross-agent guide.

## 5 False-Positive Candidates

Most reporails scoring is unavailable because there is no root instruction file; this is a coverage gap, not a false positive.

## 6 Recommended Fix Order

Batch 1: add root AGENTS.md. Batch 2: decide whether CLAUDE.md is needed. Batch 3: keep command shim pointing to canonical workflow.

## 7 Audit Log Entry

| 2026-05-11 | AutoPR: full surface | reporails scores in this report | D (45/100) | No root AGENTS.md/CLAUDE.md fallback, so non-Claude agents have no durable repo orientation. | Deferred |

## 8 Out of Scope

- No instruction fixes applied.
- No authenticated reporails run.
- No semantic LLM-only rules beyond the anonymous deterministic rule set.
- No commit or push from this report generation step.


