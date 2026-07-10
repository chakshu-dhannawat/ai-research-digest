from pydantic import BaseModel
from datetime import datetime


class NewsletterItem(BaseModel):
    source: str
    title: str
    url: str | None = None
    summary: str
    stars: int | None = None
    language: str | None = None
    topics: list[str] = []
    relevance_score: float | None = None


class NewsletterOut(BaseModel):
    id: int
    sent_at: datetime
    subject: str
    recipient_emails: list[str]
    item_count: int
    status: str
    error_message: str | None = None
    is_test: bool = False


class NewsletterItemOut(BaseModel):
    id: int
    source: str
    title: str
    url: str | None
    summary: str
    stars: int | None
    language: str | None
    topics: list[str]
    relevance_score: float | None


class PipelineRunOut(BaseModel):
    id: int
    started_at: datetime
    finished_at: datetime | None
    status: str
    github_items_found: int
    news_items_found: int
    items_after_dedup: int
    error_message: str | None = None
    is_test: bool = False


class InstantSendRequest(BaseModel):
    recipients: list[str]


class PipelineStatus(BaseModel):
    run_id: int
    status: str


class SubscribeRequest(BaseModel):
    email: str
    language: str = "en"


class SubscriberOut(BaseModel):
    id: int
    email: str
    subscribed_at: datetime
    active: bool
    language: str = "en"


class LanguageUpdate(BaseModel):
    email: str
    language: str


class FetchedItemOut(BaseModel):
    id: int
    source: str
    title: str
    url: str | None = None
    description: str | None = None
    summary: str | None = None
    application: str | None = None
    relevance_score: float | None = None
    stars: int | None = None
    language: str | None = None
    topics: list[str] = []
    keywords: list[str] = []
    published_at: datetime | None = None
    last_seen: datetime | None = None


class HotTopicOut(BaseModel):
    keyword: str
    count: int
