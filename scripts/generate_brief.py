from __future__ import annotations

from typing import Any, Dict, List

from utils import local_now, public_page_url


COMPANY_ORDER = [
    "OpenAI",
    "Anthropic",
    "Google / DeepMind",
    "Meta AI",
    "xAI",
    "Mistral AI",
    "Microsoft",
    "Amazon / AWS",
    "Perplexity",
    "Hugging Face",
    "GitHub",
    "Other",
]

IMPORTANCE_RANK = {"High": 3, "Medium": 2, "Low": 1}

AGENT_KEYWORDS = [
    "codex",
    "claude code",
    "gemini cli",
    "cursor",
    "windsurf",
    "devin",
    "mcp",
    "rag",
    "agent",
    "router",
    "workflow",
]


def generate_brief(
    run_date: str,
    events: List[Dict[str, Any]],
    duplicates: List[Dict[str, Any]],
    failures: List[Dict[str, Any]],
    manual_meta: Dict[str, Any],
    settings: Dict[str, Any],
) -> Dict[str, Any]:
    sorted_events = sorted(events, key=event_sort_key, reverse=True)
    core_items = build_core_summary(sorted_events, settings)
    company_updates = build_company_updates(sorted_events)
    deep_dives = build_deep_dives(sorted_events, settings)
    agent_tools = build_agent_tools(sorted_events)
    model_api_changes = build_model_api_changes(sorted_events)
    manual_review = build_manual_review(events, duplicates)
    cognition = build_cognition_items(sorted_events, settings)
    actions = build_action_items(sorted_events, settings)

    stats = {
        "total_events": len(events),
        "manual_events": len([event for event in events if event.get("is_manual_input") or event.get("has_manual_input")]),
        "duplicates": len(duplicates),
        "verified_events": len([event for event in events if event.get("is_verified")]),
        "needs_follow_up": len([event for event in events if event.get("needs_follow_up")]),
        "source_failures": len(failures),
        "manual_files": manual_meta.get("files_read", []),
        "generated_at": local_now().isoformat(),
    }

    return {
        "date": run_date,
        "title": f"{run_date} 每日 AI 行业简讯",
        "page_url": public_page_url(run_date, settings),
        "language": "中文为主 / Original titles retained",
        "core_summary": core_items,
        "company_updates": company_updates,
        "deep_dives": deep_dives,
        "agent_tools": agent_tools,
        "model_api_changes": model_api_changes,
        "manual_review": manual_review,
        "cognition": cognition,
        "actions": actions,
        "events": sorted_events,
        "duplicates": duplicates,
        "failures": failures,
        "stats": stats,
    }


def event_sort_key(event: Dict[str, Any]) -> tuple:
    return (
        IMPORTANCE_RANK.get(event.get("importance", "Low"), 1),
        1 if event.get("credibility") == "official" else 0,
        event.get("published_at") or event.get("fetched_at") or "",
    )


