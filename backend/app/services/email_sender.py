import html
import logging
import re
import smtplib
import time
import uuid
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from email.utils import formatdate
from pathlib import Path

import httpx
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
        "tagline": "Curated for AI Engineers & Researchers",
        "explore": "🔎 Browse all articles & subscribe",
    },
    "ja": {
        "apply": "💡 活用方法",
        "tagline": "AIエンジニア・研究者向けダイジェスト",
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


def _html_to_text(html_body: str) -> str:
    """Quick plain-text fallback for multipart/alternative emails."""
    text = re.sub(r"<br\s*/?>", "\n", html_body, flags=re.IGNORECASE)
    text = re.sub(r"</p>", "\n\n", text, flags=re.IGNORECASE)
    text = re.sub(r"<li>", "\n- ", text, flags=re.IGNORECASE)
    text = re.sub(r"<[^>]+>", "", text)
    text = html.unescape(text)
    # Collapse excessive whitespace
    text = re.sub(r"\n{3,}", "\n\n", text)
    return text.strip()


def _message_id_domain() -> str:
    """Derive a stable domain for Message-Id from the sender address."""
    return settings.sender_email.split("@")[-1] or "otsuka-shokai.co.jp"


def send_email(html_body: str, recipients: list[str], subject: str | None = None) -> None:
    subject = subject or f"🤖 AI Engineer Daily Digest — {now_jst().strftime('%Y-%m-%d')}"

    if settings.resend_api_key:
        _send_resend(
            settings.sender_email,
            recipients,
            subject,
            html_body=html_body,
            text_body=_html_to_text(html_body),
        )
        logger.info("Email sent to %d recipient(s) via Resend", len(recipients))
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.sender_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-Id"] = f"<{uuid.uuid4().hex}@{_message_id_domain()}>"
    # For small recipient lists (test sends) put the address in the visible To:
    # header so corporate relays do not treat the message as suspicious.
    # For larger lists, keep BCC privacy by putting the sender in To: and
    # delivering to recipients only via the SMTP envelope.
    if len(recipients) <= 3:
        msg["To"] = ", ".join(recipients)
    else:
        msg["To"] = settings.sender_email
    msg.attach(MIMEText(_html_to_text(html_body), "plain", "utf-8"))
    msg.attach(MIMEText(html_body, "html", "utf-8"))
    _send_smtp(settings.sender_email, recipients, msg)
    logger.info("Email sent to %d recipient(s) via %s:%s", len(recipients), settings.smtp_host, settings.smtp_port)


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


def _send_resend(
    sender: str,
    recipients: list[str],
    subject: str,
    html_body: str,
    text_body: str,
) -> None:
    """Send via the Resend transactional email API.

    Resend is the recommended option for new users: sign up, copy the API key,
    and you can send from onboarding@resend.dev without verifying a domain.
    """
    payload = {
        "from": sender,
        "to": recipients,
        "subject": subject,
        "html": html_body,
        "text": text_body,
    }
    headers = {
        "Authorization": f"Bearer {settings.resend_api_key}",
        "Content-Type": "application/json",
    }
    proxies = None
    if settings.http_proxy:
        proxies = {"http://": settings.http_proxy, "https://": settings.http_proxy}

    for attempt in range(1, 4):
        try:
            with httpx.Client(timeout=30, proxies=proxies) as client:
                r = client.post("https://api.resend.com/emails", json=payload, headers=headers)
                r.raise_for_status()
            return
        except Exception as e:
            if attempt == 3:
                logger.error("Resend send failed after 3 attempts: %s", e)
                raise
            delay = 10 * attempt
            logger.warning("Resend send attempt %d/3 failed (%s); retrying in %ds", attempt, e, delay)
            time.sleep(delay)


def send_alert_email(subject: str, body_text: str) -> None:
    """Notify the configured developer address when the newsletter fails to send."""
    if settings.resend_api_key:
        _send_resend(
            settings.sender_email,
            [settings.alert_email],
            subject,
            html_body=f"<pre>{html.escape(body_text)}</pre>",
            text_body=body_text,
        )
        logger.info("Alert email sent to %s via Resend", settings.alert_email)
        return

    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"] = settings.sender_email
    msg["To"] = settings.alert_email
    msg["Date"] = formatdate(localtime=True)
    msg["Message-Id"] = f"<{uuid.uuid4().hex}@{_message_id_domain()}>"
    msg.attach(MIMEText(body_text, "plain", "utf-8"))

    _send_smtp(settings.sender_email, [settings.alert_email], msg)
    logger.info("Alert email sent to %s", settings.alert_email)
