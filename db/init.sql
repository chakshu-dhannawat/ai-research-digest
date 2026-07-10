CREATE TABLE IF NOT EXISTS newsletters (
    id SERIAL PRIMARY KEY,
    sent_at TIMESTAMP NOT NULL DEFAULT NOW(),
    subject TEXT NOT NULL,
    recipient_emails TEXT[] NOT NULL,
    item_count INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'pending',
    error_message TEXT,
    is_test BOOLEAN NOT NULL DEFAULT FALSE,
    model_used TEXT
);

CREATE TABLE IF NOT EXISTS newsletter_items (
    id SERIAL PRIMARY KEY,
    newsletter_id INTEGER REFERENCES newsletters(id) ON DELETE CASCADE,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT,
    summary TEXT NOT NULL,
    stars INTEGER,
    language TEXT,
    topics TEXT[],
    relevance_score REAL,
    created_at TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE TABLE IF NOT EXISTS sent_item_hashes (
    id SERIAL PRIMARY KEY,
    item_hash TEXT UNIQUE NOT NULL,
    sent_date DATE NOT NULL DEFAULT CURRENT_DATE
);

CREATE TABLE IF NOT EXISTS pipeline_runs (
    id SERIAL PRIMARY KEY,
    started_at TIMESTAMP NOT NULL DEFAULT NOW(),
    finished_at TIMESTAMP,
    status TEXT NOT NULL DEFAULT 'running',
    github_items_found INTEGER DEFAULT 0,
    news_items_found INTEGER DEFAULT 0,
    items_after_dedup INTEGER DEFAULT 0,
    error_message TEXT,
    is_test BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE IF NOT EXISTS subscribers (
    id SERIAL PRIMARY KEY,
    email TEXT UNIQUE NOT NULL,
    subscribed_at TIMESTAMP NOT NULL DEFAULT NOW(),
    active BOOLEAN NOT NULL DEFAULT TRUE,
    language TEXT NOT NULL DEFAULT 'en'
);

-- Searchable catalog of every fetched + scored item (deduped by URL across runs)
CREATE TABLE IF NOT EXISTS fetched_items (
    id SERIAL PRIMARY KEY,
    source TEXT NOT NULL,
    title TEXT NOT NULL,
    url TEXT UNIQUE,
    description TEXT,
    summary TEXT,
    application TEXT,
    relevance_score REAL,
    stars INTEGER,
    language TEXT,
    topics TEXT[],
    keywords TEXT[],
    published_at TIMESTAMPTZ,
    first_seen TIMESTAMP NOT NULL DEFAULT NOW(),
    last_seen TIMESTAMP NOT NULL DEFAULT NOW()
);

CREATE INDEX idx_sent_hashes_hash ON sent_item_hashes(item_hash);
CREATE INDEX idx_sent_hashes_date ON sent_item_hashes(sent_date);
CREATE INDEX idx_newsletters_sent_at ON newsletters(sent_at);
CREATE INDEX idx_pipeline_runs_started ON pipeline_runs(started_at);
CREATE INDEX idx_subscribers_active ON subscribers(active);
CREATE INDEX idx_fetched_items_score ON fetched_items(relevance_score DESC);
CREATE INDEX idx_fetched_items_source ON fetched_items(source);
CREATE INDEX idx_fetched_items_seen ON fetched_items(last_seen DESC);
CREATE INDEX idx_fetched_items_keywords ON fetched_items USING GIN (keywords);
