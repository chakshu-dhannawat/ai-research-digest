const BASE = '/api'

async function request(path, opts = {}) {
  const res = await fetch(`${BASE}${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...opts,
  })
  if (!res.ok) {
    const text = await res.text()
    throw new Error(`${res.status}: ${text}`)
  }
  return res.json()
}

export const api = {
  getNewsletters: (limit = 50, includeTest = false) =>
    request(`/newsletters?limit=${limit}&include_test=${includeTest}`),
  getNewsletterItems: (id) => request(`/newsletters/${id}/items`),
  getRuns: (limit = 50, includeTest = false) =>
    request(`/runs?limit=${limit}&include_test=${includeTest}`),
  triggerPipeline: () => request('/pipeline/run', { method: 'POST' }),
  sendNow: (recipients) =>
    request('/pipeline/send-now', {
      method: 'POST',
      body: JSON.stringify({ recipients }),
    }),
  health: () => request('/health'),
  subscribe: (email, language = 'en') =>
    request('/subscribe', {
      method: 'POST',
      body: JSON.stringify({ email, language }),
    }),
  unsubscribe: (email) =>
    request('/subscribe', {
      method: 'DELETE',
      body: JSON.stringify({ email }),
    }),
  updateLanguage: (email, language) =>
    request('/subscribe/language', {
      method: 'POST',
      body: JSON.stringify({ email, language }),
    }),
  checkSubscription: (email) => request(`/subscribe/check?email=${encodeURIComponent(email)}`),
  getSubscribers: () => request('/subscribers'),
  searchItems: ({ q = '', source = '', keyword = '', minScore = 0, dateFrom = '', dateTo = '', limit = 60, offset = 0 } = {}) =>
    request(`/items?q=${encodeURIComponent(q)}&source=${encodeURIComponent(source)}&keyword=${encodeURIComponent(keyword)}&min_score=${minScore}&date_from=${dateFrom}&date_to=${dateTo}&limit=${limit}&offset=${offset}`),
  getItemSources: () => request('/items/sources'),
  getTopItems: (limit = 10) => request(`/items/top?limit=${limit}`),
  getHotTopics: (limit = 14) => request(`/items/hot-topics?limit=${limit}`),
}
