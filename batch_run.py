import argparse
import os
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Optional, Iterable

# NEW: load .env automatically (repo root)
from dotenv import load_dotenv


def ts() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


def log_line(log_path: Optional[Path], msg: str) -> None:
    line = f"[{ts()}] {msg}"
    print(line)
    if log_path:
        log_path.parent.mkdir(parents=True, exist_ok=True)
        with log_path.open("a", encoding="utf-8") as f:
            f.write(line + "\n")


def run_cmd(cmd: list[str], dry_run: bool, log_path: Optional[Path]) -> int:
    if dry_run:
        log_line(log_path, "DRY RUN > " + " ".join(cmd))
        return 0
    log_line(log_path, "> " + " ".join(cmd))
    p = subprocess.run(
        cmd,
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
    )
    if p.stdout:
        for line in p.stdout.strip().splitlines():
            log_line(log_path, f"[stdout] {line}")
    if p.stderr:
        for line in p.stderr.strip().splitlines():
            log_line(log_path, f"[stderr] {line}")
    return p.returncode


def iter_project_names_from_papers(papers_dir: Path) -> Iterable[str]:
    for d in sorted(papers_dir.iterdir(), key=lambda p: p.name):
        if not d.is_dir():
            continue
        if d.name.startswith("."):
            continue
        yield d.name


def has_existing_images(out_proj_dir: Path) -> bool:
    """Return True when output has at least one extracted image asset."""
    img_dir = out_proj_dir / "img"
    if not img_dir.exists() or not img_dir.is_dir():
        return False
    return any(p.is_file() for p in img_dir.rglob("*"))


