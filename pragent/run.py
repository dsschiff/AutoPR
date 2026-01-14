# run.py
import argparse
import asyncio
import hashlib
import json
import os
import shutil
import time
import traceback
from pathlib import Path
from typing import Optional, List

from tqdm.asyncio import tqdm

from pragent.backend.text_pipeline import pipeline as run_text_extraction
from pragent.backend.figure_table_pipeline import run_figure_extraction
from pragent.backend.blog_pipeline import generate_text_blog, generate_final_post, generate_baseline_post


# -----------------------------
# Utilities
# -----------------------------

def env_first(*keys: str, fallback: Optional[str] = None) -> Optional[str]:
    """Return first non-empty env var among keys, else fallback."""
    for k in keys:
        v = os.getenv(k)
        if v and v.strip():
            return v.strip()
    return fallback


def get_pdf_hash(file_path: Path) -> str:
    """Calculates the SHA256 hash of a file's content."""
    h = hashlib.sha256()
    with file_path.open("rb") as f:
        for chunk in iter(lambda: f.read(8192), b""):
            h.update(chunk)
    return h.hexdigest()


def create_output_package(base_dir: Path, md_content: str, assets: list):
    """
    Creates a folder with the markdown file and an 'img' subfolder for assets.
    """
    tqdm.write(f"[*] Packaging final post at: {base_dir}")
    if base_dir.exists():
        shutil.rmtree(base_dir)
    base_dir.mkdir(parents=True, exist_ok=True)

    (base_dir / "markdown.md").write_text(md_content, encoding="utf-8")

    if assets:
        assets_dir = base_dir / "img"
        assets_dir.mkdir(exist_ok=True)
        for asset_info in assets:
            src_path = Path(asset_info["src_path"])
            dest_path = assets_dir / asset_info["dest_name"]
            if src_path.exists():
                shutil.copy(src_path, dest_path)
        tqdm.write(f"[*] Copied {len(assets)} assets to {assets_dir}")
    else:
        tqdm.write("[*] No assets to package for this post.")


def _contains_pdf(folder: Path) -> bool:
    try:
        return any(folder.glob("*.pdf"))
    except Exception:
        return False


def _depth_from(root: Path, child: Path) -> int:
    """Depth in directories between root and child (root child => 1, etc.)."""
    try:
        rel = child.relative_to(root)
        return len(rel.parts)
    except Exception:
        return 10**9


def discover_project_folders(
    input_dir: Path,
    project: Optional[str] = None,
    prefix: Optional[str] = None,
    max_depth: int = 6,
) -> List[Path]:
    """
    Find project folders under input_dir.

    Rules:
    - If input_dir itself contains a PDF => treat as a single project folder.
    - Else recursively find folders (up to max_depth) that contain a PDF.
    - Optional filters:
        * project: exact folder name match
        * prefix: matches folder name starting with zero-padded 4-digit prefix (e.g., 12 -> 0012)
    """
    input_dir = input_dir.resolve()

    if not input_dir.is_dir():
        raise FileNotFoundError(f"Input directory not found: {input_dir}")

    # If user points directly at a project folder containing PDFs, accept it
    if _contains_pdf(input_dir):
        candidates = [input_dir]
    else:
        candidates = []
        for d in input_dir.rglob("*"):
            if not d.is_dir():
                continue
            if d.name.startswith("."):
                continue
            if d.name in (".temp", ".temp_output", ".cache"):
                continue

            if _depth_from(input_dir, d) > max_depth:
                continue

            if _contains_pdf(d):
                candidates.append(d)

        candidates.sort(key=lambda p: str(p).lower())

    if project:
        candidates = [c for c in candidates if c.name == project]

    if prefix:
        pfx = prefix.strip()
        if pfx.isdigit():
            pfx = pfx.zfill(4)
        candidates = [c for c in candidates if c.name.startswith(pfx)]

    return candidates


def safe_copytree(src: Path, dst: Path) -> None:
    """
    Copytree that won't explode if dst exists.
    Python 3.8+ supports dirs_exist_ok, but we keep it explicit.
    """
    if dst.exists():
        shutil.rmtree(dst, ignore_errors=True)
    shutil.copytree(src, dst)


# -----------------------------
# Core pipeline
# -----------------------------

