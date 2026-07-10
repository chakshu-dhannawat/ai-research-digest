# Python Modular Codebase — `__init__.py` and Package Structure

## The Rule: Every Folder That Contains Python Code Is a Package

A **package** is a directory with an `__init__.py` file. Without it, Python doesn't treat the folder as importable.

### This project's structure
```
backend/
└── app/                        ← package (has __init__.py)
    ├── __init__.py             ← empty — just marks this as a package
    ├── main.py
    ├── config.py
    ├── database.py
    ├── models/                 ← sub-package (has __init__.py)
    │   ├── __init__.py         ← empty
    │   └── schemas.py
    ├── routers/                ← sub-package
    │   ├── __init__.py         ← empty
    │   └── api.py
    └── services/               ← sub-package
        ├── __init__.py         ← empty
        ├── pipeline.py
        ├── github_crawler.py
        ├── news_fetcher.py
        ├── llm_summarizer.py
        ├── dedup.py
        └── email_sender.py
```

All four `__init__.py` files in this project are **completely empty**. That's intentional and correct — their only job is to tell Python "this directory is a package."

---

## Why `__init__.py` Exists

Without it:
```python
from app.services.pipeline import run_pipeline   # ImportError
```

With it (even empty):
```python
from app.services.pipeline import run_pipeline   # Works
```

Python needs the file to resolve the import path `app → services → pipeline → run_pipeline`.

---

## What You Can Put in `__init__.py`

### Option 1: Leave it empty (used in this project)
```python
# __init__.py — empty
```
Clean. Simple. Each file is responsible for its own imports. This is the right choice for most projects.

### Option 2: Re-export for a cleaner public API
```python
# services/__init__.py
from .pipeline import run_pipeline
from .dedup import filter_already_sent, mark_as_sent
```
Now callers can write:
```python
from app.services import run_pipeline           # shorter
# instead of:
from app.services.pipeline import run_pipeline  # explicit
```
Use this when you want to hide internal file organization from callers.

### Option 3: Package-level initialization
```python
# models/__init__.py
import logging
logging.getLogger(__name__).info("models package loaded")
```
Runs once when any module in the package is first imported. Rarely needed.

**Recommendation: keep `__init__.py` empty unless you have a specific reason.**

---

## How Python Resolves Imports

Given this import in `pipeline.py`:
```python
from app.services.dedup import filter_already_sent
```

Python walks the path:
1. Find `app/` → check `app/__init__.py` exists ✓
2. Find `app/services/` → check `app/services/__init__.py` exists ✓
3. Find `app/services/dedup.py` ✓
4. Import `filter_already_sent` from it ✓

If any `__init__.py` is missing, step 1 or 2 fails with `ModuleNotFoundError`.

---

## Relative vs Absolute Imports

### Absolute (used everywhere in this project — preferred)
```python
from app.config import settings
from app.services.pipeline import run_pipeline
from app.models.schemas import NewsletterOut
```
Always starts from the root package (`app`). Unambiguous from anywhere in the codebase.

### Relative (alternative, avoid unless needed)
```python
# inside app/services/pipeline.py
from ..config import settings        # go up one level to app/, then config
from .dedup import filter_already_sent  # same directory
```
The `.` means "current package", `..` means "parent package". Works but harder to read and breaks if you move files.

**Stick with absolute imports.**

---

## How `uvicorn` Finds Your App

The `Dockerfile` runs:
```
uvicorn app.main:app --host 0.0.0.0 --port 8585
```

- `app.main` = the module path: `app/main.py`
- `:app` = the variable named `app` inside that module (the `FastAPI()` instance)
- uvicorn starts from `backend/` as the working directory, so `app/` is found as a top-level package

This is why the `backend/` folder itself does NOT need an `__init__.py` — it's the working directory root, not an importable package.

---

## When to Split into Sub-packages

Split a file into a sub-package when:
- A single file grows beyond ~300–400 lines and has clear internal sections
- Multiple files share utility code that doesn't belong in any one of them

Example: if `news_fetcher.py` grew large, you could do:
```
services/
    news_fetcher/
        __init__.py      # re-exports the public functions
        github.py
        rss.py
        scrapers.py
        hf_papers.py
```
And in `__init__.py`:
```python
from .github import fetch_trending_repos
from .rss import fetch_ai_newsletters, fetch_ai_voices, fetch_ai_labs
from .hf_papers import fetch_hf_papers
```
Callers (`pipeline.py`) don't change at all — they still write:
```python
from app.services.news_fetcher import fetch_hf_papers
```

---

## Summary

| Rule | Example in this project |
|------|------------------------|
| Every importable folder needs `__init__.py` | `app/`, `app/models/`, `app/routers/`, `app/services/` |
| Empty `__init__.py` is fine and common | All 4 files are empty |
| Use absolute imports | `from app.config import settings` |
| Working directory (`backend/`) doesn't need `__init__.py` | Only `app/` and below do |
| Split files → split packages when a file gets large | Not needed yet here |
