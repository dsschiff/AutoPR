import argparse
import csv
import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple, Set

from dotenv import load_dotenv
from openai import OpenAI  # openai>=1.x

load_dotenv()  # loads .env from repo root if present


# -----------------------------
# Helpers: env + csv + IO
# -----------------------------

def env_default(key: str, fallback: str = "") -> str:
    v = os.getenv(key)
    return v.strip() if v else fallback


def load_meta_map(csv_path: Path) -> Dict[str, Dict[str, str]]:
    m: Dict[str, Dict[str, str]] = {}
    if not csv_path.exists():
        print(f"⚠️ URLs file not found: {csv_path}")
        return m

    raw = csv_path.read_text(encoding="utf-8-sig", errors="replace").strip()
    if not raw:
        print(f"⚠️ URLs file is empty: {csv_path}")
        return m

    sample = raw[:2048]
    delim = "\t" if sample.count("\t") > sample.count(",") else ","

    reader = csv.DictReader(raw.splitlines(), delimiter=delim)
    if not reader.fieldnames:
        print(f"⚠️ Could not read header from: {csv_path}")
        return m

    for row in reader:
        # normalize keys: strip whitespace/BOM-like chars
        norm = { (k or "").strip().lstrip("\ufeff"): (v or "").strip() for k, v in row.items() }

        prefix_raw = norm.get("prefix", "")
        if not prefix_raw:
            continue
        prefix = prefix_raw.zfill(4)

        # accept url or common header glitches
        url = norm.get("url") or norm.get("turl") or norm.get("\turl") or ""
        venue = norm.get("venue", "")

        if url:
            m[prefix] = {"url": url, "venue": venue}

    return m



def _read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8", errors="replace")


def _strip_code_fences(s: str) -> str:
    # Remove ```json ... ``` wrappers if present
    m = re.search(r"```(?:json)?\s*([\s\S]+?)\s*```", s)
    return m.group(1).strip() if m else s.strip()


def _list_images(img_dir: Path) -> List[str]:
    exts = {".jpg", ".jpeg", ".png", ".webp"}
    if not img_dir.exists():
        return []
    return [p.name for p in sorted(img_dir.iterdir()) if p.suffix.lower() in exts]


def _save_thread_plain(out_path: Path, posts: List[Dict[str, Any]]) -> None:
    chunks = []
    for p in posts:
        text = (p.get("text") or "").strip()
        img = p.get("image")
        if img:
            text += f"\n\n[Attach image: {img}]"
        chunks.append(text)
    out_path.write_text("\n\n---\n\n".join(chunks), encoding="utf-8")


def _save_typefully(out_path: Path, posts: List[Dict[str, Any]]) -> None:
    # Same formatting for now; kept separate in case you want Typefully-specific formatting later.
    chunks = []
    for p in posts:
        text = (p.get("text") or "").strip()
        img = p.get("image")
        if img:
            text += f"\n\n[Attach image: {img}]"
        chunks.append(text)
    out_path.write_text("\n\n---\n\n".join(chunks), encoding="utf-8")


def _maybe_number_posts(posts: List[Dict[str, Any]], number_posts: bool) -> List[Dict[str, Any]]:
    """
    Applies numbering to post TEXT only (for your .txt convenience files).
    Keeps JSON clean by default so Typefully auto-numbering works nicely.
    """
    if not number_posts:
        return posts
    n = len(posts)
    out: List[Dict[str, Any]] = []
    for i, p in enumerate(posts):
        q = dict(p)
        txt = (q.get("text") or "").lstrip()
        q["text"] = f"{i+1}/{n} {txt}" if txt else f"{i+1}/{n}"
        out.append(q)
    return out


