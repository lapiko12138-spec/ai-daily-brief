from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from jinja2 import Environment, FileSystemLoader, select_autoescape

from utils import ROOT, load_json


def render_all(run_date: str, brief: Dict[str, Any], settings: Dict[str, Any]) -> Dict[str, str]:
    env = Environment(
        loader=FileSystemLoader(str(ROOT / "templates")),
        autoescape=select_autoescape(["html", "xml"]),
        trim_blocks=True,
        lstrip_blocks=True,
    )
    env.filters["importance_class"] = importance_class
    env.filters["credibility_class"] = credibility_class

    docs_dir = ROOT / "docs"
    daily_dir = docs_dir / "daily"
    daily_dir.mkdir(parents=True, exist_ok=True)

    daily_template = env.get_template("daily_template.html")
    daily_html = daily_template.render(brief=brief, settings=settings)
    daily_path = daily_dir / f"{run_date}.html"
    daily_path.write_text(daily_html, encoding="utf-8")

    index_template = env.get_template("index_template.html")
    recent = collect_recent_briefs(settings)
    index_html = index_template.render(recent=recent, settings=settings)
    index_path = docs_dir / "index.html"
    index_path.write_text(index_html, encoding="utf-8")

    return {
        "daily_path": str(daily_path.relative_to(ROOT)),
        "index_path": str(index_path.relative_to(ROOT)),
    }


def collect_recent_briefs(settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    limit = int(settings.get("site", {}).get("homepage_recent_days", 7))
    processed_root = ROOT / "data" / "processed"
    briefs: List[Dict[str, Any]] = []
    for path in sorted(processed_root.glob("*/brief.json"), reverse=True):
        brief = load_json(path, {})
        if not brief:
            continue
        briefs.append(
            {
                "date": brief.get("date"),
                "title": brief.get("title"),
                "href": f"daily/{brief.get('date')}.html",
                "core_summary": brief.get("core_summary", [])[:3],
                "stats": brief.get("stats", {}),
            }
        )
        if len(briefs) >= limit:
            break
    return briefs


def importance_class(value: str) -> str:
    return {
        "High": "badge-high",
        "Medium": "badge-medium",
        "Low": "badge-low",
    }.get(value, "badge-low")


def credibility_class(value: str) -> str:
    return {
        "official": "badge-official",
        "media": "badge-media",
        "community": "badge-community",
        "unverified": "badge-unverified",
        "conflicting": "badge-conflicting",
    }.get(value, "badge-unverified")
