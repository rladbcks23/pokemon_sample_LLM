// 샘플(ID만 저장) → 화면 표시용 정보. 포켓몬 목록·선택지·포켓몬 상세를 불러와 캐시해서 씀
import { reactive } from 'vue'
import { api } from '@/api'

const state = reactive({ pokemon: {}, items: {}, natures: {}, details: {}, ready: false })
let loading = null

// 포켓몬 목록(이름·타입·종족값)과 선택지(도구·성격)를 한 번만 불러옴
export function loadDex() {
  if (!loading) {
    loading = Promise.all([api.pokemonList('doubles'), api.options()]).then(([list, opts]) => {
      state.pokemon = Object.fromEntries(list.items.map((p) => [p.id, p]))
      state.items = Object.fromEntries(opts.items.map((i) => [i.id, i]))
      state.natures = Object.fromEntries(opts.natures.map((n) => [n.id, n]))
      state.options = opts
      state.list = list.items
      state.ready = true
    }).catch((e) => { loading = null; throw e })
  }
  return loading
}

// 포켓몬 상세(특성·배우는 기술·폼·사용률). 한 번 불러오면 캐시
export async function loadDetail(id) {
  if (!id) return null
  if (!state.details[id]) state.details[id] = await api.pokemon(id)
  return state.details[id]
}

export const dex = state

// 샘플이 그 포켓몬의 메가스톤을 들고 있으면 메가 폼 정보 (포켓몬 목록의 megas)
// 샘플은 "기본 폼 + 메가스톤"으로 저장하고, 화면에는 메가 폼으로 보여줌
export function megaForm(sample) {
  const megas = state.pokemon[sample?.pokemon]?.megas || []
  return megas.find((m) => m.item === sample?.item) || null
}

// 메가 폼 id → { base, item } (샘플로 저장할 모양)
export function fromMegaId(id) {
  for (const p of Object.values(state.pokemon)) {
    const m = p.megas?.find((x) => x.id === id)
    if (m) return { base: p.id, item: m.item }
  }
  return null
}

// MemberCard가 받는 모양으로 변환
export function describe(sample) {
  if (!sample?.pokemon) return null
  const base = state.pokemon[sample.pokemon] || { id: sample.pokemon, name_ko: sample.pokemon, types: [] }
  const mega = megaForm(sample)
  const p = mega || base
  const detail = state.details[sample.pokemon]
  const moves = detail ? Object.fromEntries(detail.learnset.map((m) => [m.id, m])) : {}
  const ability = detail?.forms[0].abilities.find((a) => a.id === sample.ability)
  const item = state.items[sample.item]
  const nature = state.natures[sample.nature]
  return {
    pokemon: { id: p.id, name_ko: p.name_ko, types: p.types },
    item: item ? { id: item.id, name_ko: item.name_ko } : null,
    // 메가 폼이면 특성도 메가 폼 특성
    ability: mega?.ability || (ability ? { id: ability.id, name_ko: ability.name_ko } : (sample.ability ? { name_ko: sample.ability } : null)),
    nature: nature ? { id: nature.id, name_ko: nature.name_ko } : null,
    sp: sample.sp,
    moves: sample.moves.map((id) => (id ? moves[id] || { id, name_ko: id } : null)),
    is_mega: !!mega,
  }
}