def main() -> None:
    ap = argparse.ArgumentParser(
        description="Batch runner: pragent.run (extract) -> postprocess.py -> typefully_push.py"
    )

    # dirs
    ap.add_argument("--papers-dir", default="papers", help="Folder containing paper project folders.")
    ap.add_argument("--outputs-dir", default="outputs", help="Folder where outputs/<project>/... are written.")

    # stages
    ap.add_argument("--extract", action="store_true", help="Run `python -m pragent.run` for each selected project.")
    ap.add_argument("--postprocess", action="store_true", help="Run postprocess.py for each selected project.")
    ap.add_argument("--push", action="store_true", help="Run typefully_push.py for each selected project.")

    # selection
    ap.add_argument("--project", default="", help="Exact project folder name (e.g., 0012_James_2025_Extraction).")
    ap.add_argument("--only", default="", help="Substring filter (e.g., '0012').")
    ap.add_argument(
        "--prefix",
        default="",
        help="Prefix filter (e.g., '0012' matches folders that start with 0012). More precise than --only.",
    )
    ap.add_argument("--max", type=int, default=0, help="Process only first N matches (0 = no limit).")

    # extract config
    ap.add_argument(
        "--model-path",
        default=r".\models\doclayout_yolo_docstructbench_imgsz1024.pt",
        help="DocLayout-YOLO model path for figure extraction.",
    )
    ap.add_argument("--concurrency", type=int, default=1, help="pragent.run concurrency.")
    ap.add_argument("--post-format", default="rich", help="pragent.run post format (rich/description_only/text_only).")
    ap.add_argument(
        "--force-numbering",
        action="store_true",
        help="Pass --force-numbering to typefully_push.py to embed i/n numbering in text.",
    )

    # behavior
    ap.add_argument(
        "--skip-existing-outputs",
        action="store_true",
        help="If outputs/<project>/markdown.md exists, skip extract for that project.",
    )
    ap.add_argument(
        "--skip-existing-json",
        action="store_true",
        help="If outputs/<project>/platform_posts.json exists, skip postprocess for that project.",
    )
    ap.add_argument("--sleep", type=float, default=0.0, help="Seconds to sleep between projects.")
    ap.add_argument("--stop-on-error", action="store_true", help="Stop immediately on first failure.")
    ap.add_argument("--dry-run", action="store_true", help="Print commands but do not execute.")
    ap.add_argument("--log", default="batch_run.log", help='Append logs to this file ("" disables).')

    args = ap.parse_args()

    repo_dir = Path(__file__).resolve().parent

    # Use the same interpreter for subprocess stages to avoid PATH/venv mismatches.
    python_exe = sys.executable

    # NEW: auto-load .env from repo root
    load_dotenv(dotenv_path=repo_dir / ".env")

    # NEW: default to ALL steps if none explicitly provided
    if not args.extract and not args.postprocess and not args.push:
        args.extract = True
        args.postprocess = True
        args.push = True

    papers_dir = (repo_dir / args.papers_dir).resolve()
    outputs_dir = (repo_dir / args.outputs_dir).resolve()

    if not papers_dir.exists():
        raise SystemExit(f"papers dir not found: {papers_dir}")
    outputs_dir.mkdir(parents=True, exist_ok=True)

    log_path = None if args.log.strip() == "" else (repo_dir / args.log)

    # sanity check Typefully env if pushing
    if args.push and not args.dry_run:
        if not os.environ.get("TYPEFULLY_API_KEY"):
            log_line(log_path, "[WARN] TYPEFULLY_API_KEY is not set (check .env).")
        if not os.environ.get("TYPEFULLY_SOCIAL_SET_ID"):
            log_line(log_path, "[WARN] TYPEFULLY_SOCIAL_SET_ID is not set (check .env).")

    names = list(iter_project_names_from_papers(papers_dir))

    if args.project:
        names = [n for n in names if n == args.project]
        if not names:
            raise SystemExit(f"Project not found under papers/: {args.project}")

    if args.prefix:
        names = [n for n in names if n.startswith(args.prefix)]

    if args.only:
        names = [n for n in names if args.only in n]

    if args.max and len(names) > args.max:
        names = names[: args.max]

    if not names:
        raise SystemExit("No matching projects found (check --project/--prefix/--only).")

    processed = 0
    failures = 0

    for name in names:
        processed += 1
        log_line(log_path, "")
        log_line(log_path, f"=== {name} ===")

        paper_proj_dir = papers_dir / name
        out_proj_dir = outputs_dir / name

        # Stage 1: extract via pragent.run
        if args.extract:
            md_path = out_proj_dir / "markdown.md"
            if args.skip_existing_outputs and md_path.exists():
                needs_rich_assets = args.post_format in ("rich", "description_only")
                if needs_rich_assets and not has_existing_images(out_proj_dir):
                    log_line(
                        log_path,
                        f"Re-running extract: rich format requested but no images found under {out_proj_dir / 'img'}",
                    )
                else:
                    log_line(log_path, f"Skipping extract (exists): {md_path}")
                    continue
            else:
                cmd = [
                    python_exe,
                    "-m",
                    "pragent.run",
                    "--input-dir",
                    str(paper_proj_dir),
                    "--output-dir",
                    str(outputs_dir),
                    "--model-path",
                    str(Path(args.model_path)),
                    "--concurrency",
                    str(args.concurrency),
                    "--post-format",
                    args.post_format,
                ]
                rc = run_cmd(cmd, dry_run=args.dry_run, log_path=log_path)
                if rc != 0:
                    failures += 1
                    log_line(log_path, f"[ERR] extract failed: {name} (exit {rc})")
                    if args.stop_on_error:
                        break
                    continue

        # Stage 2: postprocess
        json_path = out_proj_dir / "platform_posts.json"
        if args.postprocess:
            if args.skip_existing_json and json_path.exists():
                log_line(log_path, f"Skipping postprocess (JSON exists): {json_path}")
            else:
                rc = run_cmd(
                    [python_exe, str(repo_dir / "postprocess.py"), "--project", name],
                    dry_run=args.dry_run,
                    log_path=log_path,
                )
                if rc != 0:
                    failures += 1
                    log_line(log_path, f"[ERR] postprocess failed: {name} (exit {rc})")
                    if args.stop_on_error:
                        break
                    continue

        # Stage 3: push to Typefully
        if args.push:
            if not json_path.exists():
                failures += 1
                log_line(log_path, f"[ERR] missing JSON (skipping push): {json_path}")
                if args.stop_on_error:
                    break
            else:
                push_cmd = [
                    python_exe,
                    str(repo_dir / "typefully_push.py"),
                    "--json",
                    str(json_path),
                    "--draft-title",
                    name,
                ]
                if args.force_numbering:
                    push_cmd.append("--force-numbering")
                rc = run_cmd(
                    push_cmd,
                    dry_run=args.dry_run,
                    log_path=log_path,
                )
                if rc != 0:
                    failures += 1
                    log_line(log_path, f"[ERR] push failed: {name} (exit {rc})")
                    if args.stop_on_error:
                        break
                else:
                    log_line(log_path, f"[OK] pushed: {name}")

        if args.sleep and args.sleep > 0:
            time.sleep(args.sleep)

    log_line(log_path, "")
    log_line(log_path, f"Done. Projects processed: {processed}. Failures: {failures}.")
    raise SystemExit(0 if failures == 0 else 1)


if __name__ == "__main__":
    main()
