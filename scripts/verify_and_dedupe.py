from __future__ import annotations

import re
from difflib import SequenceMatcher
from typing import Any, Dict, List, Tuple


CREDIBILITY_RANK = {
    "official": 4,
    "media": 3,
    "community": 2,
    "unverified": 1,
    "conflicting": 0,
}

IMPORTANCE_RANK = {"High": 3, "Medium": 2, "Low": 1}


def verify_and_dedupe(events: List[Dict[str, Any]]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    merged: List[Dict[str, Any]] = []
    duplicates: List[Dict[str, Any]] = []

    for event in events:
        match_index = find_duplicate_index(event, merged)
        if match_index is None:
            merged.append(event)
            continue

        primary = merged[match_index]
        chosen, duplicate = choose_primary(primary, event)
        chosen = merge_event_metadata(chosen, duplicate)
        duplicate["is_duplicate"] = True
        duplicate["duplicate_of"] = chosen["id"]
        duplicate["needs_follow_up"] = False if chosen.get("credibility") == "official" else duplicate.get("needs_follow_up", True)
        duplicates.append(duplicate)
        merged[match_index] = chosen

    for event in merged:
        event["is_verified"] = event.get("credibility") in ["official", "media"] or any(
            source.get("credibility") == "official" for source in event.get("secondary_sources", [])
        )
        event["needs_follow_up"] = not event["is_verified"] or event.get("credibility") == "conflicting"
    return merged, duplicates


def find_duplicate_index(event: Dict[str, Any], candidates: List[Dict[str, Any]]) -> int:
    for index, candidate in enumerate(candidates):
        if are_duplicates(event, candidate):
            return index
    return None


def are_duplicates(left: Dict[str, Any], right: Dict[str, Any]) -> bool:
    left_url = left.get("source_url") or ""
    right_url = right.get("source_url") or ""
    if left_url and right_url and normalize_url(left_url) == normalize_url(right_url):
        return True

    left_company = left.get("company") or "Other"
    right_company = right.get("company") or "Other"
    same_company = left_company == right_company and left_company != "Other"
    title_ratio = similarity(left.get("title", ""), right.get("title", ""))
    summary_ratio = similarity(
        (left.get("title", "") + " " + left.get("summary", ""))[:500],
        (right.get("title", "") + " " + right.get("summary", ""))[:500],
    )
    if same_company and title_ratio >= 0.82:
        return True
    if same_company and summary_ratio >= 0.88:
        return True
    return False


def choose_primary(left: Dict[str, Any], right: Dict[str, Any]) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    left_score = event_score(left)
    right_score = event_score(right)
    if right_score > left_score:
        return right, left
    return left, right


def event_score(event: Dict[str, Any]) -> int:
    score = CREDIBILITY_RANK.get(event.get("credibility", "unverified"), 0) * 10
    score += IMPORTANCE_RANK.get(event.get("importance", "Low"), 1)
    if not event.get("is_manual_input"):
        score += 2
    if event.get("source_url"):
        score += 1
    return score


def merge_event_metadata(primary: Dict[str, Any], duplicate: Dict[str, Any]) -> Dict[str, Any]:
    primary = dict(primary)
    sources = list(primary.get("secondary_sources", []))
    duplicate_source = {
        "source_name": duplicate.get("source_name", ""),
        "source_url": duplicate.get("source_url", ""),
        "credibility": duplicate.get("credibility", "unverified"),
        "is_manual_input": duplicate.get("is_manual_input", False),
    }
    if duplicate_source not in sources:
        sources.append(duplicate_source)
    primary["secondary_sources"] = sources
    primary["multi_source"] = len(sources) > 0

    tags = list(primary.get("tags", []))
    for tag in duplicate.get("tags", []):
        if tag not in tags:
            tags.append(tag)
    primary["tags"] = tags

    best_credibility = max(
        [primary.get("credibility", "unverified"), duplicate.get("credibility", "unverified")],
        key=lambda item: CREDIBILITY_RANK.get(item, 0),
    )
    primary["credibility"] = best_credibility
    if duplicate.get("importance") == "High":
        primary["importance"] = "High"
    elif primary.get("importance") != "High" and duplicate.get("importance") == "Medium":
        primary["importance"] = "Medium"

    if not primary.get("summary") and duplicate.get("summary"):
        primary["summary"] = duplicate["summary"]
    if not primary.get("source_url") and duplicate.get("source_url"):
        primary["source_url"] = duplicate["source_url"]
    if duplicate.get("is_manual_input"):
        primary["has_manual_input"] = True
    return primary


def similarity(left: str, right: str) -> float:
    left_norm = normalize_text(left)
    right_norm = normalize_text(right)
    if not left_norm or not right_norm:
        return 0.0
    return SequenceMatcher(None, left_norm, right_norm).ratio()


def normalize_text(value: str) -> str:
    lowered = (value or "").lower()
    lowered = re.sub(r"https?://\S+", " ", lowered)
    lowered = re.sub(r"[\W_]+", " ", lowered)
    return re.sub(r"\s+", " ", lowered).strip()


def normalize_url(value: str) -> str:
    normalized = value.strip().split("#", 1)[0]
    normalized = re.sub(r"[?&](utm_[^=&]+|ref)=[^&]+", "", normalized)
    return normalized.rstrip("/")
