from __future__ import annotations

import json
import re
import subprocess
import tempfile
import urllib.parse
import xml.etree.ElementTree as ET
from datetime import datetime, timedelta
from typing import Any, Dict, List, Tuple

from utils import (
    ROOT,
    compact_text,
    dump_json,
    extract_title_from_html,
    local_now,
    load_json,
    make_event,
    request_text,
    sha256_text,
    source_url,
    strip_html,
    within_window,
)


FOLLOW_BUILDERS_SCRIPT_URL = "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/scripts/prepare-digest.js"
FOLLOW_BUILDERS_FEED_X_URL = "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-x.json"
FOLLOW_BUILDERS_FEED_PODCASTS_URL = "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-podcasts.json"
FOLLOW_BUILDERS_FEED_BLOGS_URL = "https://raw.githubusercontent.com/zarazhangrui/follow-builders/main/feed-blogs.json"

AI_RELEVANCE_KEYWORDS = [
    "ai",
    "agi",
    "agent",
    "agentic",
    "codex",
    "claude",
    "claude code",
    "chatgpt",
    "openai",
    "anthropic",
    "gemini",
    "gpt",
    "llm",
    "model",
    "model routing",
    "token",
    "token budget",
    "context",
    "inference",
    "benchmark",
    "eval",
    "swe",
    "developer",
    "coding",
    "code",
    "github",
    "copilot",
    "cursor",
    "windsurf",
    "devin",
    "mcp",
    "rag",
    "retrieval",
    "memory",
    "workflow",
    "automation",
    "api",
    "sdk",
    "cli",
    "enterprise",
    "saas",
    "yes-code",
    "no-code",
    "prompt",
    "reasoning",
]


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
    if source_type == "follow_builders":
        return fetch_follow_builders_source(run_date, source, window_days)
    raise ValueError(f"Unsupported source type: {source_type}")


def fetch_follow_builders_source(
    run_date: str,
    source: Dict[str, Any],
    window_days: int,
) -> Tuple[List[Dict[str, Any]], Dict[str, Any]]:
    try:
        digest, adapter_mode, adapter_errors = load_follow_builders_digest(source)
    except Exception as exc:
        cached_raw_path = ROOT / "data" / "raw" / run_date / f"{source.get('id', 'follow_builders')}.json"
        cached_raw = load_json(cached_raw_path, {})
        if not source.get("reuse_cached_raw_on_failure", True) or not cached_raw.get("digest"):
            raise
        digest = cached_raw["digest"]
        adapter_mode = "cached follow-builders digest"
        adapter_errors = [f"network fetch failed, reused cached raw digest: {exc}"]
    events = events_from_follow_builders_digest(run_date, source, digest, window_days)
    return events, {
        "source": source,
        "adapter_mode": adapter_mode,
        "fetched_at": local_now().isoformat(),
        "events_count": len(events),
        "stats": digest.get("stats", {}),
        "digest_generated_at": digest.get("generatedAt"),
        "skill_errors": digest.get("errors", []),
        "adapter_errors": adapter_errors,
        "digest": digest,
    }


def load_follow_builders_digest(source: Dict[str, Any]) -> Tuple[Dict[str, Any], str, List[str]]:
    errors: List[str] = []
    if source.get("use_skill_script", True):
        try:
            return run_follow_builders_skill(source), "follow-builders prepare-digest.js", errors
        except Exception as exc:  # Fall back to the same public feeds if local Node/script execution fails.
            if not source.get("fallback_to_feeds", True):
                raise
            errors.append(f"prepare-digest.js failed, used direct feed fallback: {exc}")
    return fetch_follow_builders_feeds(source), "follow-builders public feeds fallback", errors


def run_follow_builders_skill(source: Dict[str, Any]) -> Dict[str, Any]:
    script_url = source.get("script_url") or FOLLOW_BUILDERS_SCRIPT_URL
    script_text = request_text(script_url, timeout=int(source.get("timeout_seconds", 25)))
    timeout = int(source.get("skill_timeout_seconds", 60))
    with tempfile.TemporaryDirectory(prefix="follow-builders-") as temp_dir:
        script_path = f"{temp_dir}/prepare-digest.js"
        with open(script_path, "w", encoding="utf-8") as handle:
            handle.write(script_text)
        result = subprocess.run(
            ["node", script_path],
            check=False,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    if result.returncode != 0:
        message = result.stderr.strip() or result.stdout.strip() or f"node exited with {result.returncode}"
        raise RuntimeError(compact_text(message, 500))
    try:
        payload = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"prepare-digest.js returned invalid JSON: {compact_text(result.stdout, 300)}") from exc
    if payload.get("status") == "error":
        raise RuntimeError(payload.get("message") or "prepare-digest.js returned error")
    return payload


