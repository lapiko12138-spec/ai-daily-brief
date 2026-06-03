from __future__ import annotations

import hashlib
import html
import json
import os
import re
import urllib.error
import urllib.parse
import urllib.request
from datetime import date, datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional

import yaml


ROOT = Path(__file__).resolve().parents[1]
LOCAL_TZ = timezone(timedelta(hours=8))


def load_yaml(path: Path) -> Dict[str, Any]:
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def dump_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as handle:
        json.dump(payload, handle, ensure_ascii=False, indent=2)
        handle.write("\n")


def load_json(path: Path, default: Any = None) -> Any:
    if not path.exists():
        return default
    with path.open("r", encoding="utf-8") as handle:
        return json.load(handle)


def local_now() -> datetime:
    return datetime.now(LOCAL_TZ)


def today_str() -> str:
    return local_now().date().isoformat()


def parse_date(value: Optional[str]) -> Optional[datetime]:
    if not value:
        return None
    text = value.strip()
    if not text:
        return None
    try:
        parsed = parsedate_to_datetime(text)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(LOCAL_TZ)
    except (TypeError, ValueError):
        pass
    candidates = [
        text,
        text.replace("Z", "+00:00"),
    ]
    for candidate in candidates:
        try:
            parsed = datetime.fromisoformat(candidate)
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=LOCAL_TZ)
            return parsed.astimezone(LOCAL_TZ)
        except ValueError:
            continue
    match = re.search(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})", text)
    if match:
        year, month, day = [int(part) for part in match.groups()]
        return datetime(year, month, day, tzinfo=LOCAL_TZ)
    return None


def iso_or_empty(value: Optional[str]) -> str:
    parsed = parse_date(value)
    return parsed.isoformat() if parsed else (value or "")


def within_window(published_at: Optional[str], run_date: str, days: int) -> bool:
    if not published_at:
        return True
    parsed = parse_date(published_at)
    if not parsed:
        return True
    run_day = datetime.fromisoformat(run_date).replace(tzinfo=LOCAL_TZ)
    earliest = run_day - timedelta(days=days)
    latest = run_day + timedelta(days=1)
    return earliest <= parsed <= latest


def compact_text(value: str, limit: Optional[int] = None) -> str:
    cleaned = re.sub(r"\s+", " ", value or "").strip()
    if limit and len(cleaned) > limit:
        return cleaned[: limit - 1].rstrip() + "..."
    return cleaned


def strip_html(value: str) -> str:
    text = re.sub(r"(?is)<(script|style).*?>.*?</\1>", " ", value or "")
    text = re.sub(r"(?s)<[^>]+>", " ", text)
    return compact_text(html.unescape(text))


def extract_title_from_html(value: str, fallback: str) -> str:
    match = re.search(r"(?is)<title[^>]*>(.*?)</title>", value or "")
    if match:
        return compact_text(html.unescape(re.sub(r"<[^>]+>", " ", match.group(1))), 160)
    return fallback


def sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8", errors="ignore")).hexdigest()


def stable_id(parts: Iterable[str]) -> str:
    seed = "|".join([part or "" for part in parts])
    return hashlib.sha1(seed.encode("utf-8", errors="ignore")).hexdigest()[:16]


class Redirect308Handler(urllib.request.HTTPRedirectHandler):
    def http_error_308(self, req, fp, code, msg, headers):
        return self.http_error_302(req, fp, code, msg, headers)


def request_text(url: str, timeout: int = 25) -> str:
    headers = {
        "User-Agent": "ai-daily-brief/0.1 (+https://github.com/)",
        "Accept": "application/rss+xml, application/atom+xml, application/json, text/html;q=0.9, */*;q=0.8",
    }
    token = os.getenv("GITHUB_TOKEN")
    if token and "api.github.com" in url:
        headers["Authorization"] = f"Bearer {token}"
    request = urllib.request.Request(url, headers=headers)
    try:
        opener = urllib.request.build_opener(Redirect308Handler)
        with opener.open(request, timeout=timeout) as response:
            charset = response.headers.get_content_charset() or "utf-8"
            return response.read().decode(charset, errors="replace")
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"HTTP {exc.code} for {url}: {compact_text(body, 240)}") from exc
    except urllib.error.URLError as exc:
        raise RuntimeError(f"Failed to fetch {url}: {exc.reason}") from exc


def source_url(source: Dict[str, Any]) -> str:
    if source.get("url"):
        return str(source["url"])
    if source.get("repo"):
        return f"https://github.com/{source['repo']}"
    if source.get("author"):
        return f"https://huggingface.co/{source['author']}"
    return ""


