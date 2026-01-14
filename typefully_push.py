import argparse
import json
import mimetypes
import os
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import requests

from dotenv import load_dotenv
load_dotenv()



TYPEFULLY_API_BASE = "https://api.typefully.com"
api_key = os.environ.get("TYPEFULLY_API_KEY", "").strip()


# -----------------------------
# HTTP helpers
# -----------------------------

def _auth_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }

print("Using key prefix:", api_key[:6], "len:", len(api_key))

def get_social_sets(api_key: str) -> Dict[str, Any]:
    """List social sets so you can pick the right ID."""
    r = requests.get(
        f"{TYPEFULLY_API_BASE}/v2/social-sets",
        headers=_auth_headers(api_key),
        timeout=30,
    )
    r.raise_for_status()
    return r.json()


def request_media_upload(api_key: str, social_set_id: str, file_name: str) -> Tuple[str, str]:
    """
    Step 1: Get presigned URL for upload.
    POST /v2/social-sets/{id}/media/upload with {"file_name": "..."}
    """
    url = f"{TYPEFULLY_API_BASE}/v2/social-sets/{social_set_id}/media/upload"
    r = requests.post(url, headers=_auth_headers(api_key), json={"file_name": file_name}, timeout=30)
    r.raise_for_status()
    data = r.json()
    media_id = data.get("media_id")
    upload_url = data.get("upload_url")
    if not media_id or not upload_url:
        raise RuntimeError(f"Unexpected media/upload response: {data}")
    return media_id, upload_url


def put_file_to_presigned_url(upload_url: str, file_path: Path) -> None:
    """
    Step 2: Upload to S3 with PUT upload_url (binary).
    For presigned URLs, avoid extra headers and avoid chunked transfer.
    """
    data = file_path.read_bytes()  # ensures Content-Length is set
    r = requests.put(upload_url, data=data, timeout=120)
    if r.status_code >= 400:
        raise requests.HTTPError(
            f"Presigned upload failed: {r.status_code}\nResponse: {r.text[:500]}",
            response=r,
        )


def wait_for_media_ready(api_key: str, social_set_id: str, media_id: str, max_wait_s: int = 60) -> Dict[str, Any]:
    """
    Step 3: Poll GET /v2/social-sets/{id}/media/{media_id} until status is ready/failed.
    """
    url = f"{TYPEFULLY_API_BASE}/v2/social-sets/{social_set_id}/media/{media_id}"
    start = time.time()
    while True:
        r = requests.get(url, headers=_auth_headers(api_key), timeout=30)
        r.raise_for_status()
        data = r.json()
        status = data.get("status")
        if status in ("ready", "failed"):
            return data
        if time.time() - start > max_wait_s:
            raise TimeoutError(f"Media {media_id} did not become ready within {max_wait_s}s. Last: {data}")
        time.sleep(1.5)


# -----------------------------
# Path resolution
# -----------------------------

def _expand_path(p: str) -> Path:
    return Path(os.path.expandvars(os.path.expanduser(p)))


def infer_images_dir(data: Dict[str, Any], json_path: Path, images_dir_arg: Optional[Path]) -> Path:
    """
    Priority:
      1) JSON field "images_dir" (written by postprocess.py)
      2) CLI --images-dir
      3) <json folder>/img if exists
      4) <json folder>
    """
    if isinstance(data.get("images_dir"), str) and data["images_dir"].strip():
        return _expand_path(data["images_dir"]).resolve()

    if images_dir_arg is not None:
        return images_dir_arg.resolve()

    candidate = (json_path.parent / "img")
    if candidate.exists() and candidate.is_dir():
        return candidate.resolve()

    return json_path.parent.resolve()


def resolve_image_path(images_dir: Path, json_path: Path, img_value: str) -> Path:
    """
    Robust resolution for:
      - absolute paths
      - basenames like "img_0.jpg"
      - relative paths like "img/img_0.jpg"
    Tries:
      1) absolute(img_value)
      2) json_path.parent / img_value
      3) images_dir / img_value
    """
    p = Path(img_value)

    if p.is_absolute():
        return p

    # try relative to JSON file folder first
    p1 = (json_path.parent / p)
    if p1.exists():
        return p1

    # then relative to inferred images_dir
    p2 = (images_dir / p)
    if p2.exists():
        return p2

    raise FileNotFoundError(
        "Image not found. Tried:\n"
        f"  - {p1}\n"
        f"  - {p2}\n"
        f"Original image field: {img_value}"
    )


