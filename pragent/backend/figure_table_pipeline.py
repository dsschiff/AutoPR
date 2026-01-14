import os
import shutil
import re
from pathlib import Path
from collections import defaultdict
from pragent.backend.loader import ImagePDFLoader
from pragent.backend.yolo import extract_and_save_layout_components
from tqdm.asyncio import tqdm

#added
import hashlib
SHORT_TMP = Path(os.environ.get("AUTOPR_TEMP", r"D:\aprtmp"))
SHORT_TMP.mkdir(parents=True, exist_ok=True)

def _short_stem(name: str, max_len: int = 48) -> str:
    # filename-safe and short, with a hash to avoid collisions
    s = re.sub(r"[^A-Za-z0-9_-]+", "_", name).strip("_")
    h = hashlib.sha1(name.encode("utf-8")).hexdigest()[:8]
    s = s[:max_len]
    return f"{s}__{h}"

def run_figure_extraction(pdf_path: str, base_work_dir: str, model_path: str) -> str:
    if not all([ImagePDFLoader, extract_and_save_layout_components]):
        tqdm.write("[!] Error: One or more core dependencies of figure_pipeline failed to load.")
        return None

    pdf_file = Path(pdf_path)

    # ✅ Shrink temp root (Windows-safe)
    temp_root = os.environ.get("AUTOPR_TEMP", "").strip()
    if temp_root:
        session_name = Path(base_work_dir).name  # e.g., session_..._0003__Ganz...
        work_dir = os.path.join(temp_root, session_name)
    else:
        work_dir = base_work_dir

    os.makedirs(work_dir, exist_ok=True)

    # ✅ Do NOT nest by pdf_stem — paths get too long on Windows
    tqdm.write(f"\n--- Step 1/3: Convert PDF '{pdf_file.name}' to images ---")
    page_save_dir = os.path.join(work_dir, "page_paper")
    os.makedirs(page_save_dir, exist_ok=True)

    try:
        loader = ImagePDFLoader(pdf_path)
        page_image_paths = []
        for i, img in enumerate(loader.load()):
            path = os.path.join(page_save_dir, f"page_{i+1}.png")
            img.save(path)
            page_image_paths.append(path)
        tqdm.write(f"[*] All {len(page_image_paths)} pages have been saved to: {page_save_dir}")
    except Exception as e:
        tqdm.write(f"[!] Error: Failed to load or convert PDF: {e}")
        return None

    tqdm.write(f"\n--- Step 2/3: Analyze page layout to crop figures and tables ---")
    cropped_results_dir = os.path.join(work_dir, "cropped_results")
    os.makedirs(cropped_results_dir, exist_ok=True)

    for path in page_image_paths:
        page_num_str = Path(path).stem  # e.g., page_1
        page_crop_dir = os.path.join(cropped_results_dir, page_num_str)
        os.makedirs(page_crop_dir, exist_ok=True)

        extract_and_save_layout_components(
            image_path=path,
            model_path=model_path,
            save_base_dir=page_crop_dir
        )

    tqdm.write(f"[*] All cropped results have been saved to: {cropped_results_dir}")

    tqdm.write(f"\n--- Step 3/3: Pair the cropped components ---")
    final_paired_dir = os.path.join(work_dir, "paired_results")
    os.makedirs(final_paired_dir, exist_ok=True)

    run_pairing_process(cropped_results_dir, final_paired_dir, threshold=30)

    if os.path.isdir(final_paired_dir):
        return final_paired_dir
    return None



def run_pairing_process(source_dir_str: str, output_dir_str: str, threshold: int):
    """Pairing logic, now part of the pipeline."""
    source_dir = Path(source_dir_str)
    output_root_dir = Path(output_dir_str)
    if output_root_dir.exists(): shutil.rmtree(output_root_dir)
    output_root_dir.mkdir(parents=True, exist_ok=True)
    
    tqdm.write(f"    Starting nearest neighbor pairing process (threshold = {threshold})")

    page_dirs = sorted([d for d in source_dir.iterdir() if d.is_dir() and d.name.startswith('page_')])
    for page_dir in page_dirs:
        output_page_dir = output_root_dir / page_dir.name
        output_page_dir.mkdir(exist_ok=True)
        pair_items_on_page(str(page_dir), str(output_page_dir), threshold)

def pair_items_on_page(page_dir: str, output_dir: str, threshold: int):
    """Process a single page directory for nearest neighbor pairing."""
    organized_files = defaultdict(dict)
    component_types = ["figure", "figure_caption", "table", "table_caption_above", "table_caption_below"]
    
    def parse_filename(filename: str):
        match = re.match(r'([a-zA-Z_]+)_(\d+)_score([\d.]+)\.jpg', filename)
        return (match.group(1), int(match.group(2))) if match else (None, None)

    for comp_type in component_types:
        comp_dir = os.path.join(page_dir, comp_type)
        if os.path.isdir(comp_dir):
            for filename in os.listdir(comp_dir):
                _, index = parse_filename(filename)
                if index is not None: organized_files[comp_type][index] = os.path.join(comp_dir, filename)

    paired_files, used_captions = set(), defaultdict(set)

    for item_type, cap_types in [("figure", ["figure_caption"]), ("table", ["table_caption_above", "table_caption_below"])]:
        for item_index, item_path in organized_files[item_type].items():
            best_match = {'min_diff': float('inf'), 'cap_path': None, 'cap_index': -1, 'cap_type': ''}
            for cap_type in cap_types:
                for cap_index, cap_path in organized_files[cap_type].items():
                    if cap_index in used_captions[cap_type]: continue
                    diff = abs(item_index - cap_index)
                    if diff < best_match['min_diff']:
                        best_match.update({'min_diff': diff, 'cap_path': cap_path, 'cap_index': cap_index, 'cap_type': cap_type})
            
            if best_match['cap_path'] and best_match['min_diff'] <= threshold:
                target_dir = os.path.join(output_dir, f"paired_{item_type}_{item_index}")
                os.makedirs(target_dir, exist_ok=True)
                shutil.copy(item_path, target_dir); shutil.copy(best_match['cap_path'], target_dir)
                paired_files.add(item_path); paired_files.add(best_match['cap_path'])
                used_captions[best_match['cap_type']].add(best_match['cap_index'])

    for files_dict in organized_files.values():
        for file_path in files_dict.values():
            if file_path not in paired_files:
                item_type, index = parse_filename(Path(file_path).name)
                if item_type:
                    target_dir = os.path.join(output_dir, f"unpaired_{item_type}_{index}")
                    os.makedirs(target_dir, exist_ok=True); shutil.copy(file_path, target_dir)
