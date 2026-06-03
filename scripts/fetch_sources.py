from __future__ import annotations

import json
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

from utils import (
    ROOT,
    compact_text,
    dump_json,
    extract_title_from_html,
    local_now,
    make_event,
    request_text,
    sha256_text,
    source_url,
    strip_html,
    within_window,
)


def fetch_all_sources(
    run_date: str,
    sources: List[Dict[str, Any]],
    settings: Dict[str, Any],
    offline: bool = False,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    events: List[Dict[str, Any]] = []
    failures: List[Dict[str, Any]] = []
    raw_dir = ROOT / "data" / "raw" / run_date
    raw_dir.mkdir(parents=True, exist_ok=True)

    if offline:
        return events, failures

    window_days = int(settings.get("brief", {}).get("fetch_window_days", 3))
    for source in sources:
        if source.get("enabled") is False:
            continue
        source_id = source.get("id", "unknown")
        try:
            source_events, raw_payload = fetch_source(run_date, source, window_days)
            events.extend(source_events)
            dump_json(raw_dir / f"{source_id}.json", raw_payload)
        except Exception as exc:  # Keep the daily pipeline alive on partial failures.
            failure = {
                "source_id": source_id,
                "source_name": source.get("name", source_id),
                "url": source_url(source),
                "error": str(exc),
                "fetched_at": local_now().isoformat(),
            }
            failures.append(failure)
            dump_json(raw_dir / f"{source_id}.error.json", failure)
    return events, failures


def fetch_source(
    run_date: str,
    source: Dict[str, Any],
    window_days: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    source_type = source.get("type")
    if source_type == "rss":
        return fetch_rss_source(run_date, source, window_days)
    if source_type == "html":
        return fetch_html_source(run_date, source)
    if source_type == "github_releases":
        return fetch_github_releases(run_date, source, window_days)
    if source_type == "huggingface_models":
        return fetch_huggingface_models(run_date, source, window_days)
    if source_type == "github_search":
        return fetch_github_search(run_date, source, window_days)
    raise ValueError(f"Unsupported source type: {source_type}")


def fetch_rss_source(
    run_date: str,
    source: Dict[str, Any],
    window_days: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    xml_text = fetch_text(source, str(source["url"]))
    entries = parse_feed(xml_text)
    max_items = int(source.get("max_items", 10))
    events: List[Dict[str, Any]] = []
    for entry in entries[:max_items]:
        published_at = entry.get("published_at", "")
        if not within_window(published_at, run_date, window_days):
            continue
        events.append(
            make_event(
                run_date=run_date,
                title=entry.get("title", ""),
                summary=entry.get("summary", ""),
                company=source.get("company", ""),
                product=source.get("product", ""),
                category=source.get("category", ""),
                tags=source.get("tags", []),
                credibility=source.get("credibility", "official"),
                source_name=source.get("name", ""),
                source_url_value=entry.get("link") or str(source["url"]),
                published_at=published_at,
                raw_text=entry.get("raw_text", ""),
            )
        )
    return events, {
        "source": source,
        "fetched_at": local_now().isoformat(),
        "items": entries[:max_items],
        "events_count": len(events),
    }


def fetch_html_source(run_date: str, source: Dict[str, Any]) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    html_text = fetch_text(source, str(source["url"]))
    page_title = extract_title_from_html(html_text, source.get("name", "Official page"))
    page_text = strip_html(html_text)
    content_hash = sha256_text(page_text)

    snapshot_dir = ROOT / "data" / "raw" / "snapshots"
    snapshot_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = snapshot_dir / f"{source['id']}.sha256"
    previous_hash = snapshot_path.read_text(encoding="utf-8").strip() if snapshot_path.exists() else ""
    changed = bool(previous_hash and previous_hash != content_hash)
    snapshot_path.write_text(content_hash + "\n", encoding="utf-8")

    events: List[Dict[str, Any]] = []
    if changed or source.get("emit_on_first_seen"):
        summary = (
            "检测到该官方页面内容与上次快照不同。MVP 阶段先记录官方入口，"
            "后续可为该来源增加专用解析器来抽取具体更新条目。"
        )
        events.append(
            make_event(
                run_date=run_date,
                title=f"{source.get('name', page_title)} 页面出现更新",
                summary=summary,
                company=source.get("company", ""),
                product=source.get("product", ""),
                category=source.get("category", ""),
                tags=source.get("tags", []),
                credibility=source.get("credibility", "official"),
                source_name=source.get("name", ""),
                source_url_value=str(source["url"]),
                published_at=local_now().isoformat(),
                raw_text=compact_text(page_text, 3000),
            )
        )

    return events, {
        "source": source,
        "fetched_at": local_now().isoformat(),
        "title": page_title,
        "url": source["url"],
        "hash": content_hash,
        "previous_hash": previous_hash,
        "changed": changed,
        "text_excerpt": compact_text(page_text, 2000),
        "events_count": len(events),
    }


def fetch_github_releases(
    run_date: str,
    source: Dict[str, Any],
    window_days: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    repo = source["repo"]
    per_page = int(source.get("max_items", 10))
    url = f"https://api.github.com/repos/{repo}/releases?per_page={per_page}"
    payload = json.loads(fetch_text(source, url))
    events: List[Dict[str, Any]] = []
    for item in payload[:per_page]:
        published_at = item.get("published_at") or item.get("created_at") or ""
        if not within_window(published_at, run_date, window_days):
            continue
        release_name = item.get("name") or item.get("tag_name") or "release"
        body = strip_html(item.get("body") or "")
        events.append(
            make_event(
                run_date=run_date,
                title=f"{repo} {release_name}",
                summary=body or f"{repo} 发布了 {release_name}",
                company=source.get("company", ""),
                product=source.get("product", ""),
                category=source.get("category", ""),
                tags=source.get("tags", []),
                credibility=source.get("credibility", "official"),
                source_name=source.get("name", ""),
                source_url_value=item.get("html_url") or f"https://github.com/{repo}/releases",
                published_at=published_at,
                raw_text=body,
            )
        )
    return events, {
        "source": source,
        "fetched_at": local_now().isoformat(),
        "api_url": url,
        "items": payload[:per_page],
        "events_count": len(events),
    }


def fetch_huggingface_models(
    run_date: str,
    source: Dict[str, Any],
    window_days: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    author = source["author"]
    limit = int(source.get("max_items", 10))
    query = urllib.parse.urlencode(
        {
            "author": author,
            "sort": "lastModified",
            "direction": "-1",
            "limit": str(limit),
            "full": "false",
        }
    )
    url = f"https://huggingface.co/api/models?{query}"
    payload = json.loads(fetch_text(source, url))
    events: List[Dict[str, Any]] = []
    for item in payload[:limit]:
        model_id = item.get("modelId") or item.get("id")
        if not model_id:
            continue
        published_at = item.get("lastModified") or ""
        if not within_window(published_at, run_date, window_days):
            continue
        downloads = item.get("downloads")
        likes = item.get("likes")
        stats = []
        if downloads is not None:
            stats.append(f"downloads={downloads}")
        if likes is not None:
            stats.append(f"likes={likes}")
        summary = f"Hugging Face 上的 {model_id} 最近有更新。"
        if stats:
            summary += " " + ", ".join(stats)
        events.append(
            make_event(
                run_date=run_date,
                title=f"Hugging Face 模型更新：{model_id}",
                summary=summary,
                company=source.get("company", ""),
                product=source.get("product", ""),
                category=source.get("category", ""),
                tags=source.get("tags", []),
                credibility=source.get("credibility", "official"),
                source_name=source.get("name", ""),
                source_url_value=f"https://huggingface.co/{model_id}",
                published_at=published_at,
                raw_text=json.dumps(item, ensure_ascii=False),
            )
        )
    return events, {
        "source": source,
        "fetched_at": local_now().isoformat(),
        "api_url": url,
        "items": payload[:limit],
        "events_count": len(events),
    }


def fetch_github_search(
    run_date: str,
    source: Dict[str, Any],
    window_days: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    max_items = int(source.get("max_items", 10))
    since = (datetime.fromisoformat(run_date) - timedelta(days=window_days)).date().isoformat()
    query = f"{source.get('query', 'AI')} pushed:>={since}"
    encoded = urllib.parse.urlencode({"q": query, "sort": "updated", "order": "desc", "per_page": str(max_items)})
    url = f"https://api.github.com/search/repositories?{encoded}"
    payload = json.loads(fetch_text(source, url))
    events: List[Dict[str, Any]] = []
    for item in payload.get("items", [])[:max_items]:
        pushed_at = item.get("pushed_at") or item.get("updated_at") or ""
        if not within_window(pushed_at, run_date, window_days):
            continue
        events.append(
            make_event(
                run_date=run_date,
                title=item.get("full_name") or item.get("name") or "GitHub repository",
                summary=item.get("description") or "GitHub AI 相关仓库近期更新。",
                company=source.get("company", "GitHub"),
                product=source.get("product", ""),
                category=source.get("category", ""),
                tags=source.get("tags", []),
                credibility=source.get("credibility", "community"),
                source_name=source.get("name", ""),
                source_url_value=item.get("html_url", ""),
                published_at=pushed_at,
                raw_text=json.dumps(item, ensure_ascii=False),
            )
        )
    return events, {
        "source": source,
        "fetched_at": local_now().isoformat(),
        "api_url": url,
        "items": payload.get("items", [])[:max_items],
        "events_count": len(events),
    }


def parse_feed(xml_text: str) -> List[Dict[str, str]]:
    root = ET.fromstring(xml_text.encode("utf-8"))
    if local_name(root.tag) == "rss" or root.find("./channel") is not None:
        items = root.findall("./channel/item")
        return [parse_rss_item(item) for item in items]
    entries = [node for node in root.iter() if local_name(node.tag) == "entry"]
    return [parse_atom_entry(entry) for entry in entries]


def parse_rss_item(item: ET.Element) -> Dict[str, str]:
    title = child_text(item, ["title"])
    link = child_text(item, ["link", "guid"])
    published = child_text(item, ["pubDate", "published", "updated", "date"])
    summary = child_text(item, ["description", "summary", "content"])
    return {
        "title": compact_text(strip_html(title), 220),
        "link": compact_text(link, 500),
        "published_at": compact_text(published, 100),
        "summary": compact_text(strip_html(summary), 800),
        "raw_text": compact_text(strip_html(summary), 3000),
    }


def parse_atom_entry(entry: ET.Element) -> Dict[str, str]:
    title = child_text(entry, ["title"])
    summary = child_text(entry, ["summary", "content"])
    published = child_text(entry, ["published", "updated"])
    link = ""
    for child in list(entry):
        if local_name(child.tag) == "link":
            rel = child.attrib.get("rel", "alternate")
            href = child.attrib.get("href", "")
            if href and rel in ["alternate", ""]:
                link = href
                break
    return {
        "title": compact_text(strip_html(title), 220),
        "link": compact_text(link, 500),
        "published_at": compact_text(published, 100),
        "summary": compact_text(strip_html(summary), 800),
        "raw_text": compact_text(strip_html(summary), 3000),
    }


def child_text(node: ET.Element, names: List[str]) -> str:
    wanted = set(names)
    for child in list(node):
        if local_name(child.tag) in wanted:
            return "".join(child.itertext())
    return ""


def local_name(tag: str) -> str:
    return tag.split("}", 1)[-1] if "}" in tag else tag


def fetch_text(source: Dict[str, Any], url: str) -> str:
    timeout = int(source.get("timeout_seconds", 15))
    return request_text(url, timeout=timeout)