# -----------------------------
# Media upload with caching
# -----------------------------

def upload_media_if_needed(
    api_key: str,
    social_set_id: str,
    images_dir: Path,
    json_path: Path,
    image_value: str,
    cache: Dict[str, str],
) -> str:
    """
    Upload one image if not already uploaded in this run.
    image_value may be basename or path.
    Returns media_id.
    """
    cache_key = image_value.strip()
    if cache_key in cache:
        return cache[cache_key]

    file_path = resolve_image_path(images_dir, json_path, image_value)
    file_name = file_path.name  # what Typefully sees

    media_id, upload_url = request_media_upload(api_key, social_set_id, file_name)
    put_file_to_presigned_url(upload_url, file_path)

    status = wait_for_media_ready(api_key, social_set_id, media_id)
    if status.get("status") != "ready":
        raise RuntimeError(f"Media processing failed for {file_name}: {status}")

    cache[cache_key] = media_id
    return media_id


# -----------------------------
# Text cleanup
# -----------------------------

def maybe_strip_manual_numbering(text: str) -> str:
    """
    Conservative stripping of manual numbering at the *very start* of a post:
      - "1/ " or "12/ "
      - "1) " or "12) "
      - "1. " or "12. "
      - "1: " or "12: "
    """
    t = text.lstrip()

    # Find leading digits
    i = 0
    while i < len(t) and t[i].isdigit():
        i += 1
    if i == 0:
        return t  # no leading number

    # Must be one of these separators
    if i < len(t) and t[i] in ("/", ")", ".", ":"):
        # require a space after separator OR end-of-string
        j = i + 1
        if j == len(t):
            return ""  # it was just "1/" etc
        if t[j].isspace():
            return t[j:].lstrip()

    return t


# -----------------------------
# Payload builders
# -----------------------------

def build_typefully_platform_posts(
    api_key: str,
    social_set_id: str,
    platform_blob: Any,
    images_dir: Path,
    json_path: Path,
    media_cache: Dict[str, str],
    strip_numbering: bool = True,
) -> List[Dict[str, Any]]:
    """
    Convert your per-platform structure into Typefully v2 posts:
      - For threads: [{"text": "...", "media_ids": [...]?}, ...]
      - For single post: [{"text": "...", "media_ids": [...]?}]
    """
    posts_out: List[Dict[str, Any]] = []

    # twitter/bluesky: {"posts": [{"text":..., "image": "img_0.jpg"|null}, ...]}
    if isinstance(platform_blob, dict) and "posts" in platform_blob:
        for p in platform_blob.get("posts") or []:
            text = (p.get("text") or "")
            if strip_numbering:
                text = maybe_strip_manual_numbering(text)

            out: Dict[str, Any] = {"text": text}
            img = p.get("image")

            if isinstance(img, str) and img.strip():
                media_id = upload_media_if_needed(
                    api_key=api_key,
                    social_set_id=social_set_id,
                    images_dir=images_dir,
                    json_path=json_path,
                    image_value=img,
                    cache=media_cache,
                )
                out["media_ids"] = [media_id]

            posts_out.append(out)

        return posts_out

    # linkedin: {"text": "...", "images": ["img_1.jpg", ...]}
    if isinstance(platform_blob, dict) and "text" in platform_blob:
        text = platform_blob.get("text") or ""
        if strip_numbering:
            text = maybe_strip_manual_numbering(text)

        out2: Dict[str, Any] = {"text": text}
        imgs = platform_blob.get("images") or []
        if imgs:
            media_ids: List[str] = []
            for img in imgs:
                if not isinstance(img, str) or not img.strip():
                    continue
                media_ids.append(
                    upload_media_if_needed(
                        api_key=api_key,
                        social_set_id=social_set_id,
                        images_dir=images_dir,
                        json_path=json_path,
                        image_value=img,
                        cache=media_cache,
                    )
                )
            if media_ids:
                out2["media_ids"] = media_ids

        return [out2]

    raise ValueError(f"Unrecognized platform structure: {platform_blob}")


