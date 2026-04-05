import argparse
import json
import os
from datetime import date, timedelta
from typing import Any, Dict, Optional

import requests
from dotenv import load_dotenv

load_dotenv()

TYPEFULLY_API_BASE = "https://api.typefully.com"


def _auth_headers(api_key: str) -> Dict[str, str]:
    return {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }


def _get(api_key: str, path: str, params: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    url = f"{TYPEFULLY_API_BASE}{path}"
    r = requests.get(url, headers=_auth_headers(api_key), params=params, timeout=30)
    r.raise_for_status()
    return r.json()


def cmd_social_sets(api_key: str) -> None:
    data = _get(api_key, "/v2/social-sets")
    print(json.dumps(data, indent=2))


def cmd_list_drafts(api_key: str, social_set_id: str, status: Optional[str], limit: int, offset: int) -> None:
    params: Dict[str, Any] = {"limit": limit, "offset": offset}
    if status:
        params["status"] = status
    data = _get(api_key, f"/v2/social-sets/{social_set_id}/drafts", params=params)
    print(json.dumps(data, indent=2))


def cmd_get_queue_schedule(api_key: str, social_set_id: str) -> None:
    data = _get(api_key, f"/v2/social-sets/{social_set_id}/queue/schedule")
    print(json.dumps(data, indent=2))


def cmd_get_queue(api_key: str, social_set_id: str, start_date: str, end_date: str) -> None:
    data = _get(
        api_key,
        f"/v2/social-sets/{social_set_id}/queue",
        params={"start_date": start_date, "end_date": end_date},
    )
    print(json.dumps(data, indent=2))


def cmd_analytics_x(
    api_key: str,
    social_set_id: str,
    start_date: str,
    end_date: str,
    include_replies: bool,
    limit: int,
    offset: int,
) -> None:
    data = _get(
        api_key,
        f"/v2/social-sets/{social_set_id}/analytics/x/posts",
        params={
            "start_date": start_date,
            "end_date": end_date,
            "include_replies": str(include_replies).lower(),
            "limit": limit,
            "offset": offset,
        },
    )
    print(json.dumps(data, indent=2))


def _default_window() -> tuple[str, str]:
    end = date.today()
    start = end - timedelta(days=14)
    return start.isoformat(), end.isoformat()


def main() -> None:
    ap = argparse.ArgumentParser(description="Explore Typefully v2 queue/analytics/drafts endpoints.")
    ap.add_argument("command", choices=["social-sets", "drafts", "queue-schedule", "queue", "analytics-x"])
    ap.add_argument("--social-set-id", default=os.environ.get("TYPEFULLY_SOCIAL_SET_ID", ""))
    ap.add_argument("--status", default=None, choices=["draft", "published", "scheduled", "error", "publishing", None])
    ap.add_argument("--limit", type=int, default=25)
    ap.add_argument("--offset", type=int, default=0)
    ap.add_argument("--start-date", default=None)
    ap.add_argument("--end-date", default=None)
    ap.add_argument("--include-replies", action="store_true")

    args = ap.parse_args()

    api_key = os.environ.get("TYPEFULLY_API_KEY", "").strip()
    if not api_key:
        raise SystemExit("Missing TYPEFULLY_API_KEY env var.")

    if args.command == "social-sets":
        cmd_social_sets(api_key)
        return

    social_set_id = (args.social_set_id or "").strip()
    if not social_set_id:
        raise SystemExit("Missing social_set_id. Set TYPEFULLY_SOCIAL_SET_ID or pass --social-set-id.")

    if args.command == "drafts":
        cmd_list_drafts(api_key, social_set_id, args.status, args.limit, args.offset)
        return

    if args.command == "queue-schedule":
        cmd_get_queue_schedule(api_key, social_set_id)
        return

    start_default, end_default = _default_window()
    start_date = args.start_date or start_default
    end_date = args.end_date or end_default

    if args.command == "queue":
        cmd_get_queue(api_key, social_set_id, start_date, end_date)
        return

    if args.command == "analytics-x":
        cmd_analytics_x(
            api_key,
            social_set_id,
            start_date,
            end_date,
            args.include_replies,
            args.limit,
            args.offset,
        )
        return


if __name__ == "__main__":
    main()