def build_core_summary(events: List[Dict[str, Any]], settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    limit = int(settings.get("brief", {}).get("max_core_items", 5))
    selected = [event for event in events if event.get("importance") in ["High", "Medium"]][:limit]
    return [
        {
            "event_id": event["id"],
            "title": display_title(event),
            "company": event.get("company", ""),
            "product": event.get("product", ""),
            "summary": event.get("summary", ""),
            "why_it_matters": event.get("why_it_matters", ""),
            "source_url": event.get("source_url", ""),
            "source_name": event.get("source_name", ""),
            "importance": event.get("importance", "Low"),
            "credibility": event.get("credibility", "unverified"),
        }
        for event in selected
    ]


def build_company_updates(events: List[Dict[str, Any]]) -> Dict[str, List[Dict[str, Any]]]:
    grouped: Dict[str, List[Dict[str, Any]]] = {company: [] for company in COMPANY_ORDER}
    for event in events:
        company = event.get("company") or "Other"
        if company not in grouped:
            company = "Other"
        grouped[company].append(event)
    return {company: grouped[company] for company in COMPANY_ORDER if grouped[company]}


def build_deep_dives(events: List[Dict[str, Any]], settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    limit = int(settings.get("brief", {}).get("max_deep_dive_items", 3))
    candidates = [
        event
        for event in events
        if event.get("importance") == "High"
        or any(tag in event.get("tags", []) for tag in ["模型更新", "API 更新", "Agent", "开发者工具", "企业服务"])
    ]
    selected = candidates[:limit]
    return [
        {
            "event_id": event["id"],
            "title": display_title(event),
            "company": event.get("company", ""),
            "source_url": event.get("source_url", ""),
            "source_name": event.get("source_name", ""),
            "problem_solved": infer_problem_solved(event),
            "industry_signal": infer_industry_signal(event),
            "competition_impact": infer_competition_impact(event),
            "user_impact": infer_user_impact(event),
            "business_impact": infer_business_impact(event),
            "personal_takeaway": infer_personal_takeaway(event),
            "uncertainty": infer_uncertainty(event),
        }
        for event in selected
    ]


def build_agent_tools(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    selected = []
    for event in events:
        haystack = " ".join([event.get("title", ""), event.get("summary", ""), " ".join(event.get("tags", []))]).lower()
        if "Agent" in event.get("tags", []) or "开发者工具" in event.get("tags", []) or any(keyword in haystack for keyword in AGENT_KEYWORDS):
            selected.append(
                {
                    "event_id": event["id"],
                    "title": display_title(event),
                    "company": event.get("company", ""),
                    "source_url": event.get("source_url", ""),
                    "workflow_help": "可能帮助把模型能力接入编码、检索、企业知识库或自动化任务链路。",
                    "try_or_not": "值得试用" if event.get("importance") in ["High", "Medium"] and event.get("credibility") == "official" else "先收藏观察",
                    "scenarios": infer_agent_scenario(event),
                    "business_relevance": "与业务自动化、AI 工作台、云服务销售中的方案理解有关，适合沉淀为案例。",
                    "importance": event.get("importance", "Low"),
                    "credibility": event.get("credibility", "unverified"),
                }
            )
    return selected


def build_model_api_changes(events: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    rows = []
    for event in events:
        tags = event.get("tags", [])
        if not any(tag in tags for tag in ["模型更新", "API 更新", "价格变化", "多模态", "Agent"]):
            continue
        rows.append(
            {
                "company": event.get("company", ""),
                "model_product": event.get("product") or event.get("title", ""),
                "before": "信息不足",
                "after": event.get("summary", "信息不足"),
                "change_type": ", ".join(tags[:3]) or event.get("category", ""),
                "developer_impact": event.get("why_it_matters", ""),
                "business_impact": infer_business_impact(event),
                "source_url": event.get("source_url", ""),
            }
        )
    return rows


def build_manual_review(events: List[Dict[str, Any]], duplicates: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    duplicate_ids = {event.get("id"): event for event in duplicates}
    rows = []
    for event in events + duplicates:
        if not event.get("is_manual_input") and not event.get("has_manual_input"):
            continue
        duplicate_of = event.get("duplicate_of", "")
        status = "多源确认" if duplicate_of or event.get("multi_source") else ("已核实" if event.get("is_verified") else "待核实")
        rows.append(
            {
                "title": display_title(event),
                "company": event.get("company", ""),
                "source_url": event.get("source_url", ""),
                "credibility": event.get("credibility", "unverified"),
                "status": status,
                "duplicate_of": duplicate_of,
                "worth_deep_dive": event.get("importance") == "High",
                "summary": event.get("summary", ""),
            }
        )
    return rows


def build_cognition_items(events: List[Dict[str, Any]], settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    limit = int(settings.get("brief", {}).get("max_cognition_items", 5))
    items = []
    used = set()
    for event in events:
        tags = event.get("tags", [])
        if "Agent" in tags or "开发者工具" in tags:
            text = "Agent 工具的核心不是替代聊天，而是把 AI 从回答者变成执行者。"
            explanation = "今天的开发者工具更新需要放到真实任务链路中评估，而不是只看演示效果。"
        elif "API 更新" in tags:
            text = "API 能力变化会改变应用层产品的功能边界。"
            explanation = "接口、上下文、工具调用和价格变化，都会影响一个功能是否值得产品化。"
        elif "模型更新" in tags:
            text = "模型竞争正在从单点能力转向模型、工具链和分发渠道的组合竞争。"
            explanation = "只看 benchmark 容易低估产品入口和开发者生态的价值。"
        elif "企业服务" in tags:
            text = "云厂商的 AI 更新，本质上是在把模型能力变成企业可采购的解决方案。"
            explanation = "这对云服务销售、企业集成和行业方案理解尤其重要。"
        else:
            text = "每日追踪的价值在于把零散更新沉淀成可复用的判断框架。"
            explanation = "单条信息可能很小，但连续观察能帮助识别平台战略和商业化节奏。"
        if text in used:
            continue
        used.add(text)
        items.append(
            {
                "insight": text,
                "explanation": explanation,
                "source_title": display_title(event),
                "source_url": event.get("source_url", ""),
            }
        )
        if len(items) >= limit:
            break
    return items


def build_action_items(events: List[Dict[str, Any]], settings: Dict[str, Any]) -> List[Dict[str, Any]]:
    limit = int(settings.get("brief", {}).get("max_action_items", 5))
    actions = []
    for event in events:
        actions.append(
            {
                "title": display_title(event),
                "action": event.get("action_suggestion", ""),
                "source_url": event.get("source_url", ""),
                "reason": event.get("why_it_matters", ""),
            }
        )
        if len(actions) >= limit:
            break
    return actions


def display_title(event: Dict[str, Any]) -> str:
    return event.get("title_zh") or event.get("title") or "Untitled"


def infer_problem_solved(event: Dict[str, Any]) -> str:
    tags = event.get("tags", [])
    if "API 更新" in tags:
        return "主要解决开发者接入、能力调用或平台集成中的具体问题。"
    if "Agent" in tags:
        return "主要解决从模型回答到任务执行之间的工作流连接问题。"
    if "模型更新" in tags:
        return "主要围绕模型能力、可用范围或产品化入口做增强。"
    return "目前只能确认这是一个值得跟踪的官方或生态更新，具体问题需要继续看原文细节。"


def infer_industry_signal(event: Dict[str, Any]) -> str:
    tags = event.get("tags", [])
    if "Agent" in tags:
        return "行业信号是平台竞争正在向工具调用、上下文管理和任务执行链路延伸。"
    if "企业服务" in tags:
        return "行业信号是模型能力继续被包装成云服务、企业 API 和可采购方案。"
    if "开源模型" in tags:
        return "行业信号是开源模型仍在为私有化、成本控制和生态扩散提供替代路径。"
    return "行业信号仍需结合后续官方细节、开发者反馈和竞品动作确认。"


def infer_competition_impact(event: Dict[str, Any]) -> str:
    company = event.get("company", "")
    return f"对竞争格局的影响取决于 {company} 是否能把这次更新转化为稳定产品入口、API 使用量或开发者生态优势。"


def infer_user_impact(event: Dict[str, Any]) -> str:
    tags = event.get("tags", [])
    if "开发者工具" in tags or "API 更新" in tags:
        return "开发者需要关注接口变化、迁移成本和能否减少手工集成；企业客户更关心稳定性、权限和合规；普通用户影响可能间接体现为产品体验提升。"
    return "开发者、企业客户和普通用户的实际收益仍需看可用入口、价格和限制条件。"


def infer_agent_scenario(event: Dict[str, Any]) -> str:
    text = " ".join([event.get("title", ""), event.get("summary", ""), event.get("product", "")]).lower()
    if "code" in text or "codex" in text or "copilot" in text or "cli" in text:
        return "适合代码理解、脚手架生成、仓库内修改、命令行自动化和开发流程提效。"
    if "mcp" in text or "database" in text or "file" in text:
        return "适合把本地文件、数据库、知识库或第三方工具接入 Agent。"
    if "rag" in text or "search" in text or "perplexity" in text:
        return "适合检索增强、信息核查、研究型工作流和知识库问答。"
    return "适合先作为 Agent 工作流候选工具观察，重点看权限、上下文、执行稳定性和集成成本。"


def infer_business_impact(event: Dict[str, Any]) -> str:
    tags = event.get("tags", [])
    if "企业服务" in tags or "API 更新" in tags:
        return "可能影响企业采购、云平台绑定和业务自动化方案设计。"
    if "Agent" in tags:
        return "可能推动从单点工具采购走向端到端工作流方案。"
    return "商业化影响暂时需要更多使用数据和客户场景验证。"


def infer_personal_takeaway(event: Dict[str, Any]) -> str:
    tags = event.get("tags", [])
    if "Agent" in tags or "开发者工具" in tags:
        return "建议记录它如何连接文件、代码、数据库、浏览器或企业系统，这是理解 Agent 工作流的关键。"
    if "企业服务" in tags:
        return "建议从云服务销售视角记录它面向什么客户问题、如何定价、如何集成。"
    return "建议保留官方链接，后续和同类公司更新放在一起比较。"


def infer_uncertainty(event: Dict[str, Any]) -> str:
    if event.get("credibility") != "official":
        return "这条信息不是官方确认，仍需后续核实。"
    if event.get("category") in ["模型更新", "API 更新"] and "信息不足" in event.get("summary", ""):
        return "具体更新前后差异仍需继续查证，不能补写参数、价格或 benchmark。"
    return "当前判断基于已抓取来源，具体影响仍需结合原文细节和后续反馈。"
