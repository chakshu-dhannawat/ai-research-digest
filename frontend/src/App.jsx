import React, { useState, useEffect } from 'react'
import { api } from './api/client.js'

const SOURCE_COLORS = {
  github: { accent: '#24292e', bg: '#f6f8fa', label: 'GitHub' },
  arxiv: { accent: '#b31b1b', bg: '#fef2f2', label: 'arXiv' },
  hf_papers: { accent: '#ea580c', bg: '#fff7ed', label: 'HF Papers' },
  newsletter: { accent: '#2563eb', bg: '#eff6ff', label: 'Blog' },
  hackernews: { accent: '#ff6600', bg: '#fff7ed', label: 'HN' },
  model_release: { accent: '#7c3aed', bg: '#f5f3ff', label: 'Model' },
  web_search: { accent: '#059669', bg: '#ecfdf5', label: 'Web' },
  voices: { accent: '#0891b2', bg: '#ecfeff', label: 'Voices' },
  labs: { accent: '#4f46e5', bg: '#eef2ff', label: 'Lab' },
}

function getSourceStyle(source) {
  return SOURCE_COLORS[source] || { accent: '#6b7280', bg: '#f9fafb', label: source }
}

// Backend stores naive UTC timestamps. Append 'Z' so the browser converts
// them to local time instead of misreading them as local (which shifted
// today's 09:00 JST send back to the previous day).
function parseUTC(ts) {
  if (ts && !/[zZ]|[+-]\d\d:?\d\d$/.test(ts)) ts = ts + 'Z'
  return new Date(ts)
}

function ScorePill({ score }) {
  const s = score || 0
  const bg = s >= 7 ? '#059669' : s >= 4 ? '#d97706' : '#dc2626'
  return (
    <span style={{
      display: 'inline-block', fontSize: 11, fontWeight: 700, padding: '2px 8px',
      borderRadius: 10, color: '#fff', background: bg, marginRight: 6,
    }}>
      {s.toFixed(0)}/10
    </span>
  )
}

function SourceTag({ source }) {
  const s = getSourceStyle(source)
  return (
    <span style={{
      display: 'inline-block', fontSize: 10, fontWeight: 600, padding: '2px 8px',
      borderRadius: 10, color: s.accent, background: s.bg, textTransform: 'uppercase',
    }}>
      {s.label}
    </span>
  )
}

function StatusDot({ status }) {
  const bg = status === 'sent' || status === 'completed' ? '#059669'
    : status === 'running' || status === 'started' ? '#d97706' : '#dc2626'
  return (
    <span style={{
      display: 'inline-block', width: 8, height: 8, borderRadius: '50%',
      background: bg, marginRight: 6, verticalAlign: 'middle',
    }} />
  )
}

/* ─── Home / Introduction ─── */
const SOURCE_LINKS = {
  'GitHub': 'https://github.com/trending',
  'arXiv': 'https://arxiv.org/list/cs.LG/recent',
  'HF Papers': 'https://huggingface.co/papers',
  'Model Releases': 'https://huggingface.co/models?sort=trending',
  'AI Labs & Reports': 'https://www.anthropic.com/research',
  'Voices': 'https://www.latent.space',
  'AI News & Blogs': 'https://www.marktechpost.com',
  'Web Search': 'https://duckduckgo.com',
}

