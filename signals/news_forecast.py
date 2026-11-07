"""News and demand-signal adapter with an NVIDIA Nemotron-compatible endpoint.

The adapter is intentionally provider-agnostic: Nemotron can be hosted through
NIM, an OpenAI-compatible gateway, or a local endpoint. If no endpoint is set,
the raw headlines are returned so the optimizer remains usable offline.
"""

from __future__ import annotations

import json
import os
import urllib.parse
import urllib.request
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True)
class NewsSignal:
    title: str
    summary: str
    source: str
    url: str
    demand_impact: float = 0.0
    confidence: float = 0.0


def fetch_rss(query: str, limit: int = 8) -> list[dict[str, str]]:
    """Fetch public Google News RSS headlines for a local demand query."""

    url = "https://news.google.com/rss/search?" + urllib.parse.urlencode({"q": query})
    request = urllib.request.Request(url, headers={"User-Agent": "ShiftOS/0.1"})
    with urllib.request.urlopen(request, timeout=8) as response:
        root = ET.fromstring(response.read())
    items: list[dict[str, str]] = []
    for item in root.findall("./channel/item")[:limit]:
        items.append({
            "title": item.findtext("title", default=""),
            "summary": item.findtext("description", default=""),
            "url": item.findtext("link", default=""),
            "source": "Google News RSS",
        })
    return items


def score_with_nemotron(headlines: list[dict[str, str]], endpoint: str | None = None, api_key: str | None = None) -> list[NewsSignal]:
    """Ask a Nemotron-compatible chat endpoint to score demand pressure.

    The expected response is JSON: {"signals": [{"index": 0,
    "demand_impact": 0.0, "confidence": 0.0}]}. Scores range from -1 to 1.
    """

    endpoint = endpoint or os.getenv("NEMOTRON_ENDPOINT")
    api_key = api_key or os.getenv("NEMOTRON_API_KEY")
    if not endpoint or not headlines:
        return [NewsSignal(**item) for item in headlines]
    prompt = {
        "role": "user",
        "content": "Score each headline's likely near-term local electricity demand impact from -1 to 1. Return JSON only with a signals array containing index, demand_impact, confidence.\n" + json.dumps(headlines),
    }
    payload = json.dumps({"model": os.getenv("NEMOTRON_MODEL", "nvidia/nemotron"), "messages": [prompt], "temperature": 0}).encode()
    headers = {"Content-Type": "application/json"}
    if api_key:
        headers["Authorization"] = f"Bearer {api_key}"
    request = urllib.request.Request(endpoint, data=payload, headers=headers, method="POST")
    with urllib.request.urlopen(request, timeout=20) as response:
        body = json.loads(response.read())
    content = body.get("choices", [{}])[0].get("message", {}).get("content", "{}")
    parsed = json.loads(content)
    scores = {int(row["index"]): row for row in parsed.get("signals", [])}
    return [NewsSignal(**item, demand_impact=float(scores.get(i, {}).get("demand_impact", 0.0)), confidence=float(scores.get(i, {}).get("confidence", 0.0))) for i, item in enumerate(headlines)]
