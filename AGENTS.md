# AGENTS.md — ai-research-digest (GitHub public mirror)

## Git identity

This is the personal GitHub mirror. Commit as **chakshu-dhannawat**:

- Name: `chakshu-dhannawat`
- Email: `chakshu.dhannawat1@gmail.com`

```bash
git config user.name "chakshu-dhannawat"
git config user.email "chakshu.dhannawat1@gmail.com"
```

## Secrets

`backend/.env` holds real credentials and is git-ignored. Never commit it.
Keep `backend/.env.example` in sync with generic placeholder values only.

## Permanent workflow: GitLab (Otsuka-internal) first, then GitHub (public)

This repository is the **public, general-audience mirror**. The canonical
Otsuka-internal deployment lives in `/home/mac/chakshu/ai-newsletter` and
pushes to GitLab.

### Folder locations

| Repo | Path | Remote | Branch | Audience |
|------|------|--------|--------|----------|
| Otsuka-internal | `/home/mac/chakshu/ai-newsletter` | GitLab (`origin`) | `master` | Otsuka AI team |
| Public mirror | `/home/mac/chakshu/ai-research-digest-github` | GitHub (`origin`) | `main` | General AI engineers / researchers |

### How to apply user changes

1. **Make changes in the GitLab clone first**: `/home/mac/chakshu/ai-newsletter`
   - Use GitLab identity: `chakshu123` / `chakshu@otsuka-shokai.co.jp`.
   - Keep Otsuka-specific files (`README.md`, `backend/.env.example`, `compose.yml`,
     `backend/app/services/email_sender.py` taglines, `backend/app/services/llm_summarizer.py`
     prompts) tailored to the Otsuka deployment.
   - Push to GitLab `master`.

2. **Mirror code changes to the GitHub clone**:
   - Work in `/home/mac/chakshu/ai-research-digest-github`.
   - Use GitHub identity: `chakshu-dhannawat` / `chakshu.dhannawat1@gmail.com`.
   - Do **not** copy Otsuka-specific files from the GitLab clone.
   - Cherry-pick or re-apply the same code changes, but keep the generic README,
     `.env.example`, `compose.yml`, generic prompts/taglines, and generic defaults.
   - Push to GitHub `main`.

### What must stay generic in this repo

- `README.md` — generic quick-start, no Otsuka hostnames or internal endpoints.
- `backend/.env.example` — generic defaults (`localhost`, `example.com`).
- `compose.yml` — no hardcoded corporate proxy; read proxy from `.env`.
- `backend/app/services/llm_summarizer.py` — generic "AI researchers and engineers" prompts.
- `backend/app/services/email_sender.py` — generic taglines (no "@ Otsuka").

### What is shared between both repos

All code changes that are not environment-specific:
- Crawler logic (`news_fetcher.py`, `github_crawler.py`)
- Pipeline logic (`pipeline.py`)
- Scoring/prompt structure changes (but not org-specific wording)
- Email/Teams formatting improvements
- Bug fixes, tests, Makefile, docs under `docs/`

### Token locations

- GitHub token: loaded from `/home/mac/chakshu/github-oss/.envrc` via `source`.
- GitLab token: read from `/home/mac/chakshu/ai-newsletter/chakshu_gitlab_pat.txt`.