def _collect_referenced_images(data: Dict[str, Any]) -> Set[str]:
    refs: Set[str] = set()

    # twitter + bluesky posts
    for platform in ("twitter", "bluesky"):
        posts = (((data.get(platform) or {}).get("posts")) or [])
        for p in posts:
            img = (p or {}).get("image")
            if isinstance(img, str) and img.strip():
                refs.add(img.strip())

    # linkedin images
    li_imgs = ((data.get("linkedin") or {}).get("images")) or []
    for img in li_imgs:
        if isinstance(img, str) and img.strip():
            refs.add(img.strip())

    return refs


def _coerce_json_object(s: str) -> str:
    """
    Minimal JSON coercion:
    - strips code fences
    - if content starts with '"twitter"' (missing outer braces), wrap with {...}
    """
    s = _strip_code_fences(s).strip()
    if s.lstrip().startswith('"twitter"'):
        s = "{" + s + "}"
    return s


def _parse_model_json(content: str, debug_dir: Path) -> Dict[str, Any]:
    """
    Parse model output as JSON with minimal fallback + optional debug artifacts.
    Writes debug files only when parsing fails.
    """
    json_str = _coerce_json_object(content)
    try:
        data = json.loads(json_str)
    except json.JSONDecodeError:
        debug_dir.mkdir(parents=True, exist_ok=True)
        (debug_dir / "llm_raw_response.txt").write_text(content, encoding="utf-8", errors="replace")
        (debug_dir / "llm_json_attempt.txt").write_text(json_str, encoding="utf-8", errors="replace")
        raise
    if not isinstance(data, dict):
        raise RuntimeError("Parsed JSON is not a JSON object/dict.")
    return data


def _get_client() -> Tuple[OpenAI, str]:
    """
    Use OpenAI-compatible env vars.
    Works with:
      - OPENAI_API_KEY + OPENAI_BASE_URL (or OPENAI_API_BASE)
      - Or TEXT_API_KEY + TEXT_API_BASE (your earlier convention)
    """
    api_key = (os.getenv("OPENAI_API_KEY") or os.getenv("TEXT_API_KEY") or "").strip()
    base_url = (
        os.getenv("OPENAI_BASE_URL")
        or os.getenv("OPENAI_API_BASE")
        or os.getenv("TEXT_API_BASE")
        or ""
    ).strip()

    if not api_key:
        raise RuntimeError("Missing API key. Set OPENAI_API_KEY (or TEXT_API_KEY).")
    if not base_url:
        raise RuntimeError("Missing base URL. Set OPENAI_BASE_URL (or OPENAI_API_BASE / TEXT_API_BASE).")

    model = (os.getenv("POSTPROCESS_MODEL") or os.getenv("TEXT_MODEL") or "gpt-4o-mini").strip()
    client = OpenAI(api_key=api_key, base_url=base_url)
    return client, model


def _select_projects(outputs_dir: Path, project: Optional[str], latest: bool) -> List[Path]:
    if project:
        p = outputs_dir / project
        if not p.exists():
            raise FileNotFoundError(f"Project folder not found: {p}")
        return [p]

    candidates = [
        p for p in outputs_dir.iterdir()
        if p.is_dir() and not p.name.startswith(".") and p.name != ".temp"
    ]

    if latest:
        candidates.sort(key=lambda d: d.stat().st_mtime, reverse=True)
        return candidates[:1]

    candidates.sort(key=lambda d: d.name)
    return candidates


# -----------------------------
# Length enforcement (Typefully numbering reserve)
# -----------------------------

def _typefully_number_prefix(i: int, n: int) -> str:
    # i is 0-based index, n is total posts
    return f"{i+1}/{n} "


def _over_limit_indices(posts: List[Dict[str, Any]], limit: int, reserve_prefix: bool = True) -> List[int]:
    n = len(posts)
    bad: List[int] = []
    for i, p in enumerate(posts):
        text = (p.get("text") or "")
        budget = len(_typefully_number_prefix(i, n)) if reserve_prefix else 0
        if len(text) + budget > limit:
            bad.append(i)
    return bad


