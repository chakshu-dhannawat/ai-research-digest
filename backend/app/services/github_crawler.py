import base64
import logging
import time
from concurrent.futures import ThreadPoolExecutor, as_completed
from datetime import timedelta

import httpx

from app.config import settings
from app.utils import now_jst

logger = logging.getLogger(__name__)

AI_SEARCH_QUERIES = [
    "LLM OR large-language-model OR GPT",
    "AI agent OR agentic OR multi-agent",
    "RAG OR retrieval-augmented OR vector-database",
    "fine-tuning OR RLHF OR DPO OR alignment",
    "diffusion OR multimodal OR vision-language",
]

_GITHUB_API_BASE = "https://api.github.com"


def _github_headers() -> dict[str, str]:
    headers = {
        "Accept": "application/vnd.github+json",
        "X-GitHub-Api-Version": "2022-11-28",
    }
    if settings.github_token:
        headers["Authorization"] = f"token {settings.github_token}"
    return headers


def _rate_limit_wait(resp: httpx.Response) -> float:
    """Return seconds to sleep based on GitHub rate-limit headers."""
    remaining = resp.headers.get("x-ratelimit-remaining")
    reset_at = resp.headers.get("x-ratelimit-reset")
    if remaining is not None and int(remaining) <= 1 and reset_at:
        return max(0, int(reset_at) - int(time.time()) + 2)
    return 0


def _search_repos(client: httpx.Client, query: str, per_page: int, max_retries: int = 3) -> list[dict]:
    """Call GitHub search/repositories directly; retry on rate-limit or transient errors."""
    url = f"{_GITHUB_API_BASE}/search/repositories"
    params = {"q": query, "sort": "stars", "order": "desc", "per_page": per_page}

    for attempt in range(1, max_retries + 1):
        try:
            resp = client.get(url, params=params, headers=_github_headers(), timeout=30)
            if resp.status_code == 200:
                return resp.json().get("items", [])
            if resp.status_code in (403, 429):
                sleep = _rate_limit_wait(resp)
                if sleep:
                    logger.warning("GitHub rate-limit for '%s...'; sleeping %.1fs", query[:40], sleep)
                    time.sleep(sleep)
                    continue
                logger.warning("GitHub 403 for '%s...': %s", query[:40], resp.text[:200])
            elif resp.status_code >= 500:
                logger.warning("GitHub %s for '%s...'", resp.status_code, query[:40])
            else:
                logger.warning("GitHub search failed (%s): %s", resp.status_code, resp.text[:200])
                break
        except Exception as e:
            logger.warning("GitHub search exception for '%s...' (attempt %d/%d): %s", query[:40], attempt, max_retries, e)
        if attempt < max_retries:
            time.sleep(2 ** attempt)
    return []


def _fetch_readme(client: httpx.Client, full_name: str) -> str:
    """Fetch and decode the README for a repo; return empty string on failure."""
    try:
        resp = client.get(
            f"{_GITHUB_API_BASE}/repos/{full_name}/readme",
            headers={**_github_headers(), "Accept": "application/vnd.github.raw+json"},
            timeout=20,
        )
        if resp.status_code == 200:
            # raw+json returns the raw content, otherwise base64-encoded JSON
            content_type = resp.headers.get("content-type", "")
            if "application/json" in content_type:
                data = resp.json()
                raw = data.get("content", "")
                return base64.b64decode(raw).decode("utf-8", errors="ignore")[:3000]
            return resp.text[:3000]
    except Exception as e:
        logger.debug("README fetch failed for %s: %s", full_name, e)
    return ""


def _enrich_repo(client: httpx.Client, repo: dict) -> dict | None:
    """Convert a GitHub API repo object into the internal item format."""
    try:
        full_name = repo.get("full_name")
        if not full_name:
            return None
        created_at = repo.get("created_at")
        readme_text = _fetch_readme(client, full_name)
        return {
            "source": "github",
            "name": repo.get("name", ""),
            "full_name": full_name,
            "url": repo.get("html_url", ""),
            "description": repo.get("description") or "",
            "stars": repo.get("stargazers_count"),
            "forks": repo.get("forks_count"),
            "language": repo.get("language"),
            "topics": repo.get("topics", []),
            "created_at": created_at,
            "published_at": created_at,
            "readme_snippet": readme_text,
        }
    except Exception as e:
        logger.warning("Failed to enrich %s: %s", repo.get("full_name"), e)
        return None


def fetch_trending_repos(max_per_query: int = 5) -> list[dict]:
    """Find trending AI repos created in the last week using the GitHub REST API.

    Uses direct HTTPS calls instead of PyGithub for transparent rate-limit
    handling, retry logic, and to avoid PaginatedList slicing bugs that have
    caused production runs to return 0 repos.
    """
    week_ago = (now_jst() - timedelta(days=7)).strftime("%Y-%m-%d")

    seen: set[str] = set()
    all_repos: list[dict] = []

    with httpx.Client(proxy=settings.http_proxy, timeout=httpx.Timeout(30.0, connect=10.0), follow_redirects=True) as client:
        for query_text in AI_SEARCH_QUERIES:
            q = f"created:>{week_ago} stars:>5 {query_text}"
            logger.info("GitHub search: %s", q)
            repos = _search_repos(client, q, per_page=max_per_query)
            for repo in repos:
                full_name = repo.get("full_name")
                if not full_name or full_name in seen:
                    continue
                seen.add(full_name)
                all_repos.append(repo)

        logger.info("Found %d unique repos across all queries", len(all_repos))

        enriched: list[dict] = []
        with ThreadPoolExecutor(max_workers=6) as executor:
            futures = {executor.submit(_enrich_repo, client, r): r for r in all_repos}
            for future in as_completed(futures):
                try:
                    data = future.result()
                    if data:
                        enriched.append(data)
                except Exception as e:
                    logger.warning("Error enriching repo: %s", e)

    return enriched
