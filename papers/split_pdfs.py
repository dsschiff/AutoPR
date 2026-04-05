from pathlib import Path

SRC = Path(r"D:\Dropbox\Documents\Academics\Purdue\GitHub\AutoPR\papers")

# Only PDFs directly in SRC (non-recursive)
pdfs = [p for p in SRC.iterdir() if p.is_file() and p.suffix.lower() == ".pdf"]

# Sort by "Date Modified" (mtime): earliest first
pdfs.sort(key=lambda p: p.stat().st_mtime)

if len(pdfs) > 10000:
    raise RuntimeError(f"Found {len(pdfs)} PDFs; exceeds 10,000 folders (0000..9999).")

moved = 0
for i, pdf in enumerate(pdfs):
    folder = SRC / f"{i:04d}"
    folder.mkdir(exist_ok=True)

    dest = folder / pdf.name

    # If a file with the same name already exists in the destination folder, avoid overwriting
    if dest.exists():
        stem, suffix = pdf.stem, pdf.suffix
        k = 1
        while True:
            candidate = folder / f"{stem} ({k}){suffix}"
            if not candidate.exists():
                dest = candidate
                break
            k += 1

    pdf.rename(dest)  # move (within same drive)

    moved += 1

print(f"Moved {moved} PDF(s).")
