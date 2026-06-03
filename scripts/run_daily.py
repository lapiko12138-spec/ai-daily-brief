from __future__ import annotations

import argparse
import traceback
from typing import Any, Dict

from fetch_sources import fetch_all_sources
from generate_brief import generate_brief
from parse_manual_input import parse_manual_inputs
from render_html import render_all
from send_feishu import send_failure_message, send_feishu_message
from utils import ROOT, dump_json, load_yaml, today_str
from verify_and_dedupe import verify_and_dedupe


def main() -> int:
    parser = argparse.ArgumentParser(description="Generate the daily AI industry brief.")
    parser.add_argument("--date", default=today_str(), help="Run date in YYYY-MM-DD, default is today in Asia/Shanghai.")
    parser.add_argument("--offline", action="store_true", help="Skip network fetching and only process manual input.")
    parser.add_argument("--no-feishu", action="store_true", help="Do not send Feishu webhook message.")
    args = parser.parse_args()

    try:
        result = run_pipeline(args.date, offline=args.offline, no_feishu=args.no_feishu)
        print(f"Generated: {result['daily_path']}")
        print(f"Index: {result['index_path']}")
        print(f"Events: {result['stats']['total_events']}, failures: {result['stats']['source_failures']}")
        if result.get("feishu"):
            print(f"Feishu: {result['feishu']}")
        return 0
    except Exception as exc:
        error_text = "".join(traceback.format_exception_only(type(exc), exc)).strip()
        print(error_text)
        print(traceback.format_exc())
        if not args.no_feishu:
            send_failure_message(args.date, error_text)
        return 1


def run_pipeline(run_date: str, offline: bool = False, no_feishu: bool = False) -> Dict[str, Any]:
    settings = load_yaml(ROOT / "config" / "settings.yaml")
    sources_config = load_yaml(ROOT / "config" / "sources.yaml")
    sources = sources_config.get("sources", [])

    fetched_events, failures = fetch_all_sources(run_date, sources, settings, offline=offline)
    manual_events, manual_meta = parse_manual_inputs(run_date)
    all_events = fetched_events + manual_events
    merged_events, duplicates = verify_and_dedupe(all_events)

    processed_dir = ROOT / "data" / "processed" / run_date
    dump_json(processed_dir / "events.json", merged_events)
    dump_json(processed_dir / "duplicates.json", duplicates)
    dump_json(processed_dir / "failures.json", failures)
    dump_json(processed_dir / "manual_meta.json", manual_meta)

    brief = generate_brief(run_date, merged_events, duplicates, failures, manual_meta, settings)
    dump_json(processed_dir / "brief.json", brief)

    rendered = render_all(run_date, brief, settings)
    feishu_result = None
    if not no_feishu:
        feishu_result = send_feishu_message(brief)

    return {
        **rendered,
        "stats": brief["stats"],
        "feishu": feishu_result,
    }


if __name__ == "__main__":
    raise SystemExit(main())
