# Personalization & Feedback — Design Doc

**Status:** Design only — not yet implemented.
**Decisions locked:** per-recipient send (drop BCC) · per-article 👍/👎 feedback · re-ranking by affinity (demote, never hard-filter) · **Microsoft MSAL auth on the homepage** · **explicit interest tags (4–5) set once at onboarding** · **two signals (explicit + implicit) merged by a decay algorithm**.

## Two-signal model (the key idea)

Personalization is driven by **two complementary signals** that combine into one affinity profile per user:

| Signal | Source | When | Strength |
|--------|--------|------|----------|
| **Explicit interests** | 4–5 tags the user picks on the homepage | Once at onboarding, editable anytime | Strong prior — instant cold-start, no waiting for data |
| **Implicit feedback** | Per-article 👍/👎 in the daily email | Continuously | Grows over time; can reinforce or override the explicit prior |

Explicit tags give a *good day-1 digest* without collecting data first. Implicit votes then refine it daily. If behaviour diverges from declared taste (declared "rag" but keeps downvoting it), the implicit signal gradually counteracts the explicit prior — because they're additive and implicit decays/accumulates.

---

## 1. Goal

Let each subscriber shape their own digest by reacting 👍/👎 to individual articles. Over time, each user's top-10 is re-ranked toward the topics they like and away from the ones they don't — without ever hard-hiding a topic (no filter bubble). The LLM scoring rubric stays global; personalization is a cheap per-user re-ranking layer on top of it.

---

## 2. Why this changes the send model

Today the pipeline sends **one BCC email per language** (`pipeline.py` loops over `lang_map`). All recipients get byte-identical HTML, so a feedback link can't know who clicked.

Personalization needs two things BCC can't provide:
1. **Attribution** — which user voted.
2. **Per-user content** — each user's re-ranked top-10.

So we move to **one email per subscriber**, each with:
- Their own re-ranked article list.
- 👍/👎 links carrying a signed token that identifies `(user, item)`.

Trade-off accepted: ~15 sends instead of 2. At this scale (seconds of extra SMTP time) this is fine.

---

## 3. Architecture Overview

```
   ONBOARDING (once)                          DAILY (continuous)
   ─────────────────                          ──────────────────
   user logs in via MSAL                      user clicks 👍/👎 in email
        │ verified MS email                        │
        ▼                                          ▼
   picks 4–5 interest tags             GET /api/feedback?t=<signed token>
        │                                          │ verify → record vote
        ▼                                          ▼
   subscribers.interests[]  ──┐         feedback table  ──┐
                              │                           │
                              ▼                           ▼
                       ┌──────────────────────────────────────┐
                       │  user_affinity  (explicit + implicit, │
                       │  time-decayed, per keyword/source)    │
                       └───────────────────┬──────────────────┘
                                           │ feeds
   daily cron ──► pipeline: fetch → age-filter → dedup → SCORE (global)
                                           │ scored items (0–10)
                                           ▼
                       FOR EACH subscriber:
                         load affinity profile (explicit+implicit)
                         re-rank scored items
                         take personalized top-10
                         render email w/ signed 👍/👎 links
                         send individually
```

---

## 4. Data Model

Two new tables. (`fetched_items` already stores `keywords[]` and `source`, which we reuse.)

### 4.1 `feedback` — raw vote log
```sql
CREATE TABLE feedback (
    id          SERIAL PRIMARY KEY,
    user_email  TEXT NOT NULL,
    item_url    TEXT NOT NULL,        -- stable key; matches fetched_items.url
    vote        SMALLINT NOT NULL,    -- +1 (up) / -1 (down)
    source      TEXT,                 -- denormalized at vote time
    keywords    TEXT[],               -- denormalized at vote time
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    UNIQUE (user_email, item_url)     -- one vote per user per article; re-click flips it
);
CREATE INDEX idx_feedback_user ON feedback(user_email);
```
Denormalizing `source` + `keywords` means affinity can be computed without joining back to `fetched_items` (and survives even if the item later ages out of the catalog).

### 4.2 `user_affinity` — derived per-user profile (a cache)
```sql
CREATE TABLE user_affinity (
    user_email  TEXT NOT NULL,
    dimension   TEXT NOT NULL,        -- 'keyword:rag' | 'source:labs'
    score       REAL NOT NULL,        -- signed, combined explicit + time-decayed implicit
    updated_at  TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    PRIMARY KEY (user_email, dimension)
);
```
This is a materialized convenience table. It can always be rebuilt from `feedback` + `subscribers.interests` — so it's safe to wipe and recompute if the formula changes.