def fetch_follow_builders_feeds(source: Dict[str, Any]) -> Dict[str, Any]:
    feed_x = json.loads(fetch_text(source, source.get("feed_x_url") or FOLLOW_BUILDERS_FEED_X_URL))
    feed_podcasts = json.loads(fetch_text(source, source.get("feed_podcasts_url") or FOLLOW_BUILDERS_FEED_PODCASTS_URL))
    feed_blogs = json.loads(fetch_text(source, source.get("feed_blogs_url") or FOLLOW_BUILDERS_FEED_BLOGS_URL))
    x_builders = feed_x.get("x", [])
    podcasts = feed_podcasts.get("podcasts", [])
    blogs = feed_blogs.get("blogs", [])
    return {
        "status": "ok",
        "generatedAt": local_now().isoformat(),
        "config": {"language": source.get("language", "zh"), "frequency": "daily", "delivery": {"method": "stdout"}},
        "x": x_builders,
        "podcasts": podcasts,
        "blogs": blogs,
        "stats": {
            "podcastEpisodes": len(podcasts),
            "xBuilders": len(x_builders),
            "totalTweets": sum(len(builder.get("tweets", [])) for builder in x_builders),
            "blogPosts": len(blogs),
            "feedGeneratedAt": feed_x.get("generatedAt") or feed_podcasts.get("generatedAt") or feed_blogs.get("generatedAt"),
        },
        "errors": [*feed_x.get("errors", []), *feed_podcasts.get("errors", []), *feed_blogs.get("errors", [])] or None,
    }


