"""Text-only result cleanup used by the optional analysis enhancer."""

from __future__ import annotations

import re

_RELATED = re.compile(
    r"\n*#{1,3}\s*(?:联想追问|推荐问题|后续问题|相关问题|相关推荐|还可以继续)[：:]?[\s\S]*$",
    re.IGNORECASE,
)


def strip_related_suggestions(markdown: str) -> str:
    text = (markdown or "").strip()
    if not text:
        return text
    cleaned = _RELATED.sub("", text).rstrip()
    cleaned = re.sub(
        r"\n*(?:如果需要进一步分析|建议继续查看|你可以继续问)[^\n]*(?:\n[-*•].*)*\s*$",
        "",
        cleaned,
        flags=re.IGNORECASE,
    ).rstrip()
    return cleaned or text