### 4.3 `subscribers.interests` — explicit declared tags
```sql
ALTER TABLE subscribers ADD COLUMN IF NOT EXISTS interests TEXT[] DEFAULT '{}';
```
The 4–5 tags the user picks at onboarding (Section 13). Stored on the existing `subscribers` row (we already key everything by email). Editable from the homepage; empty `{}` = no explicit prior (pure implicit / global).

---

## 5. Identity: MSAL on the web, signed tokens in the email

Two contexts, two mechanisms, **one identity** (the Microsoft account email, which is also the Outlook/subscriber email — so they unify naturally):

### 5a. Homepage → Microsoft MSAL (verified login)
- The web UI authenticates with **Microsoft MSAL** (`@azure/msal-browser` on the React side, OAuth2/OIDC against Entra ID).
- After login we read the verified email (`preferred_username` / `email` claim) from the ID token.
- Because Outlook uses the *same* Microsoft account, that email **equals the subscriber email** — no separate account linking needed. We match `claim.email` → `subscribers.email` directly.
- Backend verifies the MSAL access token (validate signature against the Entra JWKS, check `aud`/`iss`/`exp`) on any write endpoint (set interests, change language, view profile).
- This gives strong, login-backed identity for *setting explicit interests* and *viewing one's profile* — no guessable email params.

### 5b. Email 👍/👎 → HMAC-signed token (frictionless, no login)
Requiring an MSAL login just to vote on an article would kill click-through. So email links keep using a self-contained HMAC token — the user votes in one click, no login. The token still ties the vote to the verified email captured at send time.

Each 👍/👎 link embeds an HMAC-signed token so it identifies the user and item, can't be forged, and needs no login.

```
token = base64url( payload ).base64url( hmac_sha256(secret, payload) )
payload = {"u": "<email>", "i": "<item_url_hash>", "v": "up|down", "n": <newsletter_id>}
```
- `secret` lives in `.env` as `FEEDBACK_SECRET` (new setting).
- Server recomputes the HMAC to verify; rejects tampered tokens.
- `n` (newsletter id) lets us trace which digest the vote came from and ignore stale links.
- No expiry needed initially; votes are idempotent (UNIQUE constraint upserts).

URL shape:
```
http://iitgpu07.hon.otsuka-shokai.co.jp:3737/api/feedback?t=<token>
```
(Frontend nginx already proxies `/api/` to the backend — no new routing.)

---

## 6. Endpoint

```
GET /api/feedback?t=<token>
  → verify HMAC
  → decode {user, item, vote, newsletter_id}
  → look up item's source + keywords from fetched_items (by url hash)
  → UPSERT into feedback (flip vote on repeat click)
  → enqueue/trigger affinity recompute for that user
  → return a minimal styled HTML "Thanks — recorded 👍" page
```
Notes:
- **GET, not POST** — email clients only follow links. (Caveat below on prefetching.)
- Must be tolerant: a double-click or an email-client link-prefetch should be harmless (idempotent upsert).
- Returns HTML (not JSON) since it renders in the user's browser.

---

## 7. Affinity model (the math)

Each dimension's affinity is the **sum of an explicit prior and the time-decayed implicit signal**:

```
affinity(user, dim) =  W_EXPLICIT · explicit(user, dim)          # declared interest
                     +  Σ  vote_v · exp(-Δdays / HALF_LIFE)       # daily 👍/👎
                       votes v on dim

explicit(user, dim) = 1 if dim == "keyword:<one of the user's interest tags>" else 0
W_EXPLICIT = 2.0        (tunable — a declared tag ≈ two recent upvotes)
HALF_LIFE  = 30 days    (tunable)
dim ∈ { keyword:<kw> for kw in item.keywords } ∪ { source:<item.source> }
```