REWRITE_ONE_PROMPT = """
Rewrite the following post to be within {max_chars} characters MAX.

Rules:
- Preserve meaning and key details.
- Keep link/mentions if present.
- Keep line breaks if helpful.
- Do NOT add new claims or numbers.
- Avoid hype.
- Do NOT add manual numbering like "1/8".
- Prefer trimming adjectives, shortening phrases, removing optional clauses.

Post:
{text}
""".strip()


def _rewrite_one_post(client: OpenAI, model: str, text: str, max_chars: int) -> str:
    prompt = REWRITE_ONE_PROMPT.format(max_chars=max_chars, text=text)
    resp = client.chat.completions.create(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_RULES},
            {"role": "user", "content": prompt},
        ],
        temperature=0.2,
    )
    out = (resp.choices[0].message.content or "").strip()
    out = _strip_code_fences(out)

    # If the model ignored the limit, hard-trim as a last resort
    if len(out) > max_chars:
        out = out[:max_chars].rstrip()

    return out


def _enforce_thread_limits_with_targeted_rewrites(
    data: Dict[str, Any],
    platform_key: str,
    limit: int,
    reserve_typefully_numbering: bool,
    client: OpenAI,
    model: str,
) -> None:
    """
    Only rewrites the posts that exceed the platform's char limit,
    accounting for Typefully numbering prefix length if reserve_typefully_numbering=True.
    """
    blob = data.get(platform_key) or {}
    posts = blob.get("posts") or []
    if not posts:
        return

    bad = _over_limit_indices(posts, limit=limit, reserve_prefix=reserve_typefully_numbering)
    if not bad:
        return

    n = len(posts)
    for i in bad:
        prefix_len = len(_typefully_number_prefix(i, n)) if reserve_typefully_numbering else 0
        max_chars = limit - prefix_len
        old = posts[i].get("text", "")
        posts[i]["text"] = _rewrite_one_post(client, model, old, max_chars=max_chars)


# -----------------------------
# Prompts
# -----------------------------

SYSTEM_RULES = """You are "Academic Thread Creator."

Generate platform-optimized, engaging academic posts for Twitter/X, LinkedIn, and Bluesky based on an academic paper.
Mirror the user's writing style: clear, direct, conceptually layered, broadly accessible. Default to "we" / "our paper" (not "I") unless the user explicitly indicates single authorship.

Hard rules:
- Avoid hype/overclaiming. Use qualified language ("suggest", "indicate").
- Avoid robotic filler phrases ("Let's delve into", "unpacking the nuances", "a testament to", "underscore", "multifaceted", "nuanced").
- Must include at least one numerical anchor (sample size, %, etc.) IF present in the provided draft/source. Do NOT invent numbers.
- Do NOT invent coauthor handles or funders. If coauthors/funder not provided, include a brief placeholder reminder like: "[Add coauthors]" or "[Add funder]".
- Keep factual accuracy. Do not invent findings, methods, datasets, effect sizes, or claims.
- Use up to 1–3 images total; choose the most impactful. If uncertain, choose 1.

Venue + tagging:
- Always include the venue in a natural way if provided (e.g., "Published in {venue}").
- Always include a final reminder line to optionally tag the journal/outlet (placeholder provided). Do not guess journal handles.

Twitter/X:
- 6–10 posts, ~240–270 chars each, scannable, short sentences/line breaks.
- No thread numbering in text.
- Post 1: strong hook + link + thread indicator emoji (🧵 or 👇).
- Final post: personal CTA + identify target audience + link again.
- Use 2–4 meaningful emoji signposts.
- Include @GRAIL_center and @purduepolsci.
- Prefer 0–2 hashtags total, ideally only in the final post.

LinkedIn:
- ~1300–2000 characters.
- First paragraph includes the link.
- Digestible paragraphs or bullets with professional emojis (✅, ➤, •).
- End with affiliations as plain text separated by pipes (e.g., GRAIL Center | Purdue University). No Markdown links.
- 3–6 hashtags.

Bluesky:
- Mirror Twitter content/structure; concise + reflective.
- No numbering in text.
- Link in first + last post.
- Mentions: @purduepolsci.bsky.social and @GRAILcenter.bsky.social
""".strip()


