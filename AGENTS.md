# AGENTS.md — ai-newsletter

## Git identity

Always commit as the **chakshu123** GitLab user:

- Name: `chakshu123`
- Email: `chakshu@otsuka-shokai.co.jp`

```bash
git config user.name "chakshu123"
git config user.email "chakshu@otsuka-shokai.co.jp"
```

## Secrets

`backend/.env` holds real credentials and is git-ignored. Never commit it.
Keep `backend/.env.example` in sync with placeholder values only.

## Operations

- The daily newsletter pipeline runs at **07:50 JST** and should deliver by **08:00 JST**.
- If the pipeline fails or no newsletter record exists for the day, the backend sends an alert email to `ALERT_EMAIL` (default: `chakshu@otsuka-shokai.co.jp`).
- Canonical Docker Compose deployment runs from `/home/mac/chakshu/ai-newsletter`.
