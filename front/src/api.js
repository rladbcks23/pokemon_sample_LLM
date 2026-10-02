// back(Django) API 호출. 개발 중엔 Vite 프록시로 /api → localhost:8000
const cache = new Map()

function qs(params) {
  const p = Object.entries(params || {}).filter(([, v]) => v !== undefined && v !== null && v !== '')
  return p.length ? '?' + new URLSearchParams(p).toString() : ''
}

async function request(path, options = {}) {
  const res = await fetch(`/api/${path}`, {
    headers: { 'Content-Type': 'application/json' },
    ...options,
  })
  const data = await res.json().catch(() => ({}))
  if (!res.ok) throw new Error(data.detail || `API 오류 ${res.status}`)
  return data
}

// GET. cache: true면 같은 요청을 한 번만 보냄 (선택지·포켓몬 목록처럼 잘 안 바뀌는 데이터)
export function get(path, params, { cache: useCache = false } = {}) {
  const key = path + qs(params)
  if (useCache && cache.has(key)) return cache.get(key)
  const p = request(key)
  if (useCache) {
    cache.set(key, p)
    p.catch(() => cache.delete(key))
  }
  return p
}

export function post(path, body) {
  return request(path, { method: 'POST', body: JSON.stringify(body) })
}

export const api = {
  ranking: (format) => get('ranking/', { format }),
  pokemonList: (format) => get('pokemon/', { format }, { cache: true }),
  pokemon: (id) => get(`pokemon/${id}/`, null, { cache: true }),
  teams: (params) => get('teams/', params),
  team: (id) => get(`teams/${id}/`),
  samples: (params) => get('samples/', params),
  speed: (top) => get('speed/', { top }),
  options: () => get('options/', null, { cache: true }),
  validate: (sample) => post('validate/', sample),
}

// 아이콘 주소 (scripts/download_assets.py로 받은 파일, Django가 /assets/로 제공)
export const img = {
  pokemon: (id) => `/assets/pokemon/${id}.png`,
  item: (id) => `/assets/items/${id}.png`,
  type: (t) => `/assets/types/${t}.png`,
}
