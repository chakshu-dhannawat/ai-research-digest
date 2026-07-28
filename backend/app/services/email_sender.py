import logging
import smtplib
import time
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from pathlib import Path

from jinja2 import Template

from app.config import settings
from app.utils import now_jst

logger = logging.getLogger(__name__)

_TEMPLATE_PATH = Path(__file__).parent.parent / "templates" / "newsletter.html"


# Section titles per language, keyed by source_key. English is the default.
_SECTION_TITLES = {
    "en": {
        "model_release": "\U0001f680 Recent Model Releases",
        "labs": "\U0001f52c AI Labs & Technical Reports",
        "voices": "\U0001f5e3️ Voices",
        "github": "\U0001f525 Trending GitHub Repos",
        "elastic": "\U0001f4e1 Elastic Blog",
        "news": "\U0001f4f0 AI News & Blogs",
        "hf_papers": "\U0001f917 HuggingFace Trending Papers",
        "arxiv": "\U0001f4c4 arXiv Papers",
    },
    "ja": {
        "model_release": "\U0001f680 最新モデルリリース",
        "labs": "\U0001f52c AIラボ・技術レポート",
        "voices": "\U0001f5e3️ 専門家の声",
        "github": "\U0001f525 GitHubトレンド",
        "elastic": "\U0001f4e1 Elasticブログ",
        "news": "\U0001f4f0 AIニュース・ブログ",
        "hf_papers": "\U0001f917 HuggingFace 注目論文",
        "arxiv": "\U0001f4c4 arXiv論文",
    },
}

# UI labels per language. English is the default.
_LABELS = {
    "en": {
        "apply": "💡 How to apply",
        "tagline": "Curated for AI Engineers @ Otsuka",
        "explore": "🔎 Browse all articles & subscribe",
    },
    "ja": {
        "apply": "💡 活用方法",
        "tagline": "大塚商会 AIエンジニア向けダイジェスト",
        "explore": "🔎 すべての記事を見る・購読設定",
    },
}


def render_newsletter(items: list[dict], date_str: str | None = None, lang: str = "en") -> str:
    date_str = date_str or now_jst().strftime("%B %d, %Y")
    template = Template(_TEMPLATE_PATH.read_text())

    model_items = [i for i in items if i.get("source") == "model_release"]
    labs_items = [i for i in items if i.get("source") == "labs"]
    voices_items = [i for i in items if i.get("source") == "voices"]
    github_items = [i for i in items if i.get("source") == "github"]
    elastic_items = [i for i in items if i.get("source") == "newsletter" and any("elastic" in t.lower() for t in i.get("topics", []))]
    other_newsletter = [i for i in items if i.get("source") == "newsletter" and i not in elastic_items]
    hf_paper_items = [i for i in items if i.get("source") == "hf_papers"]
    web_items = [i for i in items if i.get("source") == "web_search"]
    news_items = other_newsletter + web_items

    titles = _SECTION_TITLES.get(lang, _SECTION_TITLES["en"])
    labels = _LABELS.get(lang, _LABELS["en"])

    sections = [
        (titles["model_release"], "model_release", model_items),
        (titles["labs"], "labs", labs_items),
        (titles["voices"], "voices", voices_items),
        (titles["github"], "github", github_items),
        (titles["elastic"], "elastic", elastic_items),
        (titles["news"], "news", news_items),
        (titles["hf_papers"], "hf_papers", hf_paper_items),
    ]

    return template.render(date=date_str, items=items, sections=sections, lang=lang, labels=labels, site_url=settings.site_url)


def send_email(html_body: str, recipients: list[str], subject: str | None = None) -> None:
    subject = subject or f"🤖 AI Engineer Daily Digest — {now_jst().strftime('%Y-%m-%d')}"

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.sender_email
    # BCC delivery: recipients are passed via the SMTP envelope only and kept out
    # of the headers, so no recipient sees the others' addresses.
    msg["To"] = settings.sender_email
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    _send_smtp(settings.sender_email, recipients, msg)


def _send_smtp(sender: str, recipients: list[str], msg: MIMEMultipart) -> None:
    """Shared SMTP transport with retry."""
    for attempt in range(1, 4):
        try:
            with smtplib.SMTP(settings.smtp_host, settings.smtp_port, timeout=30) as server:
                server.ehlo()
                server.sendmail(sender, recipients, msg.as_string())
            return
        except (OSError, smtplib.SMTPException) as e:
            if attempt == 3:
                logger.error("SMTP send failed after 3 attempts: %s", e)
                raise
            delay = 10 * attempt  # 10s, 20s
            logger.warning("SMTP send attempt %d/3 failed (%s); retrying in %ds", attempt, e, delay)
            time.sleep(delay)


def send_alert_email(subject: str, body_text: str) -> None:
    """Notify the configured developer address when the newsletter fails to send."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.sender_email
    msg["To"] = settings.alert_email
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    _send_smtp(settings.sender_email, [settings.alert_email], msg)
    logger.info("Alert email sent to %s", settings.alert_email)