PROMPT_TEMPLATE = """
You will be given:
(A) a draft output (Markdown) from an automated tool,
(B) a list of available image files extracted from the PDF,
(C) optional metadata.

Task:
1) Rewrite into THREE outputs: twitter, linkedin, bluesky
2) For twitter + bluesky: output as arrays of post objects with text + optional image filename attachment.
3) For linkedin: output a single string + optional image filenames.
4) Use up to 1–3 images total; choose the most impactful. If uncertain, choose 1.
5) Keep factual accuracy. Do not invent sample sizes, effects, or claims.
6) Always incorporate venue if provided (briefly).
7) Always include the placeholder tag reminder line as the VERY LAST LINE of each platform output (twitter last post, linkedin last line, bluesky last post).

Return ONLY valid JSON matching this schema:

{{
  "twitter": {{
    "posts": [{{"text": "...", "image": null_or_filename}}, ...]
  }},
  "linkedin": {{
    "text": "...",
    "images": [filename, ...]
  }},
  "bluesky": {{
    "posts": [{{"text": "...", "image": null_or_filename}}, ...]
  }}
}}

Inputs:
Draft (Markdown):
{draft_markdown}

Available images (filenames):
{images_list}

Metadata:
- Paper link: {paper_url}
- Venue (optional): {venue}
- Placeholder tag line (MUST include as last line): {tag_placeholder}
- Twitter handle (no @): {twitter_handle}
- LinkedIn slug: {linkedin_slug}
- Bluesky handle: {bluesky_handle}
- Author name: {author_name}
- Coauthors (names only, optional): {coauthors}
- Funder (name only, optional): {funder}
- Extra hashtags to include: {extra_hashtags}

Voice rules:
{voice_rules}
""".strip()


# -----------------------------
# Core processing
# -----------------------------