async def process_single_project(project_path: Path, args: argparse.Namespace, platform: str, language: str):
    """
    Runs the full pipeline for a single project folder.
    """
    original_project_name = project_path.name
    project_name = original_project_name
    post_format = args.post_format
    ablation_mode = args.ablation

    if ablation_mode != "none":
        project_name = f"{original_project_name}_ablation_{ablation_mode}"
        tqdm.write("\n" + "=" * 80)
        tqdm.write(f"🚀 Starting ABLATION processing for project: {original_project_name}")
        tqdm.write(f"   (Ablation Mode: {ablation_mode}, Platform: {platform}, Format: {post_format}, Language: {language})")
        tqdm.write("=" * 80)
    else:
        tqdm.write("\n" + "=" * 80)
        tqdm.write(f"🚀 Starting processing for project: {project_name} (Platform: {platform}, Format: {post_format}, Language: {language})")
        tqdm.write("=" * 80)

    pdf_files = list(project_path.glob("*.pdf"))
    if not pdf_files:
        tqdm.write(f"[!] No PDF file found in '{project_path}'. Skipping.")
        return
    pdf_path = pdf_files[0]

    session_id = f"session_{int(time.time())}_{project_name}"
    work_dir = Path(args.output_dir) / ".temp" / session_id
    final_output_dir = Path(args.output_dir) / project_name
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        tqdm.write("\n--- Stage 1/4: Extracting Text from PDF ---")
        txt_output_path = work_dir / f"{project_name}.txt"
        await run_text_extraction(str(pdf_path), str(txt_output_path), ablation_mode=ablation_mode)
        if not txt_output_path.exists():
            tqdm.write(f"[!] Text extraction failed for {pdf_path.name}. Skipping.")
            return
        tqdm.write("[✓] Text extracted successfully.")

        tqdm.write("\n--- Stage 2/4: Extracting Figures ---")
        pdf_hash = None
        paired_dir = None

        if post_format in ("rich", "description_only"):
            cached_figures_path = None
            if args.cache_dir:
                pdf_hash = get_pdf_hash(pdf_path)
                cached_figures_path = args.cache_dir / "figures" / pdf_hash
                if cached_figures_path.exists() and any(cached_figures_path.iterdir()):
                    tqdm.write(f"[✓] Cache hit for figures '{pdf_path.name}'.")
                    paired_dir = str(cached_figures_path)

            if not paired_dir:
                if args.cache_dir:
                    tqdm.write(f"[*] Cache miss for figures '{pdf_path.name}'. Running extraction.")
                extraction_work_dir = work_dir / "figure_extraction"
                extraction_work_dir.mkdir()
                paired_dir = run_figure_extraction(str(pdf_path), str(extraction_work_dir), args.model_path)

                if paired_dir and cached_figures_path:
                    tqdm.write(f"[*] Caching extracted figures to: {cached_figures_path}")
                    safe_copytree(Path(paired_dir), cached_figures_path)

            has_figures = bool(paired_dir) and any(Path(paired_dir).rglob("paired_*"))
            if not has_figures:
                tqdm.write(f"[!] Warning: No paired figures found for format '{post_format}'.")
                tqdm.write("[*] Switching to 'text_only'.")
                post_format = "text_only"
                paired_dir = None
            else:
                tqdm.write("[✓] Paired figures found.")
        else:
            tqdm.write("[*] Skipping figure extraction for 'text_only'.")

        tqdm.write("\n--- Stage 3/4: Generating Structured Blog Draft ---")
        blog_draft, source_paper_text = await generate_text_blog(
            txt_path=str(txt_output_path),
            api_key=args.text_api_key,
            text_api_base=args.text_api_base,
            model=args.text_model,
            language=language,
            disable_qwen_thinking=args.disable_qwen_thinking,
            ablation_mode=ablation_mode,
        )
        if not blog_draft or str(blog_draft).startswith("Error:"):
            tqdm.write(f"[!] Blog draft failed. Error: {blog_draft}. Skipping.")
            return
        tqdm.write("[✓] Structured draft generated.")

        tqdm.write("\n--- Stage 4/4: Generating Final Platform Post ---")
        description_cache_dir = args.cache_dir / "descriptions" if args.cache_dir else None
        final_post, assets = await generate_final_post(
            blog_draft=blog_draft,
            source_paper_text=source_paper_text,
            assets_dir=paired_dir,
            text_api_key=args.text_api_key,
            vision_api_key=args.vision_api_key,
            text_model=args.text_model,
            text_api_base=args.text_api_base,
            vision_model=args.vision_model,
            vision_api_base=args.vision_api_base,
            platform=platform,
            language=language,
            post_format=post_format,
            pdf_hash=pdf_hash,
            description_cache_dir=str(description_cache_dir) if description_cache_dir else None,
            disable_qwen_thinking=args.disable_qwen_thinking,
            ablation_mode=ablation_mode,
        )
        if not final_post or str(final_post).startswith("Error:"):
            tqdm.write(f"[!] Final post failed. Error: {final_post}. Skipping.")
            return
        tqdm.write("[✓] Final post generated.")

        create_output_package(final_output_dir, final_post, assets)
        tqdm.write(f"\n✅ Completed: {original_project_name} -> {final_output_dir}")

    except Exception as e:
        tqdm.write(f"\n[!!!] Unexpected error for {original_project_name}: {e}")
        traceback.print_exc()
    finally:
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
            tqdm.write(f"[*] Cleaned temp: {work_dir}")