def domain_for(url: str) -> str:
    try:
        return urllib.parse.urlparse(url).netloc.lower()
    except Exception:
        return ""


def credibility_from_url(url: str, fallback: str = "unverified") -> str:
    domain = domain_for(url)
    official_domains = [
        "openai.com",
        "platform.openai.com",
        "developers.openai.com",
        "anthropic.com",
        "docs.anthropic.com",
        "deepmind.google",
        "blog.google",
        "ai.google.dev",
        "cloud.google.com",
        "ai.meta.com",
        "x.ai",
        "docs.x.ai",
        "mistral.ai",
        "docs.mistral.ai",
        "blogs.microsoft.com",
        "github.blog",
        "techcommunity.microsoft.com",
        "aws.amazon.com",
        "docs.aws.amazon.com",
        "docs.perplexity.ai",
        "huggingface.co",
    ]
    if any(domain == item or domain.endswith("." + item) for item in official_domains):
        return "official"
    if domain:
        return fallback if fallback != "unverified" else "community"
    return fallback


def infer_company(text: str) -> str:
    haystack = (text or "").lower()
    mapping = [
        ("OpenAI", ["openai", "chatgpt", "gpt-", "sora", "codex"]),
        ("Anthropic", ["anthropic", "claude"]),
        ("Google / DeepMind", ["google", "deepmind", "gemini", "vertex ai", "notebooklm"]),
        ("Meta AI", ["meta ai", "llama", "meta-llama"]),
        ("xAI", ["xai", "x.ai", "grok"]),
        ("Mistral AI", ["mistral"]),
        ("Microsoft", ["microsoft", "azure ai", "github copilot", "copilot studio", "phi"]),
        ("Amazon / AWS", ["amazon", "aws", "bedrock", "nova"]),
        ("Perplexity", ["perplexity"]),
        ("Hugging Face", ["hugging face", "huggingface"]),
        ("GitHub", ["github"]),
    ]
    for company, keywords in mapping:
        if any(keyword in haystack for keyword in keywords):
            return company
    return "Other"


def infer_tags(text: str, existing: Optional[List[str]] = None) -> List[str]:
    tags = list(existing or [])
    haystack = (text or "").lower()
    keyword_tags = [
        ("模型更新", ["model", "gpt", "claude", "gemini", "llama", "mistral", "grok", "nova", "phi"]),
        ("API 更新", ["api", "sdk", "endpoint", "rate limit", "tool call", "function calling"]),
        ("产品功能", ["chatgpt", "product", "feature", "app", "workspace", "browser"]),
        ("Agent", ["agent", "codex", "claude code", "gemini cli", "mcp", "workflow"]),
        ("多模态", ["multimodal", "image", "audio", "video", "vision", "sora"]),
        ("开发者工具", ["developer", "cli", "sdk", "github", "copilot", "code"]),
        ("价格变化", ["price", "pricing", "cost", "discount"]),
        ("企业服务", ["enterprise", "business", "azure", "aws", "cloud", "bedrock", "vertex"]),
        ("开源模型", ["open source", "open-source", "weights", "hugging face", "llama"]),
        ("论文研究", ["research", "paper", "arxiv", "benchmark"]),
        ("算力/基础设施", ["infrastructure", "gpu", "training", "inference", "compute"]),
        ("生态合作", ["partner", "partnership", "ecosystem", "integration"]),
        ("安全与合规", ["safety", "security", "policy", "compliance", "alignment"]),
    ]
    for tag, keywords in keyword_tags:
        if any(keyword in haystack for keyword in keywords) and tag not in tags:
            tags.append(tag)
    return tags[:8]


def infer_importance(text: str, credibility: str, tags: List[str]) -> str:
    haystack = (text or "").lower()
    high_keywords = [
        "new model",
        "launch",
        "release",
        "general availability",
        "price",
        "pricing",
        "agent",
        "codex",
        "claude code",
        "gemini cli",
        "context",
        "api",
        "gpt",
        "claude",
        "gemini",
        "llama",
    ]
    if credibility == "official" and any(keyword in haystack for keyword in high_keywords):
        return "High"
    if credibility == "official" or any(tag in tags for tag in ["API 更新", "Agent", "模型更新", "开源模型"]):
        return "Medium"
    return "Low"


def category_from_tags(tags: List[str], fallback: str = "Other") -> str:
    preferred = [
        "模型更新",
        "API 更新",
        "Agent",
        "开发者工具",
        "产品功能",
        "开源模型",
        "多模态",
        "企业服务",
        "价格变化",
        "论文研究",
    ]
    for tag in preferred:
        if tag in tags:
            return tag
    return tags[0] if tags else fallback