def process_one(
    project_dir: Path,
    paper_url: str,
    venue: str,
    tag_placeholder: str,
    twitter_handle: str,
    linkedin_slug: str,
    bluesky_handle: str,
    author_name: str,
    coauthors: str,
    funder: str,
    extra_hashtags: str,
    voice_rules: str,
    number_posts: bool,
    prefer_json_mode: bool,
    reserve_typefully_numbering: bool,
    x_limit: int,
    bluesky_limit: int,
) -> Path:
    """
    Writes outputs IN PLACE into project_dir:
      - platform_posts.json
      - twitter_typefully.txt
      - bluesky_thread.txt
      - linkedin_post.txt
      - llm_raw_response.txt / llm_json_attempt.txt only on JSON parse failure
    """
    md_path = project_dir / "markdown.md"
    img_dir = project_dir / "img"
    if not md_path.exists():
        raise FileNotFoundError(f"Missing markdown.md in {project_dir}")

    draft_markdown = _read_text(md_path)
    images = _list_images(img_dir)
    images_list = "\n".join([f"- {x}" for x in images]) if images else "(none)"

    prompt = PROMPT_TEMPLATE.format(
        draft_markdown=draft_markdown,
        images_list=images_list,
        paper_url=paper_url,
        venue=venue or "(not provided)",
        tag_placeholder=tag_placeholder,
        twitter_handle=twitter_handle,
        linkedin_slug=linkedin_slug,
        bluesky_handle=bluesky_handle,
        author_name=author_name,
        coauthors=coauthors or "[Add coauthors]",
        funder=funder or "[Add funder]",
        extra_hashtags=extra_hashtags,
        voice_rules=voice_rules,
    )

    client, model = _get_client()

    kwargs = dict(
        model=model,
        messages=[
            {"role": "system", "content": SYSTEM_RULES},
            {"role": "user", "content": prompt},
        ],
        temperature=0.6,
    )

    if prefer_json_mode:
        try:
            resp = client.chat.completions.create(**kwargs, response_format={"type": "json_object"})
        except Exception:
            resp = client.chat.completions.create(**kwargs)
    else:
        resp = client.chat.completions.create(**kwargs)

    content = resp.choices[0].message.content or ""
    data = _parse_model_json(content, project_dir)

    # Always include explicit images_dir for downstream scripts (Typefully, etc.)
    data["images_dir"] = str(img_dir.resolve())

    # Warn if model references images that don't exist
    available = set(images)
    referenced = _collect_referenced_images(data)
    missing = sorted([x for x in referenced if x not in available])
    if missing:
        print(f"⚠️  {project_dir.name}: referenced images not found in img/: {missing}")

    # Enforce platform length constraints with targeted single-post rewrites
    # Note: reserve_typefully_numbering=True means we budget for Typefully prefix i/n + space
    _enforce_thread_limits_with_targeted_rewrites(
        data=data,
        platform_key="twitter",
        limit=x_limit,
        reserve_typefully_numbering=reserve_typefully_numbering,
        client=client,
        model=model,
    )
    _enforce_thread_limits_with_targeted_rewrites(
        data=data,
        platform_key="bluesky",
        limit=bluesky_limit,
        reserve_typefully_numbering=reserve_typefully_numbering,
        client=client,
        model=model,
    )

    # Save JSON
    (project_dir / "platform_posts.json").write_text(
        json.dumps(data, indent=2, ensure_ascii=False),
        encoding="utf-8",
    )

    twitter_posts = data["twitter"]["posts"]
    bluesky_posts = data["bluesky"]["posts"]
    linkedin_text = data["linkedin"]["text"]
    linkedin_images = data["linkedin"].get("images", [])

    # Apply numbering only to the .txt convenience outputs (NOT the JSON)
    twitter_txt = _maybe_number_posts(twitter_posts, number_posts)
    bluesky_txt = _maybe_number_posts(bluesky_posts, number_posts)

    _save_typefully(project_dir / "twitter_typefully.txt", twitter_txt)
    _save_thread_plain(project_dir / "bluesky_thread.txt", bluesky_txt)

    li = linkedin_text.strip()
    if linkedin_images:
        li += "\n\n" + "\n".join([f"[Attach image: {x}]" for x in linkedin_images])
    (project_dir / "linkedin_post.txt").write_text(li, encoding="utf-8")

    return project_dir


