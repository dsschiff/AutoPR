# AutoPR Runbook (Windows + Anaconda PowerShell)

Quick “do this, then this” guide for running AutoPR on my machine.

**Repo path (example):**
`D:\Dropbox\Documents\Academics\Purdue\GitHub\AutoPR`

---

## 🚀 Quick Start (Common Scenarios)

### ⚠️ Note on Defaults & Required Flags
`batch_run.py` will **NOT** run anything unless you explicitly choose at least one stage. You must include one or more of: `--extract`, `--postprocess`, or `--push`.

**Default behaviors (if flags are omitted):**
* **Selection:** Processes *all* folders in `papers/` unless you use `--only` or `--project`.
* **Existing Files:** Overwrites everything unless you use `--skip-existing-outputs` or `--skip-existing-json`.
* **Stop on Error:** False (continues to next project) unless `--stop-on-error` is used.

### A) Standard Run (Recommended)
Do **ALL THREE** steps (extract → postprocess → push) for **ONLY** prefix `0012`.

    cd "D:\Dropbox\Documents\Academics\Purdue\GitHub\AutoPR"
    conda activate autopr

    python batch_run.py --extract --postprocess --push --only "0012" --skip-existing-outputs --skip-existing-json --sleep 1.5

### B) Dry Run
Prints commands but does **NOT** execute them.

    python batch_run.py --extract --postprocess --push --only "0012" --skip-existing-outputs --skip-existing-json --sleep 1.5 --dry-run

### C) Specific Project Folder
Target one exact project folder name (instead of a substring match).

    python batch_run.py --extract --postprocess --push --project "0012_James_2025_Extraction" --skip-existing-outputs --skip-existing-json --sleep 1.5

### D) Extract Only (No LLM rewrite, No Typefully)
Useful when you just want fresh `outputs/<project>/markdown.md` + `img/`.

    python batch_run.py --extract --only "0012" --skip-existing-outputs

### E) Postprocess Only (Rewrite)
Useful if extraction already exists and you just want new `platform_posts.json` + text files.

    python batch_run.py --postprocess --only "0012" --skip-existing-json

### F) Push Only (Typefully)
Useful if JSON already exists and you only want to publish.

    python batch_run.py --push --only "0012"

### G) Run ALL Papers (Careful!)
Runs selected stages for **everything** under `papers/`.

    python batch_run.py --extract --postprocess --push --skip-existing-outputs --skip-existing-json --sleep 1.5

---

## 0) Open the Right Terminal

Use: **Anaconda PowerShell Prompt**

## 1) Go to Repo & Activate Environment

    cd "D:\Dropbox\Documents\Academics\Purdue\GitHub\AutoPR"
    conda activate autopr
    python --version

## 2) Environment Variables / API Setup

### 2.1 `.env` (Recommended)
Keep a `.env` file in the repo root. Scripts load it via `python-dotenv`.

**Typical entries:**

    OPENAI_BASE_URL="https://api.poe.com/v1"
    OPENAI_API_KEY="YOUR_KEY_HERE"
    POSTPROCESS_MODEL="Claude-Sonnet-4"

    TWITTER_HANDLE=Dan_Schiff
    LINKEDIN_SLUG=daniel-schiff
    BLUESKY_HANDLE=dschiff.bsky.social
    AUTHOR_NAME=Daniel Schiff

    TYPEFULLY_API_KEY="YOUR_TYPEFULLY_KEY"
    TYPEFULLY_SOCIAL_SET_ID="142783"

> **Note:** If you edit `.env`, restart the terminal so the new env vars are picked up.

### 2.2 Temp Path Shortening (Windows Safety)
For big batch jobs, set a short temp root to avoid Windows path-length errors:

    $env:AUTOPR_TEMP = "D:\aprtmp"
    New-Item -ItemType Directory -Path "D:\aprtmp" -Force | Out-Null

## 3) Step 1 — Extraction (PRAgent)

**Input Structure:**

    papers/
    ├── 0000__Some_Paper/
    │   └── paper.pdf
    └── 0012_James_2025_Extraction/
        └── paper.pdf