function HomePanel() {
  const [email, setEmail] = useState('')
  const [checkResult, setCheckResult] = useState(null)
  const [msg, setMsg] = useState('')
  const [loading, setLoading] = useState(false)
  const [language, setLanguage] = useState('en')

  const checkStatus = async () => {
    if (!email.trim() || !email.includes('@')) return
    setLoading(true)
    setMsg('')
    setCheckResult(null)
    try {
      const result = await api.checkSubscription(email.trim())
      setCheckResult(result)
      if (result.language) setLanguage(result.language)
    } catch (e) {
      setMsg('Error: ' + e.message)
    }
    setLoading(false)
  }

  const handleSubscribe = async () => {
    setLoading(true)
    setMsg('')
    try {
      await api.subscribe(email.trim(), language)
      setMsg(`Subscribed!`)
      setCheckResult({ email: email.trim(), subscribed: true, language })
    } catch (e) {
      setMsg('Error: ' + e.message)
    }
    setLoading(false)
  }

  const handleUnsubscribe = async () => {
    setLoading(true)
    setMsg('')
    try {
      await api.unsubscribe(email.trim())
      setMsg(`Unsubscribed.`)
      setCheckResult({ email: email.trim(), subscribed: false })
    } catch (e) {
      setMsg('Error: ' + e.message)
    }
    setLoading(false)
  }

  const handleUpdateLanguage = async () => {
    setLoading(true)
    setMsg('')
    try {
      await api.updateLanguage(email.trim(), language)
      setMsg('Language updated.')
      setCheckResult(prev => ({ ...prev, language }))
    } catch (e) {
      setMsg('Error: ' + e.message)
    }
    setLoading(false)
  }

  const langLabel = (l) => (l === 'ja' ? '日本語' : 'English')

  const LangToggle = (
    <div className="lang-toggle">
      <button
        className={`chip ${language === 'en' ? 'chip-active' : ''}`}
        onClick={() => setLanguage('en')}
      >
        English
      </button>
      <button
        className={`chip ${language === 'ja' ? 'chip-active' : ''}`}
        onClick={() => setLanguage('ja')}
      >
        日本語
      </button>
    </div>
  )

  return (
    <div>
      {/* Subscribe */}
      <div className="card">
        <h3 className="card-title" style={{ marginBottom: 4 }}>Subscribe</h3>
        <p className="card-desc" style={{ marginBottom: 14 }}>Enter your email to check status or subscribe to the daily digest.</p>
        <div style={{ display: 'flex', gap: 8 }}>
          <input
            className="input"
            value={email}
            onChange={e => { setEmail(e.target.value); setCheckResult(null); setMsg('') }}
            placeholder="your.name@otsuka-shokai.co.jp"
            onKeyDown={e => e.key === 'Enter' && checkStatus()}
            style={{ flex: 1 }}
          />
          <button className="btn btn-primary" onClick={checkStatus} disabled={loading || !email.trim()}>
            Check Status
          </button>
        </div>

        {checkResult && (
          <div style={{ marginTop: 12 }}>
            <div style={{
              display: 'flex', alignItems: 'center', justifyContent: 'space-between',
              padding: '12px 16px', borderRadius: 10,
              background: checkResult.subscribed ? '#f0fdf4' : '#fef2f2',
              border: `1px solid ${checkResult.subscribed ? '#bbf7d0' : '#fecaca'}`,
            }}>
              <div style={{ display: 'flex', alignItems: 'center', gap: 10 }}>
                <span style={{
                  width: 30, height: 30, borderRadius: '50%', display: 'flex',
                  alignItems: 'center', justifyContent: 'center', fontSize: 14, fontWeight: 700,
                  background: checkResult.subscribed ? '#dcfce7' : '#fee2e2',
                  color: checkResult.subscribed ? '#166534' : '#991b1b',
                }}>
                  {checkResult.subscribed ? '✓' : '✗'}
                </span>
                <div>
                  <div style={{ fontWeight: 600, fontSize: 14 }}>{checkResult.email}</div>
                  <div style={{ fontSize: 12, color: checkResult.subscribed ? '#166534' : '#991b1b' }}>
                    {checkResult.subscribed ? 'Subscribed — receives daily newsletter at 8:00 AM JST' : 'Not subscribed'}
                  </div>
                  {checkResult.subscribed && checkResult.language && (
                    <div style={{ fontSize: 12, color: '#166534', marginTop: 2 }}>
                      {checkResult.language === 'ja'
                        ? `言語: ${langLabel(checkResult.language)}`
                        : `Language: ${langLabel(checkResult.language)}`}
                    </div>
                  )}
                </div>
              </div>
              {checkResult.subscribed ? (
                <button className="btn btn-danger" onClick={handleUnsubscribe} disabled={loading}>
                  Unsubscribe
                </button>
              ) : (
                <button className="btn btn-green" onClick={handleSubscribe} disabled={loading}>
                  Subscribe
                </button>
              )}
            </div>

            {checkResult.subscribed && (
              <div style={{ marginTop: 10, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
                <span style={{ fontSize: 13, color: '#475569', fontWeight: 500 }}>Newsletter language</span>
                {LangToggle}
                <button className="btn btn-primary" onClick={handleUpdateLanguage}
                  disabled={loading || language === checkResult.language}>
                  Update language
                </button>
              </div>
            )}
          </div>
        )}

        {(!checkResult || !checkResult.subscribed) && (
          <div style={{ marginTop: 12, display: 'flex', alignItems: 'center', gap: 8, flexWrap: 'wrap' }}>
            <span style={{ fontSize: 13, color: '#475569', fontWeight: 500 }}>Newsletter language</span>
            {LangToggle}
          </div>
        )}

        {msg && (
          <p style={{ fontSize: 13, marginTop: 8, color: msg.startsWith('Error') ? '#dc2626' : '#059669', fontWeight: 500 }}>
            {msg}
          </p>
        )}
      </div>

      {/* Hero */}
      <div className="hero" style={{ marginTop: 20 }}>
        <div className="hero-icon">&#129302;</div>
        <h2 className="hero-title">AI Engineer Daily Digest</h2>
        <p className="hero-desc">
          A curated daily newsletter for AI Engineers at Otsuka. Every morning at 8:00 AM JST,
          we crawl GitHub, arXiv &amp; trending papers, Hacker News, top AI blogs, influential voices &amp; labs,
          and model releases — then score and summarize the top 10 with an on-prem LLM, tailored to your work.
        </p>
      </div>

      {/* Sources overview */}
      <div className="source-grid">
        {[
          { icon: '&#128640;', name: 'Model Releases', desc: 'HuggingFace + labs: GLM, DeepSeek, Qwen, Kimi, MiniMax' },
          { icon: '&#128300;', name: 'AI Labs & Reports', desc: 'OpenAI, Anthropic, DeepMind, Google, HF, Together, Qwen' },
          { icon: '&#128483;&#65039;', name: 'Voices', desc: 'Eugene Yan, Nathan Lambert, Simon Willison, Raschka...' },
          { icon: '&#128220;', name: 'arXiv', desc: 'Latest research papers (cs.AI/CL/CV/LG)' },
          { icon: '&#128220;', name: 'HF Papers', desc: 'Community-trending papers (HuggingFace)' },
          { icon: '&#128187;', name: 'GitHub', desc: 'Trending AI repos' },
          { icon: '&#128240;', name: 'AI News & Blogs', desc: 'Import AI, Elastic, Latent Space, MarkTechPost' },
          { icon: '&#127760;', name: 'Web Search', desc: 'Breaking AI news' },
        ].map(s => (
          <a key={s.name} className="source-card" href={SOURCE_LINKS[s.name] || 'https://huggingface.co'}
            target="_blank" rel="noreferrer">
            <span className="source-icon" dangerouslySetInnerHTML={{ __html: s.icon }} />
            <span className="source-name">{s.name}</span>
            <span className="source-desc">{s.desc}</span>
          </a>
        ))}
      </div>
    </div>
  )
}

/* ─── Per-day History ─── */
function HistoryPanel() {
  const [newsletters, setNewsletters] = useState([])
  const [expanded, setExpanded] = useState(null)
  const [items, setItems] = useState([])
  const [showTest, setShowTest] = useState(false)

  useEffect(() => {
    api.getNewsletters(50, showTest).then(setNewsletters).catch(() => {})
  }, [showTest])

  const toggle = async (id) => {
    if (expanded === id) { setExpanded(null); return }
    setExpanded(id)
    try { setItems(await api.getNewsletterItems(id)) } catch { setItems([]) }
  }

  const grouped = newsletters.reduce((acc, n) => {
    const day = parseUTC(n.sent_at).toLocaleDateString('en-US', {
      weekday: 'long', year: 'numeric', month: 'long', day: 'numeric',
    })
    if (!acc[day]) acc[day] = []
    acc[day].push(n)
    return acc
  }, {})

  return (
    <div>
      <div style={{ display: 'flex', alignItems: 'center', justifyContent: 'space-between', marginBottom: 16 }}>
        <h3 style={{ fontSize: 16, fontWeight: 700, margin: 0 }}>Newsletter History</h3>
        <label style={{ display: 'flex', alignItems: 'center', gap: 6, fontSize: 13, color: '#64748b', cursor: 'pointer' }}>
          <input type="checkbox" checked={showTest} onChange={e => setShowTest(e.target.checked)} />
          Include test sends
        </label>
      </div>

      {Object.keys(grouped).length === 0 && (
        <div className="card" style={{ textAlign: 'center', padding: 48 }}>
          <p style={{ fontSize: 40, marginBottom: 10 }}>&#128237;</p>
          <p style={{ fontWeight: 600, fontSize: 16, marginBottom: 6 }}>
            {showTest ? 'No newsletters found' : 'No production newsletters yet'}
          </p>
          <p className="meta" style={{ maxWidth: 400, margin: '0 auto' }}>
            {showTest
              ? 'No newsletters have been sent yet.'
              : 'Production newsletters are sent daily at 8:00 AM JST. Toggle "Include test sends" above to see test history.'}
          </p>
        </div>
      )}

      {Object.entries(grouped).map(([day, nls]) => (
        <div key={day} style={{ marginBottom: 28 }}>
          <div className="day-header">
            <span className="day-label">{day}</span>
            <span className="meta">{nls.length} send{nls.length > 1 ? 's' : ''} &middot; {nls.reduce((s, n) => s + n.item_count, 0)} total items</span>
          </div>
          {nls.map(n => (
            <div key={n.id} className="card card-clickable" onClick={() => toggle(n.id)}>
              <div className="nl-row">
                <div style={{ display: 'flex', alignItems: 'center', gap: 8, flex: 1, minWidth: 0 }}>
                  <StatusDot status={n.status} />
                  <span className="nl-subject">{n.subject}</span>
                  {n.is_test && <span className="badge badge-yellow">Test</span>}
                </div>
                <div className="nl-meta">
                  <span className="pill">{n.item_count} items</span>
                  <span className="meta">
                    {parseUTC(n.sent_at).toLocaleTimeString('en-US', { hour: '2-digit', minute: '2-digit' })}
                  </span>
                  <span className="meta" style={{ maxWidth: 220, overflow: 'hidden', textOverflow: 'ellipsis', whiteSpace: 'nowrap' }}>
                    {n.recipient_emails.join(', ')}
                  </span>
                  <span className="chevron" style={{ transform: expanded === n.id ? 'rotate(180deg)' : 'rotate(0)' }}>
                    &#9662;
                  </span>
                </div>
              </div>

              {expanded === n.id && (
                <div className="nl-items" onClick={e => e.stopPropagation()}>
                  {items.map(it => {
                    const ss = getSourceStyle(it.source)
                    return (
                      <div key={it.id} className="item-card" style={{ borderLeftColor: ss.accent }}>
                        <div style={{ display: 'flex', alignItems: 'center', gap: 6, flexWrap: 'wrap', marginBottom: 4 }}>
                          <ScorePill score={it.relevance_score} />
                          <SourceTag source={it.source} />
                          {it.stars != null && (
                            <span style={{ fontSize: 11, color: '#b45309', fontWeight: 600 }}>
                              &#11088; {it.stars.toLocaleString()}
                            </span>
                          )}
                          {it.language && (
                            <span style={{
                              fontSize: 10, fontWeight: 600, padding: '2px 6px',
                              borderRadius: 8, background: '#ede9fe', color: '#6d28d9',
                            }}>
                              {it.language}
                            </span>
                          )}
                        </div>
                        <h4 className="item-title">
                          {it.url ? (
                            <a href={it.url} target="_blank" rel="noreferrer" className="item-link">{it.title}</a>
                          ) : it.title}
                        </h4>
                        {it.topics && it.topics.length > 0 && (
                          <div style={{ display: 'flex', flexWrap: 'wrap', gap: 4, marginBottom: 4 }}>
                            {it.topics.slice(0, 5).map(t => (
                              <span key={t} className="topic-pill">{t}</span>
                            ))}
                          </div>
                        )}
                        {it.summary && <p className="item-summary">{it.summary}</p>}
                      </div>
                    )
                  })}
                  {items.length === 0 && <p className="meta">No items.</p>}
                </div>
              )}
            </div>
          ))}
        </div>
      ))}
    </div>
  )
}

/* ─── Send Test (last tab) ─── */
function SendPanel() {
  const [emails, setEmails] = useState('')
  const [msg, setMsg] = useState('')
  const [loading, setLoading] = useState(false)

  const send = async () => {
    const recipients = emails.split(',').map(e => e.trim()).filter(Boolean)
    if (!recipients.length) return
    setLoading(true)
    setMsg('')
    try {
      await api.sendNow(recipients)
      setMsg('Pipeline started — emails will be sent in ~3 minutes.')
    } catch (e) {
      setMsg('Error: ' + e.message)
    }
    setLoading(false)
  }

  return (
    <div className="card">
      <div className="card-header">
        <div style={{ display: 'flex', alignItems: 'center', gap: 8 }}>
          <h3 className="card-title">Send Test Newsletter</h3>
          <span className="badge badge-yellow">Test Mode</span>
        </div>
        <p className="card-desc">
          Run the full pipeline and send to custom recipients. Test sends skip dedup and are not shown in production history.
        </p>
      </div>
      <label className="label">Recipient emails (comma-separated)</label>
      <input
        className="input"
        value={emails}
        onChange={e => setEmails(e.target.value)}
        placeholder="email1@otsuka-shokai.co.jp, email2@otsuka-shokai.co.jp"
      />
      <div style={{ marginTop: 14, display: 'flex', gap: 10, alignItems: 'center' }}>
        <button className="btn btn-primary" onClick={send} disabled={loading || !emails.trim()}>
          {loading ? (
            <><span className="spinner" /> Running Pipeline...</>
          ) : (
            'Run Pipeline & Send'
          )}
        </button>
        {msg && (
          <span style={{ fontSize: 13, color: msg.startsWith('Error') ? '#dc2626' : '#059669', fontWeight: 500 }}>
            {msg}
          </span>
        )}
      </div>
    </div>
  )
}

/* ─── Explore: searchable catalog of all fetched items ─── */
const DATE_PRESETS = [['All', null], ['Last week', 7], ['Last month', 30], ['Last 3 months', 90]]

function daysAgoISO(days) {
  const d = new Date()
  d.setDate(d.getDate() - days)
  return d.toISOString().slice(0, 10)
}

/* localStorage-backed favorites (no login → personal, per-browser) */
const FAV_KEY = 'ainl_favorites'
function loadFavs() {
  try { return JSON.parse(localStorage.getItem(FAV_KEY) || '[]') } catch { return [] }
}
function useFavorites() {
  const [favs, setFavs] = useState(loadFavs)
  const ids = new Set(favs.map(f => f.id))
  const toggle = (it) => {
    setFavs(prev => {
      const next = prev.some(f => f.id === it.id)
        ? prev.filter(f => f.id !== it.id)
        : [{ id: it.id, source: it.source, title: it.title, url: it.url,
             relevance_score: it.relevance_score, summary: it.summary, application: it.application,
             keywords: it.keywords, topics: it.topics, stars: it.stars,
             published_at: it.published_at, last_seen: it.last_seen }, ...prev].slice(0, 200)
      localStorage.setItem(FAV_KEY, JSON.stringify(next))
      return next
    })
  }
  return { favs, ids, toggle }
}

function ExploreCard({ it, faved, onFav, onKeyword }) {
  const ss = getSourceStyle(it.source)
  const dt = it.published_at ? new Date(it.published_at) : (it.last_seen ? parseUTC(it.last_seen) : null)
  const tags = (it.keywords && it.keywords.length ? it.keywords : it.topics) || []
  return (
    <div className="explore-card" style={{ borderTopColor: ss.accent }}>
      <div className="explore-head">
        <ScorePill score={it.relevance_score} />
        <SourceTag source={it.source} />
        {it.stars != null && (
          <span style={{ fontSize: 11, color: '#b45309', fontWeight: 600 }}>&#11088; {it.stars.toLocaleString()}</span>
        )}
        {dt && (
          <span className="meta">{dt.toLocaleDateString('en-US', { month: 'short', day: 'numeric' })}</span>
        )}
        <button className={`fav-star ${faved ? 'fav-on' : ''}`} style={{ marginLeft: 'auto' }}
          onClick={() => onFav(it)} title={faved ? 'Remove favorite' : 'Save to favorites'}>
          {faved ? '★' : '☆'}
        </button>
      </div>
      <h4 className="item-title">
        {it.url ? <a href={it.url} target="_blank" rel="noreferrer" className="item-link">{it.title}</a> : it.title}
      </h4>
      {it.summary && <p className="item-summary">{it.summary}</p>}
      {it.application && <div className="apply-box">&#128161; {it.application}</div>}
      {tags.length > 0 && (
        <div className="kw-row">
          {tags.slice(0, 5).map(t => (
            <button key={t} className="kw-pill" onClick={() => onKeyword(t)} title={`Filter by ${t}`}>#{t}</button>
          ))}
        </div>
      )}
    </div>
  )
}

function ExplorePanel() {
  const [query, setQuery] = useState('')
  const [active, setActive] = useState('')        // source filter ('' = all)
  const [keyword, setKeyword] = useState('')      // active keyword/topic filter
  const [dateFrom, setDateFrom] = useState('')
  const [dateTo, setDateTo] = useState('')
  const [range, setRange] = useState(null)        // active preset (null = All/custom)
  const [meta, setMeta] = useState({ total: 0, sources: [] })
  const [items, setItems] = useState([])
  const [loading, setLoading] = useState(false)
  const [top, setTop] = useState([])
  const [hot, setHot] = useState([])
  const [showFavs, setShowFavs] = useState(false)
  const fav = useFavorites()

  const load = async (q = query, source = active, kw = keyword, from = dateFrom, to = dateTo) => {
    setLoading(true)
    setShowFavs(false)
    try {
      setItems(await api.searchItems({ q, source, keyword: kw, dateFrom: from, dateTo: to }))
    } catch { setItems([]) }
    setLoading(false)
  }

  useEffect(() => {
    api.getItemSources().then(setMeta).catch(() => {})
    api.getTopItems(10).then(setTop).catch(() => {})
    api.getHotTopics(14).then(setHot).catch(() => {})
    load('', '', '', '', '')
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [])

  const pickSource = (s) => { setActive(s); load(query, s, keyword) }
  const pickRange = (days) => {
    setRange(days)
    const from = days == null ? '' : daysAgoISO(days)
    setDateFrom(from); setDateTo('')
    load(query, active, keyword, from, '')
  }
  const pickKeyword = (k) => {
    const nk = keyword === k ? '' : k
    setKeyword(nk)
    load(query, active, nk)
  }

  const shown = showFavs ? fav.favs : items

  return (
    <div>
      <div style={{ marginBottom: 14 }}>
        <h3 style={{ fontSize: 16, fontWeight: 700, margin: '0 0 4px' }}>Explore</h3>
        <p className="meta">Every crawled &amp; scored item across all runs — {meta.total} in the catalog.</p>
      </div>

      {/* Top 10 rail */}
      {top.length > 0 && !showFavs && (
        <div className="card top10">
          <div className="top10-head">
            <span className="top10-title">&#128293; Top 10</span>
            <span className="meta">highest-scored · last 14 days</span>
          </div>
          <p className="top10-intro">
            Your daily shortlist — the 10 most relevant AI items from the last 14 days,
            auto-ranked by the LLM with a one-line take on each. No searching needed.
          </p>
          <div className="top10-list">
            {top.map((it, idx) => (
              <div key={it.id} className="top10-item">
                <div className="top10-item-head">
                  <span className="top10-rank">#{idx + 1}</span>
                  <ScorePill score={it.relevance_score} />
                  <SourceTag source={it.source} />
                  <button className={`fav-star ${fav.ids.has(it.id) ? 'fav-on' : ''}`} style={{ marginLeft: 'auto' }}
                    onClick={() => fav.toggle(it)} title="Favorite">{fav.ids.has(it.id) ? '★' : '☆'}</button>
                </div>
                <h4 className="top10-item-title">
                  {it.url ? <a href={it.url} target="_blank" rel="noreferrer" className="item-link">{it.title}</a> : it.title}
                </h4>
                {it.summary && <p className="top10-summary">{it.summary}</p>}
              </div>
            ))}
          </div>
        </div>
      )}

      {/* Search */}
      <div style={{ display: 'flex', gap: 8, marginBottom: 12 }}>
        <input
          className="input"
          value={query}
          onChange={e => setQuery(e.target.value)}
          onKeyDown={e => e.key === 'Enter' && load()}
          placeholder="Search title, summary, keywords… (e.g. RAG, vLLM, Gemini)"
          style={{ flex: 1 }}
        />
        <button className="btn btn-primary" onClick={() => load()} disabled={loading}>
          {loading ? <><span className="spinner" /> …</> : 'Search'}
        </button>
      </div>

      {/* Hot Topics */}
      {hot.length > 0 && (
        <div className="chips hot-row">
          <span className="date-label" style={{ marginRight: 2 }}>&#128293; Hot</span>
          {hot.map(t => (
            <button key={t.keyword} className={`chip ${keyword === t.keyword ? 'chip-active' : ''}`}
              onClick={() => pickKeyword(t.keyword)}>
              {t.keyword} <span className="chip-count">{t.count}</span>
            </button>
          ))}
        </div>
      )}

      {/* Source filter + Favorites */}
      <div className="chips">
        <button className={`chip ${!showFavs && active === '' ? 'chip-active' : ''}`} onClick={() => pickSource('')}>
          All <span className="chip-count">{meta.total}</span>
        </button>
        {meta.sources.map(s => (
          <button key={s.source} className={`chip ${!showFavs && active === s.source ? 'chip-active' : ''}`}
            onClick={() => pickSource(s.source)}>
            {getSourceStyle(s.source).label} <span className="chip-count">{s.count}</span>
          </button>
        ))}
        <button className={`chip ${showFavs ? 'chip-active' : ''}`} onClick={() => setShowFavs(v => !v)}>
          ★ Favorites <span className="chip-count">{fav.favs.length}</span>
        </button>
      </div>

      {/* Date filter */}
      <div className="date-filter">
        <span className="date-label">Date</span>
        {DATE_PRESETS.map(([lbl, d]) => (
          <button key={lbl} className={`chip ${range === d ? 'chip-active' : ''}`} onClick={() => pickRange(d)}>{lbl}</button>
        ))}
        <span className="date-sep" />
        <span className="date-label" style={{ marginRight: 0 }}>Custom</span>
        <input type="date" className="date-input" value={dateFrom}
          onChange={e => { setDateFrom(e.target.value); setRange(null) }} />
        <span className="meta">to</span>
        <input type="date" className="date-input" value={dateTo}
          onChange={e => { setDateTo(e.target.value); setRange(null) }} />
        <button className="btn btn-primary" onClick={() => load()} disabled={loading}>Apply</button>
      </div>

      {/* Result bar */}
      <div className="result-bar">
        <span className="meta">
          {showFavs ? `${fav.favs.length} favorite${fav.favs.length === 1 ? '' : 's'}`
            : `showing ${shown.length}${shown.length >= 60 ? '+' : ''} of ${meta.total}`}
        </span>
        {keyword && !showFavs && (
          <button className="chip chip-active" onClick={() => pickKeyword(keyword)}>#{keyword} &#10005;</button>
        )}
      </div>

      {shown.length === 0 && !loading && (
        <div className="card" style={{ textAlign: 'center', padding: 40 }}>
          <p style={{ fontSize: 36, marginBottom: 8 }}>{showFavs ? '☆' : '🔍'}</p>
          <p style={{ fontWeight: 600 }}>{showFavs ? 'No favorites yet' : 'No items found'}</p>
          <p className="meta">{showFavs ? 'Tap ☆ on any card to save it here.' : 'Try a different search term or filter.'}</p>
        </div>
      )}

      <div className="explore-grid">
        {shown.map(it => (
          <ExploreCard key={it.id} it={it} faved={fav.ids.has(it.id)} onFav={fav.toggle} onKeyword={pickKeyword} />
        ))}
      </div>
    </div>
  )
}

/* ─── Main App ─── */
const TABS = [
  { key: 'home', label: 'Home' },
  { key: 'history', label: 'History' },
  { key: 'explore', label: 'Explore' },
  { key: 'send', label: 'Test Send' },
]

export default function App() {
  const [tab, setTab] = useState('home')
  const [health, setHealth] = useState(null)

  useEffect(() => {
    api.health().then(() => setHealth('ok')).catch(() => setHealth('error'))
  }, [])

  return (
    <div className="app">
      <header className="header">
        <div className="header-inner">
          <div className="header-left">
            <h1 className="logo">AI Newsletter</h1>
            <span className="logo-sub">Daily Digest for AI Engineers @ Otsuka</span>
          </div>
          <div className="header-right">
            <span className={`health-badge ${health === 'ok' ? 'health-ok' : 'health-err'}`}>
              {health === 'ok' ? 'Connected' : health === 'error' ? 'Offline' : '...'}
            </span>
          </div>
        </div>
      </header>

      <nav className="nav">
        <div className="nav-inner">
          {TABS.map(t => (
            <button
              key={t.key}
              className={`nav-tab ${tab === t.key ? 'nav-tab-active' : ''}`}
              onClick={() => setTab(t.key)}
            >
              {t.label}
            </button>
          ))}
        </div>
      </nav>

      <main className="main">
        {tab === 'home' && <HomePanel />}
        {tab === 'history' && <HistoryPanel />}
        {tab === 'explore' && <ExplorePanel />}
        {tab === 'send' && <SendPanel />}
      </main>
    </div>
  )
}
