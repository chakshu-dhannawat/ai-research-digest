import logging

import httpx

from app.config import settings
from app.utils import now_jst

logger = logging.getLogger(__name__)

_SECTION_TITLES = {
    "model_release": "🚀 Recent Model Releases",
    "labs": "🔬 AI Labs & Technical Reports",
    "voices": "🗣️ Voices",
    "github": "🔥 Trending GitHub Repos",
    "elastic": "📡 Elastic Blog",
    "news": "📰 AI News & Blogs",
    "hf_papers": "🤗 HuggingFace Trending Papers",
    "arxiv": "📄 arXiv Papers",
}


def _group_items(items: list[dict]) -> list[tuple[str, list[dict]]]:
    model_items = [i for i in items if i.get("source") == "model_release"]
    labs_items = [i for i in items if i.get("source") == "labs"]
    voices_items = [i for i in items if i.get("source") == "voices"]
    github_items = [i for i in items if i.get("source") == "github"]
    elastic_items = [
        i for i in items
        if i.get("source") == "newsletter" and any("elastic" in t.lower() for t in i.get("topics", []))
    ]
    other_newsletter = [i for i in items if i.get("source") == "newsletter" and i not in elastic_items]
    hf_paper_items = [i for i in items if i.get("source") == "hf_papers"]
    web_items = [i for i in items if i.get("source") == "web_search"]
    news_items = other_newsletter + web_items

    return [
        (_SECTION_TITLES["model_release"], model_items),
        (_SECTION_TITLES["labs"], labs_items),
        (_SECTION_TITLES["voices"], voices_items),
        (_SECTION_TITLES["github"], github_items),
        (_SECTION_TITLES["elastic"], elastic_items),
        (_SECTION_TITLES["news"], news_items),
        (_SECTION_TITLES["hf_papers"], hf_paper_items),
    ]


def _truncate(text: str | None, max_len: int = 180) -> str:
    text = (text or "").strip().replace("\n", " ")
    if len(text) <= max_len:
        return text
    return text[: max_len - 3].rstrip() + "..."


def _title_text(item: dict) -> str:
    title = item.get("title") or item.get("name", "Untitled")
    url = item.get("url", "")
    if url:
        return f"[{title}]({url})"
    return title


def build_teams_card(items: list[dict]) -> dict:
    """Build a Microsoft Teams Adaptive Card payload for the daily digest."""
    date_str = now_jst().strftime("%Y-%m-%d")
    body: list[dict] = [
        {"type": "TextBlock", "size": "Medium", "weight": "Bolder", "text": f"🤖 AI Engineer Daily Digest — {date_str}"},
        {"type": "TextBlock", "text": f"{len(items)} curated items · English digest", "wrap": True, "isSubtle": True},
    ]

    grouped = _group_items(items)
    visible_groups = [(t, s) for t, s in grouped if s]
    for idx, (section_title, section_items) in enumerate(visible_groups):
        body.append({
            "type": "TextBlock",
            "text": section_title,
            "weight": "Bolder",
            "spacing": "Medium" if idx == 0 else "Large",
            "separator": idx > 0,
        })
        for item in section_items:
            summary = _truncate(item.get("summary"), 180)
            score = item.get("relevance_score")
            score_text = f" · score: {score:.1f}" if score is not None else ""

            body.append({
                "type": "TextBlock",
                "text": _title_text(item),
                "wrap": True,
            })
            if summary:
                body.append({
                    "type": "TextBlock",
                    "text": f"{summary}{score_text}",
                    "wrap": True,
                    "isSubtle": True,
                    "spacing": "None",
                })

    body.append({
        "type": "ActionSet",
        "spacing": "Large",
        "actions": [
            {
                "type": "Action.OpenUrl",
                "title": "Browse all articles",
                "url": settings.site_url,
            }
        ],
    })

    return {
        "type": "message",
        "attachments": [
            {
                "contentType": "application/vnd.microsoft.card.adaptive",
                "contentUrl": None,
                "content": {
                    "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                    "type": "AdaptiveCard",
                    "version": "1.2",
                    "body": body,
                    "msTeams": {"width": "Full"},
                },
            }
        ],
    }


async def send_teams_digest(items: list[dict]) -> bool:
    """Post the digest to the configured Microsoft Teams channel webhook.

    Teams delivery is best-effort: errors are logged but never raised.
    Returns True if posted (or skipped because no webhook is configured),
    False if the post failed.
    """
    if not settings.teams_webhook_url:
        logger.info("TEAMS_WEBHOOK_URL not configured; skipping Teams post")
        return True

    card = build_teams_card(items)
    try:
        async with httpx.AsyncClient(proxy=settings.http_proxy, timeout=30, follow_redirects=True) as client:
            resp = await client.post(settings.teams_webhook_url, json=card)
            resp.raise_for_status()
        logger.info("Teams digest posted (%d items)", len(items))
        return True
    except Exception as e:
        logger.exception("Teams digest failed: %s", e)
        return False
