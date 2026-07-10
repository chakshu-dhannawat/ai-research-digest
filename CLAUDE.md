# CLAUDE.md — ai-newsletter

## Git identity (required)

Always commit as the **chakshu** user in this repo:

- Name: `chakshu`
- GitLab username: `chakshu123`
- Email: `chakshu@otsuka-shokai.co.jp`

The repo-local git config is already set to this. Before committing, verify:

```bash
git config user.name    # -> chakshu
git config user.email   # -> chakshu@otsuka-shokai.co.jp
```

If it drifts (e.g. inherits a global identity), reset it:

```bash
git config user.name "chakshu"
git config user.email "chakshu@otsuka-shokai.co.jp"
```

Never author commits in this repo under any other identity.

## Secrets

`backend/.env` holds real credentials and is git-ignored. Never commit it; keep
`backend/.env.example` in sync (placeholder values only).