def make_event(
    *,
    run_date: str,
    title: str,
    summary: str,
    company: str,
    product: str,
    category: str,
    tags: List[str],
    credibility: str,
    source_name: str,
    source_url_value: str,
    published_at: str = "",
    raw_text: str = "",
    is_manual_input: bool = False,
) -> Dict[str, Any]:
    title = compact_text(title, 220) or "Untitled update"
    summary = compact_text(summary, 600)
    combined = " ".join([title, summary, company, product])
    tags = infer_tags(combined, tags)
    if not company or company == "Other":
        company = infer_company(combined)
    if not category:
        category = category_from_tags(tags)
    importance = infer_importance(combined, credibility, tags)
    event_id = stable_id([run_date, company, product, title, source_url_value])
    why = default_why_it_matters(tags, company)
    action = default_action_suggestion(tags, source_url_value)
    return {
        "id": event_id,
        "date": run_date,
        "title": title,
        "title_zh": "",
        "summary": summary or title,
        "company": company or "Other",
        "product": product or "",
        "category": category_from_tags(tags, category or "Other"),
        "tags": tags,
        "importance": importance,
        "credibility": credibility or "unverified",
        "source_name": source_name or "",
        "source_url": source_url_value or "",
        "published_at": iso_or_empty(published_at),
        "fetched_at": local_now().isoformat(),
        "raw_text": compact_text(raw_text or summary or title, 3000),
        "is_manual_input": is_manual_input,
        "is_duplicate": False,
        "duplicate_of": "",
        "is_verified": credibility in ["official", "media"],
        "needs_follow_up": credibility in ["unverified", "conflicting"],
        "analysis": default_analysis(tags, company),
        "why_it_matters": why,
        "action_suggestion": action,
        "secondary_sources": [],
        "multi_source": False,
    }


def default_why_it_matters(tags: List[str], company: str) -> str:
    if "Agent" in tags or "开发者工具" in tags:
        return "这类更新关系到 AI 从回答工具走向可执行工作流的速度，值得观察实际可用性和生态绑定。"
    if "API 更新" in tags:
        return "API 能力变化会直接影响开发者接入成本、产品边界和企业集成节奏。"
    if "模型更新" in tags:
        return "模型能力更新通常会改变多模型竞争格局，也会影响上层应用可实现的功能范围。"
    if "开源模型" in tags:
        return "开源模型更新会影响开发者自部署、私有化和成本控制选择。"
    if "企业服务" in tags:
        return "企业 AI 服务更新往往反映商业化落地、云平台绑定和采购路径变化。"
    return f"这是 {company or '相关公司'} 的官方或生态动态，适合纳入每日行业观察。"


def default_analysis(tags: List[str], company: str) -> str:
    if "Agent" in tags:
        return "初步判断：这个方向的核心价值不在单次对话，而在把模型能力接入真实任务链路。"
    if "API 更新" in tags:
        return "初步判断：需要继续核对具体接口、价格、限制和迁移成本，避免只看发布标题。"
    if "模型更新" in tags:
        return "初步判断：需要把能力描述和可验证的 API / 产品入口分开看，防止过度解读。"
    return "初步判断：信息本身值得记录，后续需要结合官方细节和开发者反馈判断影响。"


def default_action_suggestion(tags: List[str], url: str) -> str:
    if "API 更新" in tags:
        return "打开官方链接，记录接口能力、限制和可能影响现有工作流的变化。"
    if "Agent" in tags or "开发者工具" in tags:
        return "判断是否适合放入个人 Agent / 自动化工作流试用清单。"
    if "开源模型" in tags:
        return "收藏模型页面，观察许可证、推理成本、社区评测和部署条件。"
    if url:
        return "优先阅读原始来源，确认发布时间、适用范围和是否已有可用入口。"
    return "等待更多可靠来源确认。"


def public_page_url(run_date: str, settings: Dict[str, Any]) -> str:
    explicit = os.getenv("SITE_BASE_URL") or settings.get("site", {}).get("base_url") or ""
    if explicit:
        return explicit.rstrip("/") + f"/daily/{run_date}.html"
    repository = os.getenv("GITHUB_REPOSITORY")
    if repository and "/" in repository:
        owner, repo = repository.split("/", 1)
        return f"https://{owner}.github.io/{repo}/daily/{run_date}.html"
    return f"docs/daily/{run_date}.html"
