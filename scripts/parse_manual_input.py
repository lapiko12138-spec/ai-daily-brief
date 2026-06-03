from __future__ import annotations

import re
from pathlib import Path
from typing import Any, Dict, List, Tuple

from utils import ROOT, compact_text, credibility_from_url, infer_company, make_event


URL_RE = re.compile(r"https?://[^\s)\]>\"']+")


def parse_manual_inputs(run_date: str) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    manual_dir = ROOT / "data" / "manual_input"
    candidates = [
        manual_dir / f"{run_date}.md",
        manual_dir / f"{run_date}.txt",
    ]
    events: List[Dict[str, Any]] = []
    files_read: List[str] = []
    for path in candidates:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8")
        files_read.append(str(path.relative_to(ROOT)))
        for item in split_manual_items(text):
            event = manual_item_to_event(run_date, item)
            if event:
                events.append(event)
    return events, {"files_read": files_read, "events_count": len(events)}


def split_manual_items(text: str) -> List[str]:
    normalized = text.replace("\r\n", "\n")
    blocks: List[str] = []
    current: List[str] = []
    for raw_line in normalized.split("\n"):
        line = raw_line.rstrip()
        starts_item = bool(re.match(r"^\s*(#{1,4}\s+|[-*]\s+|\d+[.)、]\s+)", line))
        if starts_item and current:
            blocks.append("\n".join(current).strip())
            current = [line]
        else:
            if line.strip() or current:
                current.append(line)
    if current:
        blocks.append("\n".join(current).strip())

    if len(blocks) <= 1:
        paragraphs = [part.strip() for part in re.split(r"\n\s*\n", normalized) if part.strip()]
        blocks = paragraphs

    cleaned = []
    for block in blocks:
        item = re.sub(r"^\s*(#{1,4}\s+|[-*]\s+|\d+[.)、]\s+)", "", block).strip()
        if len(item) >= 12:
            cleaned.append(item)
    return cleaned


def manual_item_to_event(run_date: str, item: str) -> Dict[str, Any]:
    urls = URL_RE.findall(item)
    source_url = urls[0] if urls else ""
    credibility = credibility_from_url(source_url, "unverified")
    lines = [line.strip(" -*#\t") for line in item.splitlines() if line.strip()]
    title = compact_text(lines[0] if lines else item, 180)
    summary = compact_text(" ".join(lines[1:]) if len(lines) > 1 else item, 600)
    company = infer_company(item)
    tags = []
    if credibility == "unverified":
        tags.append("待核实")
    return make_event(
        run_date=run_date,
        title=title,
        summary=summary,
        company=company,
        product="",
        category="手动日报",
        tags=tags,
        credibility=credibility,
        source_name="Manual input",
        source_url_value=source_url,
        published_at="",
        raw_text=item,
        is_manual_input=True,
    )