async def process_baseline_project(
    project_path: Path,
    args: argparse.Namespace,
    platform: str,
    language: str,
    log_lock: Optional[asyncio.Lock] = None,
    log_data: Optional[dict] = None,
    log_file_path: Optional[Path] = None,
):
    baseline_mode = args.baseline_mode
    project_name = f"{project_path.name}_baseline_{baseline_mode}"

    tqdm.write("\n" + "=" * 80)
    tqdm.write(f"🚀 Starting BASELINE processing for project: {project_path.name}")
    tqdm.write(f"   (Mode: {baseline_mode}, Platform: {platform}, Language: {language})")
    tqdm.write("=" * 80)

    pdf_files = list(project_path.glob("*.pdf"))
    if not pdf_files:
        tqdm.write(f"[!] No PDF file found in '{project_path}'. Skipping.")
        return
    pdf_path = pdf_files[0]

    session_id = f"session_{int(time.time())}_{project_name}"
    work_dir = Path(args.output_dir) / ".temp" / session_id
    final_output_dir = Path(args.output_dir) / project_name
    work_dir.mkdir(parents=True, exist_ok=True)

    try:
        tqdm.write("\n--- Stage 1/3: Extracting Text ---")
        txt_output_path = work_dir / f"{project_name}.txt"
        await run_text_extraction(str(pdf_path), str(txt_output_path))
        if not txt_output_path.exists():
            tqdm.write(f"[!] Text extraction failed for {pdf_path.name}. Skipping.")
            return
        paper_text = txt_output_path.read_text(encoding="utf-8", errors="replace")
        tqdm.write("[✓] Text extracted.")

        paired_dir = None
        pdf_hash = None

        if baseline_mode == "with_figure":
            tqdm.write("\n--- Stage 2/3: Extracting Figures (baseline) ---")
            cached_figures_path = None
            if args.cache_dir:
                pdf_hash = get_pdf_hash(pdf_path)
                cached_figures_path = args.cache_dir / "figures" / pdf_hash
                if cached_figures_path.exists() and any(cached_figures_path.iterdir()):
                    tqdm.write(f"[✓] Cache hit for figures '{pdf_path.name}'.")
                    paired_dir = str(cached_figures_path)

            if not paired_dir:
                extraction_work_dir = work_dir / "figure_extraction"
                extraction_work_dir.mkdir()
                extracted_data_dir = run_figure_extraction(str(pdf_path), str(extraction_work_dir), args.model_path)
                if extracted_data_dir and any(Path(extracted_data_dir).iterdir()):
                    paired_dir = extracted_data_dir
                    if args.cache_dir and cached_figures_path:
                        tqdm.write(f"[*] Caching extracted figures to: {cached_figures_path}")
                        safe_copytree(Path(extracted_data_dir), cached_figures_path)
                else:
                    tqdm.write("[!] Warning: Figure extraction failed or found no figures.")
        else:
            tqdm.write("\n--- Stage 2/3: Skipping Figures (baseline) ---")

        tqdm.write("\n--- Stage 3/3: Generating Baseline Post ---")
        baseline_post, assets, think_token_count = await generate_baseline_post(
            paper_text=paper_text,
            api_key=args.text_api_key,
            api_base=args.text_api_base,
            model=args.text_model,
            platform=platform,
            language=language,
            disable_qwen_thinking=args.disable_qwen_thinking,
            mode=baseline_mode,
            assets_dir=paired_dir,
        )

        tqdm.write(f"[*] 'Thinking' tokens used (baseline): {think_token_count}")

        if args.log_think_tokens and log_lock and log_data is not None and log_file_path:
            log_key = f"{project_path.name}_{baseline_mode}"
            async with log_lock:
                log_data[log_key] = {
                    "think_tokens": think_token_count,
                    "model": args.text_model,
                    "timestamp": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime()),
                }
                log_file_path.write_text(json.dumps(log_data, indent=2, ensure_ascii=False), encoding="utf-8")
                tqdm.write(f"[*] Logged baseline tokens for '{log_key}' -> {log_file_path.name}")

        if not baseline_post or str(baseline_post).startswith("Error:"):
            tqdm.write(f"[!] Baseline post failed. Error: {baseline_post}. Skipping.")
            return

        create_output_package(final_output_dir, baseline_post, assets)
        tqdm.write(f"\n✅ Completed baseline: {project_path.name} -> {final_output_dir}")

    except Exception as e:
        tqdm.write(f"\n[!!!] Unexpected baseline error for {project_name}: {e}")
        traceback.print_exc()
    finally:
        if work_dir.exists():
            shutil.rmtree(work_dir, ignore_errors=True)
            tqdm.write(f"[*] Cleaned temp: {work_dir}")