**How the two signals interact over time:**
- **Day 1 (no votes):** affinity = explicit prior only → digest already tuned to declared interests.
- **As votes arrive:** implicit term grows. Consistent upvotes on a declared tag reinforce it; consistent downvotes accumulate negative and **cancel then overturn** the `+W_EXPLICIT` prior — so behaviour wins over declaration, gradually.
- **Decay:** old votes fade (30-day half-life), keeping the profile current. The explicit prior does **not** decay (it's a standing declaration) until the user edits their tags.

Example profile after a few weeks (declared tags: `rag`, `quantization`, `agents`):
```
keyword:rag           +3.4   (explicit +2.0, implicit +1.4)
keyword:quantization  +1.9   (explicit +2.0, implicit -0.1 — mild disengagement)
keyword:agents        +2.0   (explicit +2.0, no votes yet)
keyword:reasoning     +1.1   (no declaration, discovered via upvotes)
keyword:embodied-ai   -3.1   (implicit only — strongly disliked)
source:web_search     -0.8
```
Note `reasoning` surfaced from pure implicit signal (discovery), and `embodied-ai` is suppressed despite never being declared.

---

## 8. Re-ranking at send time

Global LLM score is computed once (unchanged). Then **per user**:

```
personal_score(item) = llm_score(item)                       # 0–10, global
                      + ALPHA · Σ affinity(user, "keyword:"+k) for k in item.keywords
                      + BETA  · affinity(user, "source:"+item.source)

ALPHA = 0.7,  BETA = 0.5     # tunable; keep small so LLM score still dominates
```
Then sort by `personal_score`, take top-10, render that user's email.

**Why this respects "demote, not filter":** a downvoted topic only *lowers* an item's rank. A truly excellent (LLM 9–10) robotics-adjacent paper can still surface if its base score outweighs the penalty. Nothing is ever removed from the candidate pool. **Cold start is solved by explicit interests:** a brand-new user with declared tags but no votes already has a non-zero affinity from the `W_EXPLICIT` prior, so their very first digest is personalized. A user who declared nothing falls back to `affinity = 0` → today's global ranking.

**Guardrails:**
- Clamp the total affinity adjustment to e.g. `[-4, +4]` so one strong opinion can't completely dominate the LLM signal.
- Keep ALPHA/BETA in config so they're tunable without code edits.

---

## 9. Pipeline changes (where code will touch later)

| File | Change |
|------|--------|
| `db/init.sql` + `database.py` | Create `feedback`, `user_affinity` tables; add `subscribers.interests TEXT[]` (+ startup migrations) |
| `config.py` / `.env` | `FEEDBACK_SECRET`, `AFFINITY_HALF_LIFE_DAYS`, `W_EXPLICIT`, `RERANK_ALPHA`, `RERANK_BETA`; Entra/MSAL: `MSAL_TENANT_ID`, `MSAL_CLIENT_ID`, `MSAL_AUDIENCE` |
| `services/feedback.py` (new) | token sign/verify, record vote, recompute affinity (explicit+implicit), load profile |
| `services/auth.py` (new) | validate MSAL access tokens against Entra JWKS; map email claim → subscriber |
| `services/pipeline.py` | After scoring: loop **per subscriber** (not per language) → re-rank → render → send individually. `mark_as_sent` still once total. |
| `services/email_sender.py` | `render_newsletter(..., feedback_tokens=...)`; accept per-item token map |
| `templates/newsletter.html` | Add 👍/👎 buttons per card linking to `/api/feedback?t=...` |
| `routers/api.py` | `GET /api/feedback`; `GET/POST /api/me/interests` (MSAL-protected); dashboard aggregate stats |
| Frontend | MSAL login (`@azure/msal-browser`); onboarding tag-picker (4–5 from taxonomy); "edit interests" + "my profile" views |

The per-subscriber loop replaces the current per-language loop. Language is then just a property of each subscriber (we already store it), so JA users get Japanese + personalization together.

> **MSAL app registration** is a one-time Entra ID setup (register an SPA, set redirect URI to the homepage, expose the email/openid/profile scopes). Capture the tenant + client IDs into `.env`. This is an infra task, not code.

---

## 10. Rollout phases

**Phase 0 — MSAL + explicit interests (independent, can ship first).**
Add MSAL login to the homepage, the onboarding tag-picker, and `subscribers.interests`. Users start declaring interests. Even before any feedback plumbing, this enables a *first* personalization pass (re-rank on explicit-only affinity). Low risk, self-contained.

**Phase 1 — Collect implicit feedback (low risk).**
`feedback`/`user_affinity` tables + endpoint + 👍/👎 links + per-recipient send with tokens. Re-ranking can stay off — votes accumulate and show in the dashboard. Validates the click→record loop in production.

**Phase 2 — Re-rank with combined affinity.**
Turn on affinity-based re-ranking (Section 8) using explicit + implicit. Keep `W_EXPLICIT`/ALPHA/BETA small initially, watch how lists shift.

**Phase 3 — Tune & observe.**
Expose per-user profiles + aggregate stats in the dashboard. Adjust HALF_LIFE / W_EXPLICIT / ALPHA / BETA. Optionally feed strong *aggregate* 👎 signals back into the global rubric.

(Level-3 "inject preferences into the LLM prompt per user" is explicitly out of scope — too costly for ~15 subscribers; revisit only if the audience grows large.)

---

## 11. Edge cases & risks

| Risk | Mitigation |
|------|-----------|
| **Email client link prefetch** (scanners/Outlook Safe Links auto-GET the link → fake votes) | Make the GET render a confirmation page with a real confirm button, OR require the click to land then confirm; track `User-Agent`; treat votes as low-stakes signal, not truth. Worst case: a little noise — re-ranking is robust to it. |
| Filter bubble | Already handled — demote-only + clamped adjustment + LLM score dominates. |
| Cold start (new user) | Zero affinity = today's global ranking. No special-casing needed. |
| Sparse votes | Time-decay + small ALPHA means a couple of votes nudge gently, don't swing wildly. |
| Token forgery | HMAC with server secret; tamper → reject. |
| Item ages out of catalog | `source`/`keywords` denormalized into `feedback` at vote time, so affinity survives. |
| Send volume grows | Per-recipient send is O(subscribers); fine for tens, revisit batching at hundreds. |
| Privacy | Votes are tied to internal work emails; keep the feedback table internal-only, don't expose per-user data in the public Explore UI. |
| **MSAL email ≠ subscriber email** | Match on the verified `email`/`preferred_username` claim; if a user's MS email isn't in `subscribers`, offer to subscribe them on first login (upsert). Normalize lowercase (already done). |
| **Free-text interest tags** | Onboarding picks from a **controlled taxonomy** (Section 13), not free text — so tags map exactly to item `keywords` and re-ranking actually matches. |
| Declared-but-never-engaged tag | Implicit decay + accumulation lets behaviour override the standing prior over time (Section 7). |
| MSAL token validation | Validate against Entra JWKS with `aud`/`iss`/`exp` checks server-side; never trust client-supplied email without a verified token. |

---

## 12. Open follow-ups (not blocking)

- Should a per-digest "was today useful?" rating also exist alongside per-article votes? (Decided: per-article for now.)
- Dashboard visualizations for aggregate + per-user signal — design when we build Phase 3.
- Whether strong aggregate 👎 on a source should auto-adjust the global rubric or just alert you to adjust it manually.

---

## 13. Onboarding: explicit interest tags

### 13.1 Flow
1. User opens the homepage → **Sign in with Microsoft** (MSAL).
2. First-time users see an onboarding card: *"Pick 4–5 topics you care about"* — a grid of toggle chips from the taxonomy below.
3. Selection saves to `subscribers.interests` (MSAL-protected `POST /api/me/interests`) and seeds `user_affinity`.
4. The choice is editable anytime from a "My interests" panel. Editing recomputes the explicit half of the affinity profile.

### 13.2 Controlled taxonomy (maps 1:1 to item `keywords`)
Interests are **not** free text — they're chosen from a curated list that matches the keywords the LLM already emits (Section: scoring rubric). This guarantees a declared tag actually matches incoming items. Proposed starter set (Otsuka-relevant, ~16 tags; user picks 4–5):

```
rag · fine-tuning · llm-serving · quantization · vector-search/ann
agents · context-engineering · evals · reasoning · long-context
vlm/document-ai · multimodal · moe · distillation · llm-security · embeddings
```

The taxonomy lives in one place (a constant shared by backend + frontend) so it stays in sync with the rubric's priority topics. When the rubric's hot-topics change, update the taxonomy too.

### 13.3 Why explicit + implicit, not one or the other
- **Explicit alone** = static; can't discover new interests or notice when declared taste goes stale.
- **Implicit alone** = cold-start problem; the first ~2 weeks are generic until enough votes accumulate.
- **Both** = instant good day-1 digest (explicit) that self-corrects and discovers (implicit). The merge formula (Section 7) is exactly how they reconcile: declaration is a *prior*, behaviour is the *evidence* that updates it.

### 13.4 Mapping interests → affinity at save time
```
on save interests = [t1..t5]:
    for each tag t:  user_affinity["keyword:"+t] gets explicit component = W_EXPLICIT
    (implicit component, if any, is preserved and re-summed)
    removed tags lose their explicit component (implicit history stays)
```
Because explicit and implicit are stored/summed separately, editing tags never erases vote history — it only changes the standing prior.