def main():
    ap = argparse.ArgumentParser()

    ap.add_argument("--outputs-dir", default="outputs", help="Path to outputs directory.")
    ap.add_argument("--project", default=None, help="Single project folder name, e.g. 0000__Schiff_et_al_2025")
    ap.add_argument("--latest", action="store_true", help="Process only the most recently modified project folder.")

    ap.add_argument(
        "--number-posts",
        action="store_true",
        help="Prefix thread posts with 1/n, 2/n... in .txt outputs only (JSON remains unnumbered).",
    )

    ap.add_argument(
        "--prefer-json-mode",
        action="store_true",
        help="Attempt to enforce strict JSON mode via response_format={type: json_object} (falls back if unsupported).",
    )

    ap.add_argument(
        "--reserve-typefully-numbering",
        action="store_true",
        default=True,
        help="Reserve space for Typefully auto-numbering when enforcing character limits (default: on).",
    )
    ap.add_argument(
        "--no-reserve-typefully-numbering",
        dest="reserve_typefully_numbering",
        action="store_false",
        help="Do NOT reserve space for Typefully auto-numbering.",
    )

    ap.add_argument("--x-limit", type=int, default=280, help="Character limit to enforce for X posts.")
    ap.add_argument("--bluesky-limit", type=int, default=300, help="Character limit to enforce for Bluesky posts.")

    ap.add_argument("--paper-url", default="", help="Fallback paper link if CSV is missing.")
    ap.add_argument("--venue", default="", help="Fallback venue if CSV is missing.")
    ap.add_argument("--urls-file", default="paper_urls.csv", help="CSV mapping prefix -> url (+ optional venue).")
    ap.add_argument("--tag-placeholder", default="[Optional: tag journal/outlet here]", help="Always appended as last line.")
    ap.add_argument("--twitter-handle", default=env_default("TWITTER_HANDLE", "Dan_Schiff"), help="Twitter/X handle without @.")
    ap.add_argument("--linkedin-slug", default=env_default("LINKEDIN_SLUG", "daniel-schiff"), help="LinkedIn profile slug.")
    ap.add_argument("--bluesky-handle", default=env_default("BLUESKY_HANDLE", "dschiff.bsky.social"), help="Bluesky handle.")
    ap.add_argument("--author-name", default=env_default("AUTHOR_NAME", "Daniel Schiff"), help="Your name for LinkedIn signoff.")
    ap.add_argument("--coauthors", default="", help="Comma-separated coauthor names (optional).")
    ap.add_argument("--funder", default="", help="Primary funder name (optional), e.g., NSF.")
    ap.add_argument("--extra-hashtags", default="#AIGovernance #ResponsibleAI", help="Space-separated hashtags to include.")
    ap.add_argument("--voice-file", default="voice_rules.txt", help="Voice rules file in repo root (optional).")
    args = ap.parse_args()

    outputs_dir = Path(args.outputs_dir)

    vf = Path(args.voice_file)
    if vf.exists():
        voice_rules = _read_text(vf)
    else:
        voice_rules = "Voice preferences: clear, direct, audience-aware. Not salesy."

    projects = _select_projects(outputs_dir, args.project, args.latest)
    script_dir = Path(__file__).resolve().parent
    urls_path = Path(args.urls_file)
    if not urls_path.is_absolute():
        urls_path = script_dir / urls_path

    meta_map = load_meta_map(urls_path)
    print("Loaded URL prefixes (first 10):", list(meta_map.keys())[:10])
    if not meta_map:
        print(f"⚠️  meta_map is empty. Looked for URLs file at: {urls_path}")


    print(f"Found {len(projects)} project(s) to postprocess.")
    for p in projects:
        try:
            for p in projects:
                if p.name.startswith("."):
                    print(f"Skipping hidden/system folder: {p.name}")
                    continue
            prefix = p.name[:4]  # e.g., "0000"
            meta = meta_map.get(prefix, {})

            paper_url = meta.get("url") or args.paper_url
            if not paper_url:
                raise RuntimeError(f"Missing URL for prefix {prefix}. Check {args.urls_file} or pass --paper-url.")

            venue = meta.get("venue") or args.venue

            proj_out = process_one(
                project_dir=p,
                paper_url=paper_url,
                venue=venue,
                tag_placeholder=args.tag_placeholder,
                twitter_handle=args.twitter_handle,
                linkedin_slug=args.linkedin_slug,
                bluesky_handle=args.bluesky_handle,
                author_name=args.author_name,
                coauthors=args.coauthors,
                funder=args.funder,
                extra_hashtags=args.extra_hashtags,
                voice_rules=voice_rules,
                number_posts=args.number_posts,
                prefer_json_mode=args.prefer_json_mode,
                reserve_typefully_numbering=args.reserve_typefully_numbering,
                x_limit=args.x_limit,
                bluesky_limit=args.bluesky_limit,
            )
            print(f"✅ Wrote: {proj_out}")
        except Exception as e:
            import traceback
            print(f"❌ Failed {p.name}: {e!r}")
            traceback.print_exc()


if __name__ == "__main__":
    main()
