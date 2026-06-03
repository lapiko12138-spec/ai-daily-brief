from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import time
import urllib.request
from typing import Any, Dict


def send_feishu_message(brief: Dict[str, Any]) -> Dict[str, Any]:
    webhook = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook:
        return {"skipped": True, "reason": "FEISHU_WEBHOOK_URL is not set"}

    payload = build_payload(brief)
    secret = os.getenv("FEISHU_SECRET", "").strip()
    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = sign_feishu(timestamp, secret)

    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8", errors="replace")
        return {"skipped": False, "status": response.status, "body": body}


def send_failure_message(run_date: str, error_text: str) -> Dict[str, Any]:
    webhook = os.getenv("FEISHU_WEBHOOK_URL", "").strip()
    if not webhook:
        return {"skipped": True, "reason": "FEISHU_WEBHOOK_URL is not set"}
    payload = {
        "msg_type": "text",
        "content": {
            "text": "\n".join(
                [
                    "每日 AI 行业简讯生成失败",
                    f"日期：{run_date}",
                    f"失败原因：{error_text}",
                    "请查看 GitHub Actions 日志或本地运行输出。",
                ]
            )
        },
    }
    secret = os.getenv("FEISHU_SECRET", "").strip()
    if secret:
        timestamp = str(int(time.time()))
        payload["timestamp"] = timestamp
        payload["sign"] = sign_feishu(timestamp, secret)
    data = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    request = urllib.request.Request(
        webhook,
        data=data,
        headers={"Content-Type": "application/json; charset=utf-8"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=20) as response:
        body = response.read().decode("utf-8", errors="replace")
        return {"skipped": False, "status": response.status, "body": body}


def build_payload(brief: Dict[str, Any]) -> Dict[str, Any]:
    text = build_text(brief)
    return {
        "msg_type": "text",
        "content": {"text": text},
    }


def build_text(brief: Dict[str, Any]) -> str:
    stats = brief.get("stats", {})
    lines = [
        f"{brief.get('title', '每日 AI 行业简讯')}",
        f"日期：{brief.get('date', '')}",
        "",
        "今日核心摘要：",
    ]
    core = brief.get("core_summary", [])[:5]
    if core:
        for index, item in enumerate(core, start=1):
            lines.append(f"{index}. [{item.get('importance', 'Low')}] {item.get('title', '')}")
            if item.get("why_it_matters"):
                lines.append(f"   重要性：{item['why_it_matters']}")
    else:
        lines.append("暂无已确认核心事件。")

    deep_titles = [item.get("title", "") for item in brief.get("deep_dives", [])[:3]]
    if deep_titles:
        lines.extend(["", "今日重点深挖："])
        for title in deep_titles:
            lines.append(f"- {title}")

    lines.extend(
        [
            "",
            f"页面链接：{brief.get('page_url', '')}",
            f"信息事件数：{stats.get('total_events', 0)}",
            f"待核实信息数：{stats.get('needs_follow_up', 0)}",
            f"抓取失败来源数：{stats.get('source_failures', 0)}",
        ]
    )
    if brief.get("failures"):
        lines.append("部分来源抓取失败，详情见页面底部。")
    return "\n".join(lines)


def sign_feishu(timestamp: str, secret: str) -> str:
    string_to_sign = f"{timestamp}\n{secret}"
    digest = hmac.new(string_to_sign.encode("utf-8"), b"", digestmod=hashlib.sha256).digest()
    return base64.b64encode(digest).decode("utf-8")
