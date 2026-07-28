# CLAUDE.md — ai-newsletter

## Git identity (required)

Always commit as the **chakshu123** GitLab user in this repo:

- Name: `chakshu123`
- GitLab username: `chakshu123`
- Email: `chakshu@otsuka-shokai.co.jp`

The repo-local git config is already set to this. Before committing, verify:

```bash
git config user.name    # -> chakshu123
git config user.email   # -> chakshu@otsuka-shokai.co.jp
```

If it drifts (e.g. inherits a global identity), reset it:

```bash
git config user.name "chakshu123"
git config user.email "chakshu@otsuka-shokai.co.jp"
```

Never author commits in this repo under any other identity.

## Secrets

`backend/.env` holds real credentials and is git-ignored. Never commit it; keep
`backend/.env.example` in sync (placeholder values only).

## Operations

- The daily newsletter pipeline is scheduled for **07:50 JST** and should deliver by **08:00 JST**.
- If the pipeline fails to send, or no newsletter record exists for the day, the backend sends an alert email via the configured SMTP server to `ALERT_EMAIL` (default: `chakshu@otsuka-shokai.co.jp`).
- Canonical Docker Compose deployment runs from `/home/mac/chakshu/ai-newsletter`.
