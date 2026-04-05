import argparse
import csv
import re
import shutil
from pathlib import Path


def slugify(text: str) -> str:
    text = text.strip().lower()
    text = re.sub(r"[^a-z0-9]+", "_", text)
    return re.sub(r"_+", "_", text).strip("_")


def detect_next_prefix(papers_dir: Path) -> str:
    max_prefix = -1
    for d in papers_dir.iterdir():
        if not d.is_dir():
            continue
        m = re.match(r"^(\d{4})", d.name)
        if m:
            max_prefix = max(max_prefix, int(m.group(1)))
    return f"{max_prefix + 1:04d}"


def build_default_project_name(prefix: str, first_author: str, year: str, title: str) -> str:
    author_slug = slugify(first_author) or "unknown"
    title_slug = slugify(title) or "paper"
    short_title = "_".join(title_slug.split("_")[:4])
    return f"{prefix}_{author_slug}_{year}_{short_title}"


def upsert_paper_url(csv_path: Path, prefix: str, url: str, venue: str) -> None:
    rows = []
    if csv_path.exists():
        with csv_path.open("r", newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            for row in reader:
                rows.append(row)

    found = False
    for row in rows:
        if row.get("prefix", "").strip() == prefix:
            row["url"] = url
            row["venue"] = venue
            found = True
            break

    if not found:
        rows.append({"prefix": prefix, "url": url, "venue": venue})

    with csv_path.open("w", newline="", encoding="utf-8") as f:
        fieldnames = ["prefix", "url", "venue"]
        writer = csv.DictWriter(f, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(rows)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Create an AutoPR paper project folder from a PDF and optionally update paper_urls.csv"
    )
    parser.add_argument("--pdf", required=True, help="Source PDF path (e.g., Zotero storage path)")
    parser.add_argument("--first-author", required=True, help="First author surname (e.g., Jacobson)")
    parser.add_argument("--year", required=True, help="Publication year (e.g., 2026)")
    parser.add_argument("--title", required=True, help="Paper title")
    parser.add_argument("--prefix", help="Optional explicit 4-digit prefix")
    parser.add_argument(
        "--project-name",
        help="Optional explicit folder name under papers/. If omitted, generated from prefix/author/year/title",
    )
    parser.add_argument("--url", default="", help="Optional paper URL for paper_urls.csv")
    parser.add_argument("--venue", default="", help="Optional venue for paper_urls.csv")
    parser.add_argument(
        "--update-url-map",
        action="store_true",
        help="If set, upsert prefix,url,venue in paper_urls.csv",
    )
    parser.add_argument("--dry-run", action="store_true", help="Print planned actions without writing")

    args = parser.parse_args()

    repo_root = Path(__file__).resolve().parent
    papers_dir = repo_root / "papers"
    outputs_dir = repo_root / "outputs"
    paper_urls_csv = repo_root / "paper_urls.csv"

    pdf_path = Path(args.pdf).expanduser().resolve()
    if not pdf_path.exists():
        raise SystemExit(f"PDF not found: {pdf_path}")

    prefix = args.prefix or detect_next_prefix(papers_dir)
    if not re.match(r"^\d{4}$", prefix):
        raise SystemExit(f"Invalid prefix '{prefix}'. Expected 4 digits.")

    project_name = args.project_name or build_default_project_name(prefix, args.first_author, args.year, args.title)
    target_paper_dir = papers_dir / project_name
    target_output_dir = outputs_dir / project_name
    target_pdf_path = target_paper_dir / pdf_path.name

    print(f"prefix: {prefix}")
    print(f"project_name: {project_name}")
    print(f"source_pdf: {pdf_path}")
    print(f"target_pdf: {target_pdf_path}")
    print(f"target_output_dir: {target_output_dir}")

    if target_paper_dir.exists():
        raise SystemExit(f"Target paper folder already exists: {target_paper_dir}")

    if args.dry_run:
        if args.update_url_map:
            print(f"[dry-run] would upsert {prefix} into {paper_urls_csv}")
        print("[dry-run] no files were changed")
        return 0

    target_paper_dir.mkdir(parents=True, exist_ok=False)
    target_output_dir.mkdir(parents=True, exist_ok=True)
    shutil.copy2(pdf_path, target_pdf_path)

    if args.update_url_map:
        upsert_paper_url(paper_urls_csv, prefix, args.url, args.venue)

    print("ingest complete")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
