// 타입·스탯 표시와 실수치 계산 (back/apps/dex/stats.py와 같은 공식)
export const TYPES = ['Normal', 'Fire', 'Water', 'Electric', 'Grass', 'Ice', 'Fighting', 'Poison', 'Ground',
  'Flying', 'Psychic', 'Bug', 'Rock', 'Ghost', 'Dragon', 'Dark', 'Steel', 'Fairy']

export const TYPE_KO = {
  Normal: '노말', Fire: '불꽃', Water: '물', Electric: '전기', Grass: '풀', Ice: '얼음',
  Fighting: '격투', Poison: '독', Ground: '땅', Flying: '비행', Psychic: '에스퍼', Bug: '벌레',
  Rock: '바위', Ghost: '고스트', Dragon: '드래곤', Dark: '악', Steel: '강철', Fairy: '페어리',
}

// 기술 타입 점 색 (디자인의 타입 색)
export const TYPE_COLOR = {
  Normal: '#9a978f', Fire: '#e5835b', Water: '#5e8fd8', Electric: '#e3be3a', Grass: '#6fae4d', Ice: '#6cc3cc',
  Fighting: '#c8664f', Poison: '#9a62a8', Ground: '#bf9a4a', Flying: '#8f9be0', Psychic: '#e06f93', Bug: '#9aad3c',
  Rock: '#b3a36a', Ghost: '#7a66ad', Dragon: '#6a56d6', Dark: '#6f625a', Steel: '#8c9aab', Fairy: '#e38fc6',
}

export const STATS = ['hp', 'atk', 'def', 'spa', 'spd', 'spe']
export const STAT_KO = { hp: 'HP', atk: '공격', def: '방어', spa: '특공', spd: '특방', spe: '스피드' }
export const STAT_SHORT = { hp: 'H', atk: 'A', def: 'B', spa: 'C', spd: 'D', spe: 'S' }
export const CATEGORY_KO = { Physical: '물리', Special: '특수', Status: '변화' }

export const SP_MAX_PER_STAT = 32
export const SP_MAX_TOTAL = 66

// Lv50 챔피언스: HP = 종족 + SP + 75, 그 외 = floor((종족 + SP + 20) × 성격 보정)
export function calcStat(stat, base, sp = 0, plus = null, minus = null) {
  if (stat === 'hp') return base + sp + 75
  const v = base + sp + 20
  if (stat === plus) return Math.floor((v * 110) / 100)
  if (stat === minus) return Math.floor((v * 90) / 100)
  return v
}

export function calcStats(base, sp = {}, plus = null, minus = null) {
  return Object.fromEntries(STATS.map((s) => [s, calcStat(s, base[s], sp[s] || 0, plus, minus)]))
}

// SP를 "H2 A32 S32" 형태로 (0은 생략)
export function spText(sp) {
  if (!sp) return '—'
  const parts = STATS.filter((s) => sp[s]).map((s) => `${STAT_SHORT[s]}${sp[s]}`)
  return parts.length ? parts.join(' ') : '—'
}

export const spTotal = (sp) => STATS.reduce((a, s) => a + (sp?.[s] || 0), 0)

// 배율 표기: 4 → ×4, 0.5 → ½
export function mulText(m) {
  return { 4: '×4', 2: '×2', 0.5: '½', 0.25: '¼', 0: '0' }[m] ?? ''
}

// Showdown ID 규칙: 소문자 영숫자 ("Garchompite Z" → "garchompitez")
export const toId = (s) => (s || '').toLowerCase().replace(/[^a-z0-9]/g, '')

// 성능이 같아 하나로 합친 폼 (back/apps/dex/ids.py의 MERGED_POKEMON과 같음)
export const MERGED_POKEMON = { maushold: 'mausholdfour' }

// 브라우저에 저장된 예전 샘플의 포켓몬 ID를 현재 ID로
export function migrateSample(s) {
  if (s && MERGED_POKEMON[s.pokemon]) s.pokemon = MERGED_POKEMON[s.pokemon]
  return s
}

// 기술 기본 정렬: 타입 순서(노말 → 페어리) → 분류(물리 → 특수 → 변화) → 위력 높은 순
const CATEGORY_ORDER = ['Physical', 'Special', 'Status']
export function compareMoves(a, b) {
  return TYPES.indexOf(a.type) - TYPES.indexOf(b.type)
    || CATEGORY_ORDER.indexOf(a.category) - CATEGORY_ORDER.indexOf(b.category)
    || (b.power || 0) - (a.power || 0)
    || a.name_ko.localeCompare(b.name_ko, 'ko')
}