# -----------------------------
# Main
# -----------------------------

async def main():
    parser = argparse.ArgumentParser(description="PRAgent: Batch process PDF projects.")

    parser.add_argument("--input-dir", type=str, default="papers",
                        help="Root directory containing projects (may be nested). If this folder contains a PDF, it is treated as a single project.")
    parser.add_argument("--output-dir", type=str, default="outputs",
                        help="Directory where final posts are saved.")
    parser.add_argument("--model-path", type=str, default="models/doclayout_yolo_docstructbench_imgsz1024.pt",
                        help="Path to the DocLayout-YOLO model.")

    # API
    parser.add_argument("--text-api-key", type=str, default=None, help="API key for text models (defaults to env).")
    parser.add_argument("--vision-api-key", type=str, default=None, help="API key for vision models (defaults to text key).")
    parser.add_argument("--text-api-base", type=str, default=None, help="Base URL for text API (defaults to env).")
    parser.add_argument("--vision-api-base", type=str, default=None, help="Base URL for vision API (defaults to text base).")

    # Models: default None so env can drive defaults
    parser.add_argument("--text-model", type=str, default=None, help="Text model name (defaults to TEXT_MODEL/OPENAI_TEXT_MODEL env, else gpt-4o).")
    parser.add_argument("--vision-model", type=str, default=None, help="Vision model name (defaults to VISION_MODEL env, else text-model).")

    parser.add_argument("--concurrency", type=int, default=1, help="Max concurrent projects.")

    # Selection
    parser.add_argument("--project", type=str, default=None, help="Process only this exact project folder name.")
    parser.add_argument("--prefix", type=str, default=None, help="Process folders whose names start with this prefix (e.g., 12 or 0012).")
    parser.add_argument("--max-depth", type=int, default=6, help="When input-dir is a root, search up to this depth for PDFs.")

    # Output format
    parser.add_argument("--post-format", type=str, default="rich",
                        choices=["rich", "description_only", "text_only"],
                        help="Output format for the final post.")

    # Platform/language (optional, but handy)
    parser.add_argument("--platform", type=str, default="twitter",
                        choices=["twitter", "xiaohongshu"],
                        help="Target platform for PRAgent generation.")
    parser.add_argument("--language", type=str, default="en",
                        choices=["en", "zh"],
                        help="Language for generation.")

    # Baseline + logging
    parser.add_argument("--baseline-mode", type=str, default=None,
                        choices=["original", "fewshot", "with_figure"],
                        help="If specified, run baseline generation instead of advanced pipeline.")
    parser.add_argument("--log-think-tokens", action="store_true", help="Log 'think' tokens to JSON in output dir (baseline only).")

    # Cache + ablations
    parser.add_argument("--cache-dir", type=Path, default=None, help="Optional cache directory for figures/descriptions.")
    parser.add_argument("--disable-qwen-thinking", action="store_true", help="Disable Qwen thinking mode.")
    parser.add_argument("--ablation", type=str, default="none",
                        choices=["none", "no_logical_draft", "no_visual_analysis", "no_visual_integration",
                                 "no_hierarchical_summary", "no_platform_adaptation", "stage2"],
                        help="Ablation mode (advanced pipeline only).")

    args = parser.parse_args()

    # Load .env (repo root)
    try:
        from dotenv import load_dotenv
        load_dotenv()
    except Exception:
        pass

    # API key/base: support both TEXT_* and OPENAI_* conventions
    args.text_api_key = args.text_api_key or env_first("TEXT_API_KEY", "OPENAI_API_KEY")
    args.text_api_base = args.text_api_base or env_first("TEXT_API_BASE", "OPENAI_API_BASE", "OPENAI_BASE_URL", fallback="https://api.openai.com/v1")

    if not args.text_api_key:
        print("Error: No API key found. Set TEXT_API_KEY or OPENAI_API_KEY (or pass --text-api-key).")
        return

    if args.vision_api_key is None:
        args.vision_api_key = env_first("VISION_API_KEY", fallback=args.text_api_key)
    if args.vision_api_base is None:
        args.vision_api_base = env_first("VISION_API_BASE", fallback=args.text_api_base)

    # Model defaults: env-driven
    if args.text_model is None:
        args.text_model = env_first("TEXT_MODEL", "OPENAI_TEXT_MODEL", fallback="gpt-4o")
    if args.vision_model is None:
        args.vision_model = env_first("VISION_MODEL", "OPENAI_VISION_MODEL", fallback=args.text_model)

    print(f"[*] Using Text API Base:   {args.text_api_base}")
    print(f"[*] Using Vision API Base: {args.vision_api_base}")
    print(f"[*] Using Text Model:      {args.text_model}")
    print(f"[*] Using Vision Model:    {args.vision_model}")

    # Cache dirs
    if args.cache_dir:
        args.cache_dir.mkdir(parents=True, exist_ok=True)
        (args.cache_dir / "figures").mkdir(exist_ok=True)
        (args.cache_dir / "descriptions").mkdir(exist_ok=True)
        print(f"[*] Using cache at: {args.cache_dir}")

    input_path = Path(args.input_dir)
    output_path = Path(args.output_dir)
    output_path.mkdir(parents=True, exist_ok=True)

    # Discover projects
    project_folders = discover_project_folders(
        input_dir=input_path,
        project=args.project,
        prefix=args.prefix,
        max_depth=args.max_depth,
    )

    if not project_folders:
        print(f"No project folders found under '{input_path}'.")
        print("Tip: ensure your project folders contain at least one .pdf (directly inside the folder).")
        return

    print(f"Found {len(project_folders)} project(s) with concurrency={args.concurrency}.")
    if args.project:
        print(f"[*] Filter: project == {args.project}")
    if args.prefix:
        print(f"[*] Filter: prefix startswith {args.prefix}")

    # Setup baseline logging
    log_lock = None
    log_file_path = None
    log_data = {}
    if args.baseline_mode and args.log_think_tokens:
        log_lock = asyncio.Lock()
        log_file_path = output_path / "think_token_log.json"
        if log_file_path.exists():
            try:
                log_data = json.loads(log_file_path.read_text(encoding="utf-8"))
                print(f"[*] Loaded token log from: {log_file_path}")
            except json.JSONDecodeError:
                print("[!] Warning: could not parse token log; starting fresh.")
        else:
            print(f"[*] Token log will be created at: {log_file_path}")

    semaphore = asyncio.Semaphore(args.concurrency)

    async def process_with_semaphore(coro):
        async with semaphore:
            await coro

    tasks = []
    for project_path in project_folders:
        base_name = project_path.name
        out_name = base_name
        if args.baseline_mode:
            out_name = f"{base_name}_baseline_{args.baseline_mode}"
        elif args.ablation != "none":
            out_name = f"{base_name}_ablation_{args.ablation}"

        out_dir = output_path / out_name

        # Skip if already exists
        if out_dir.exists() and any(out_dir.iterdir()):
            tqdm.write(f"[*] Skipping '{out_name}': output already exists.")
            continue

        platform = args.platform
        language = args.language

        if args.baseline_mode:
            # Optional skip based on token log
            if args.log_think_tokens and log_file_path and (f"{base_name}_{args.baseline_mode}" in log_data):
                tqdm.write(f"[*] Skipping '{base_name}' baseline '{args.baseline_mode}': already logged.")
                continue

            coro = process_baseline_project(
                project_path, args, platform, language,
                log_lock=log_lock, log_data=log_data, log_file_path=log_file_path
            )
        else:
            coro = process_single_project(project_path, args, platform, language)

        tasks.append(process_with_semaphore(coro))

    if tasks:
        await tqdm.gather(*tasks, desc="Processing Projects", unit="project", total=len(tasks))
    else:
        print("[*] Nothing to do (everything already processed).")


if __name__ == "__main__":
    asyncio.run(main())
