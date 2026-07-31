import base64
import logging
from datetime import timedelta

from app.utils import now_jst
from concurrent.futures import ThreadPoolExecutor, as_completed

from github import Github

from app.config import settings

logger = logging.getLogger(__name__)

AI_SEARCH_QUERIES = [
    "LLM OR large-language-model OR GPT",
    "AI agent OR agentic OR multi-agent",
    "RAG OR retrieval-augmented OR vector-database",
    "fine-tuning OR RLHF OR DPO OR alignment",
    "diffusion OR multimodal OR vision-language",
]


def fetch_trending_repos(max_per_query: int = 5) -> list[dict]:
    g = Github(settings.github_token)
    yesterday = (now_jst() - timedelta(days=1)).strftime("%Y-%m-%d")
    week_ago = (now_jst() - timedelta(days=7)).strftime("%Y-%m-%d")
    month_ago = (now_jst() - timedelta(days=30)).strftime("%Y-%m-%d")
    seen = set()
    all_repos = []

    for query_text in AI_SEARCH_QUERIES:
        # Brand new repos (created in last week) gaining early traction
        q_new = f"created:>{week_ago} stars:>5 {query_text}"
        # New-ish repos (created in last month) with rapid star growth, excluding mega-repos
        q_growing = f"pushed:>{yesterday} created:>{month_ago} stars:10..5000 {query_text}"

        for q in [q_new, q_growing]:
            logger.info("GitHub search: %s", q)
            try:
                results = g.search_repositories(query=q, sort="stars", order="desc")
                if results.totalCount == 0:
                    continue
                for repo in list(results[:max_per_query]):
                    if repo.full_name in seen:
                        continue
                    seen.add(repo.full_name)
                    all_repos.append(repo)
            except Exception as e:
                logger.warning("Search failed for '%s': %s", q, e)

    logger.info("Found %d unique repos across all queries", len(all_repos))

    enriched = []
    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(_enrich_repo, r): r for r in all_repos}
        for future in as_completed(futures):
            try:
                data = future.result()
                if data:
                    enriched.append(data)
            except Exception as e:
                logger.warning("Error enriching repo: %s", e)

    return enriched


def _enrich_repo(repo) -> dict | None:
    try:
        readme_text = ""
        try:
            raw = repo.get_readme().content
            readme_text = base64.b64decode(raw).decode("utf-8")[:3000]
        except Exception:
            pass

        created_at = repo.created_at.isoformat() if repo.created_at else None
        return {
            "source": "github",
            "name": repo.name,
            "full_name": repo.full_name,
            "url": repo.html_url,
            "description": repo.description or "",
            "stars": repo.stargazers_count,
            "forks": repo.forks_count,
            "language": repo.language,
            "topics": repo.get_topics(),
            "created_at": created_at,
            "published_at": created_at,
            "readme_snippet": readme_text,
        }
    except Exception as e:
        logger.warning("Failed to enrich %s: %s", repo.full_name, e)
        return None