def create_typefully_draft(
    api_key: str,
    social_set_id: str,
    platforms_payload: Dict[str, Any],
    tags: Optional[List[str]] = None,
) -> Dict[str, Any]:
    """
    POST /v2/social-sets/{id}/drafts with {"platforms": {...}, "tags": [...?]}
    """
    url = f"{TYPEFULLY_API_BASE}/v2/social-sets/{social_set_id}/drafts"
    body: Dict[str, Any] = {"platforms": platforms_payload}
    if tags:
        body["tags"] = tags

    r = requests.post(url, headers=_auth_headers(api_key), json=body, timeout=30)
    r.raise_for_status()
    return r.json()


def create_draft_from_platform_posts_json(
    json_path: Path,
    api_key: str,
    social_set_id: str,
    include_platforms: Tuple[str, ...] = ("x", "linkedin", "bluesky"),
    strip_numbering: bool = True,
    tags: Optional[List[str]] = None,
    images_dir_override: Optional[Path] = None,
) -> Dict[str, Any]:
    """
    Reads your JSON format and creates a Typefully draft with selected platforms enabled.
    """
    data = json.loads(json_path.read_text(encoding="utf-8"))

    # map your keys -> Typefully platform keys
    key_map = {
        "twitter": "x",
        "linkedin": "linkedin",
        "bluesky": "bluesky",
    }

    images_dir = infer_images_dir(data, json_path, images_dir_override)

    media_cache: Dict[str, str] = {}
    platforms_payload: Dict[str, Any] = {}

    for src_key, tf_key in key_map.items():
        if tf_key not in include_platforms:
            continue
        if src_key not in data:
            continue

        posts = build_typefully_platform_posts(
            api_key=api_key,
            social_set_id=social_set_id,
            platform_blob=data[src_key],
            images_dir=images_dir,
            json_path=json_path,
            media_cache=media_cache,
            strip_numbering=strip_numbering,
        )
        platforms_payload[tf_key] = {"enabled": True, "posts": posts}

    if not platforms_payload:
        raise RuntimeError("No platforms payload created. Check include_platforms and JSON keys.")

    return create_typefully_draft(
        api_key=api_key,
        social_set_id=social_set_id,
        platforms_payload=platforms_payload,
        tags=tags,
    )


# -----------------------------
# CLI
# -----------------------------

def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Create a Typefully draft from platform_posts.json")

    ap.add_argument("--json", dest="json_path", default="platform_posts.json", help="Path to platform_posts.json")
    ap.add_argument(
        "--images-dir",
        dest="images_dir",
        default=None,
        help="Override images directory (otherwise inferred from JSON or <json>/img).",
    )
    ap.add_argument(
        "--platforms",
        nargs="+",
        default=["x", "linkedin", "bluesky"],
        help="Platforms to include (Typefully keys): x linkedin bluesky",
    )
    ap.add_argument("--no-strip-numbering", action="store_true", help="Do not strip manual numbering prefixes.")
    ap.add_argument("--tags", nargs="*", default=None, help="Optional Typefully tags")
    ap.add_argument("--list-social-sets", action="store_true", help="List social sets and exit.")
    return ap.parse_args()


if __name__ == "__main__":
    args = _parse_args()

    api_key = os.environ.get("TYPEFULLY_API_KEY", "").strip()
    social_set_id = os.environ.get("TYPEFULLY_SOCIAL_SET_ID", "").strip()

    if not api_key:
        raise SystemExit("Missing TYPEFULLY_API_KEY env var.")

    if args.list_social_sets:
        data = get_social_sets(api_key)
        print(json.dumps(data, indent=2))
        raise SystemExit(0)

    if not social_set_id:
        raise SystemExit("Missing TYPEFULLY_SOCIAL_SET_ID env var. Use --list-social-sets to find it.")

    json_path = Path(args.json_path).resolve()
    if not json_path.exists():
        raise SystemExit(f"JSON file not found: {json_path}")

    images_dir_override = Path(args.images_dir).resolve() if args.images_dir else None
    include_platforms = tuple(args.platforms)

    result = create_draft_from_platform_posts_json(
        json_path=json_path,
        api_key=api_key,
        social_set_id=social_set_id,
        include_platforms=include_platforms,
        strip_numbering=(not args.no_strip_numbering),
        tags=args.tags,
        images_dir_override=images_dir_override,
    )

    print("Created draft:", result.get("id", result))