**Output Structure:**

    outputs<project>/
    ├── markdown.md
    ├── img/
    └── ...

**Manual Extract (Single Project):**

    python -m pragent.run --input-dir ".\papers\0012_James_2025_Extraction" --output-dir ".\outputs" --model-path ".\models\doclayout_yolo_docstructbench_imgsz1024.pt" --concurrency 1 --post-format rich

> **Notes:**
> * `--concurrency 1` is safest while debugging.
> * `--post-format rich` is usually what you want.

## 4) URL Mapping (`paper_urls.csv`)

`postprocess.py` uses `paper_urls.csv` in the repo root to map `prefix` → `url` (+ optional `venue`).

**Expected Columns:**
`prefix,url,venue`

**Example Rows:**

    0000,https://doi.org/10.1177/20539517241299732,Big Data & Society
    0001,https://www.sciencedirect.com/science/article/pii/S2666920X24001437,Computers and Education: Artificial Intelligence

> **Important:**
> * Prefixes must match the **first 4 chars** of the output folder name (e.g., `0000__...`).
> * If a prefix is missing, `postprocess.py` will fail for that project.

## 5) Step 2 — Postprocess (Socials)

`postprocess.py` reads `markdown.md` and generates social content **in place** within the same folder.

**Generated Files:**
* `outputs<project>\platform_posts.json`
* `outputs<project>\twitter_typefully.txt`
* `outputs<project>\bluesky_thread.txt`
* `outputs<project>\linkedin_post.txt`

**Manual Postprocess (Single Project):**

    python postprocess.py --project "0012_James_2025_Extraction"

**Manual Postprocess (Latest Output Folder):**

    python postprocess.py --latest

## 6) Step 3 — Push to Typefully (API)

**List social sets (to confirm your ID):**

    python typefully_push.py --list-social-sets

**Push one project JSON:**

    python typefully_push.py --json ".\outputs\0012_James_2025_Extraction\platform_posts.json"

## 7) One-Command Batching (`batch_run.py`)

`batch_run.py` can orchestrate all three steps per project:
1.  Extract (`python -m pragent.run`)
2.  Postprocess (`python postprocess.py`)
3.  Push (`python typefully_push.py`)

**Run all steps for ONLY "0012" (substring match):**

    python batch_run.py --extract --postprocess --push --only "0012" --skip-existing-outputs --skip-existing-json --sleep 1.5

**Run all steps for one exact project folder:**

    python batch_run.py --extract --postprocess --push --project "0012_James_2025_Extraction" --skip-existing-outputs --skip-existing-json --sleep 1.5

**Useful Batch Flags:**
* `--skip-existing-outputs`: Skip extraction if `markdown.md` exists.
* `--skip-existing-json`: Skip postprocess if `platform_posts.json` exists.
* `--stop-on-error`: Stop at the first failure.
* `--max 10`: Only do the first N matches.
* `--dry-run`: Print commands only.

## 8) Manual Posting (Fallback)

If the API fails, open these text files and copy/paste:

* **Twitter/X:** Open `twitter_typefully.txt`. Attach images manually from the `img` folder.
* **Bluesky:** Open `bluesky_thread.txt`.
* **LinkedIn:** Open `linkedin_post.txt`.

## 9) Troubleshooting Quick Hits

### Missing URL for prefix (postprocess fails)
* Add the row to `paper_urls.csv` (must include URL).
* Ensure the prefix matches the folder name (first 4 chars).

### Typefully 401 Unauthorized
* Confirm `TYPEFULLY_API_KEY` is correct in `.env` and loaded.
* Confirm `TYPEFULLY_SOCIAL_SET_ID` is set.

### Windows Path-Length Errors
* Ensure `AUTOPR_TEMP` is set to a short path (e.g., `D:\aprtmp`).
* Avoid deeply nested folders or very long project names.

### pragent.run says “No project subfolders found”
* `--input-dir` expects a directory *containing* project subfolders, OR a single project folder that contains a PDF directly. Check your directory nesting.