def events_from_follow_builders_digest(
    run_date: str,
    source: Dict[str, Any],
    digest: Dict[str, Any],
    window_days: int,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    events.extend(events_from_follow_builders_x(run_date, source, digest.get("x", []), window_days))
    events.extend(events_from_follow_builders_podcasts(run_date, source, digest.get("podcasts", []), window_days))
    events.extend(events_from_follow_builders_blogs(run_date, source, digest.get("blogs", []), window_days))
    return events


def events_from_follow_builders_x(
    run_date: str,
    source: Dict[str, Any],
    builders: List[Dict[str, Any]],
    window_days: int,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    max_builders = int(source.get("max_x_builders", 18))
    max_tweets = int(source.get("max_tweets_per_builder", 3))
    for builder in builders[:max_builders]:
        window_tweets = [
            tweet
            for tweet in builder.get("tweets", [])
            if within_window(tweet.get("createdAt"), run_date, window_days)
        ]
        tweets = [
            tweet
            for tweet in window_tweets
            if is_ai_relevant(tweet.get("text", ""))
        ][:max_tweets]
        if not tweets:
            continue
        first_tweet = tweets[0]
        handle = builder.get("handle", "")
        name = builder.get("name") or handle or "AI builder"
        bio = compact_text(builder.get("bio", ""), 180)
        tweet_lines = [
            f"{index}. {compact_text(tweet.get('text', ''), 180)}"
            for index, tweet in enumerate(tweets, start=1)
            if tweet.get("text")
        ]
        summary = (
            f"Follow Builders 记录到 {name}"
            f"{f'（@{handle}）' if handle else ''} 在 X 上的最新动态。"
            f"{'简介：' + bio + '。' if bio else ''}"
            f"要点：{' '.join(tweet_lines)}"
        )
        combined = " ".join([summary, bio])
        event = make_event(
            run_date=run_date,
            title=f"{name}: {compact_text(first_tweet.get('text', ''), 110)}",
            summary=summary,
            company="",
            product=f"X / @{handle}" if handle else "X",
            category="Builder 观点",
            tags=["Builder 观点", "X"],
            credibility="community",
            source_name=f"Follow Builders / @{handle}" if handle else "Follow Builders / X",
            source_url_value=first_tweet.get("url") or (f"https://x.com/{handle}" if handle else source.get("url", "")),
            published_at=first_tweet.get("createdAt", ""),
            raw_text=json.dumps({"builder": builder, "tweets": tweets}, ensure_ascii=False),
        )
        event["source_platform"] = "follow-builders"
        event["source_kind"] = "builder_x"
        event["company"] = event["company"] if event["company"] != "Other" else "Builder Ecosystem"
        event["why_it_matters"] = infer_follow_builders_why(combined, event["tags"], "builder_x")
        event["analysis"] = infer_follow_builders_analysis(combined, event["tags"], "builder_x")
        event["action_suggestion"] = "打开原始 X 链接，判断这是否只是个人观点，还是已经对应到产品、文档或可试用入口。"
        event["secondary_sources"] = [
            {
                "source_name": f"@{handle}",
                "source_url": tweet.get("url", ""),
                "credibility": "community",
            }
            for tweet in tweets[1:]
            if tweet.get("url")
        ]
        event["importance"] = follow_builders_importance(tweets, event["tags"])
        events.append(event)
    return events


def events_from_follow_builders_podcasts(
    run_date: str,
    source: Dict[str, Any],
    podcasts: List[Dict[str, Any]],
    window_days: int,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    max_podcasts = int(source.get("max_podcasts", 5))
    for episode in podcasts[:max_podcasts]:
        published_at = episode.get("publishedAt", "")
        if not within_window(published_at, run_date, max(window_days, int(source.get("podcast_window_days", 7)))):
            continue
        transcript = episode.get("transcript", "")
        excerpt = compact_text(transcript, 700)
        title = episode.get("title") or episode.get("name") or "Podcast episode"
        name = episode.get("name", "Podcast")
        summary = (
            f"Follow Builders 收录了 {name} 的一期播客：{title}。"
            f"转录摘要线索：{excerpt or '暂无转录文本。'}"
        )
        event = make_event(
            run_date=run_date,
            title=f"{name}: {title}",
            summary=summary,
            company="Podcasts / Interviews",
            product=name,
            category="Builder 访谈",
            tags=["Builder 访谈", "Podcast"],
            credibility="media",
            source_name=f"Follow Builders / {name}",
            source_url_value=episode.get("url") or source.get("url", ""),
            published_at=published_at,
            raw_text=transcript,
        )
        event["source_platform"] = "follow-builders"
        event["source_kind"] = "podcast"
        event["why_it_matters"] = infer_follow_builders_why(" ".join([title, transcript]), event["tags"], "podcast")
        event["analysis"] = infer_follow_builders_analysis(" ".join([title, transcript]), event["tags"], "podcast")
        event["action_suggestion"] = "优先听这期访谈或检索转录，提炼 builder 对产品、商业化和 Agent 工作流的原始判断。"
        if "Agent" in event["tags"] or "企业服务" in event["tags"]:
            event["importance"] = "Medium"
        events.append(event)
    return events


def events_from_follow_builders_blogs(
    run_date: str,
    source: Dict[str, Any],
    blogs: List[Dict[str, Any]],
    window_days: int,
) -> List[Dict[str, Any]]:
    events: List[Dict[str, Any]] = []
    max_blogs = int(source.get("max_blogs", 6))
    for article in blogs[:max_blogs]:
        published_at = article.get("publishedAt") or article.get("updatedAt") or ""
        if not within_window(published_at, run_date, window_days):
            continue
        title = article.get("title") or article.get("name") or "Blog post"
        body = article.get("summary") or article.get("text") or article.get("content") or ""
        source_name = article.get("name") or article.get("sourceName") or "Blog"
        event = make_event(
            run_date=run_date,
            title=f"{source_name}: {title}",
            summary=f"Follow Builders 收录了博客文章：{compact_text(body, 700) or title}",
            company="Blogs / Essays",
            product=source_name,
            category="Blog / Essay",
            tags=["Blog", "Builder 观点"],
            credibility="media",
            source_name=f"Follow Builders / {source_name}",
            source_url_value=article.get("url") or source.get("url", ""),
            published_at=published_at,
            raw_text=body,
        )
        event["source_platform"] = "follow-builders"
        event["source_kind"] = "blog"
        events.append(event)
    return events


def follow_builders_importance(tweets: List[Dict[str, Any]], tags: List[str]) -> str:
    engagement = max(
        [
            int(tweet.get("likes") or 0) + int(tweet.get("retweets") or 0) * 3 + int(tweet.get("replies") or 0)
            for tweet in tweets
        ]
        or [0]
    )
    if engagement >= 1200 or "Agent" in tags:
        return "High"
    if engagement >= 120 or any(tag in tags for tag in ["开发者工具", "企业服务", "API 更新", "产品功能"]):
        return "Medium"
    return "Low"


def is_ai_relevant(text: str) -> bool:
    haystack = (text or "").lower()
    for keyword in AI_RELEVANCE_KEYWORDS:
        if not keyword:
            continue
        if " " in keyword or "-" in keyword:
            if keyword in haystack:
                return True
            continue
        if re.search(rf"(?<![a-z0-9]){re.escape(keyword)}(?![a-z0-9])", haystack):
            return True
    return False


def infer_follow_builders_why(text: str, tags: List[str], kind: str) -> str:
    haystack = text.lower()
    if "agent" in haystack or "codex" in haystack or "claude code" in haystack or "workflow" in haystack:
        return "这类 builder 动态能更早反映 Agent 工具从演示走向日常工作流的真实用法。"
    if "enterprise" in haystack or "business" in haystack or "microsoft" in haystack or "customer" in haystack:
        return "它有助于观察 AI 从技术能力进入企业采购、业务流程和商业化落地的路径。"
    if kind == "podcast":
        return "访谈比发布稿更容易暴露 builder 的真实判断、取舍和产品路线，适合沉淀长期认知。"
    return "这不是官方公告，但来自一线 builder 的原始表达，适合作为行业温度和早期信号来源。"


def infer_follow_builders_analysis(text: str, tags: List[str], kind: str) -> str:
    haystack = text.lower()
    if "codex" in haystack or "claude code" in haystack or "agent" in haystack:
        return "初步判断：Agent 相关讨论正在从“模型能不能做”转向“如何嵌入个人和企业工作流”。"
    if "saas" in haystack or "pricing" in haystack or "business" in haystack:
        return "初步判断：AI 正在压缩窄场景软件的差异化空间，商业化更依赖工作流深度和客户上下文。"
    if kind == "podcast":
        return "初步判断：这类长访谈适合提炼 builder 的问题定义，而不是只摘录观点金句。"
    return "初步判断：需要把 builder 观点和官方产品事实分开看，避免把个人判断误读为已发布能力。"


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
