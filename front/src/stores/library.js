import { defineStore } from 'pinia'
import { ref, watch } from 'vue'

// 찜·내가 만든 파티/샘플. 로그인 없이 이 브라우저(localStorage)에만 저장
const KEY = 'pb-library-v1'

function load() {
  try {
    return JSON.parse(localStorage.getItem(KEY)) || {}
  } catch {
    return {}
  }
}

export const newId = (prefix) => `${prefix}-${Date.now().toString(36)}${Math.random().toString(36).slice(2, 6)}`

// 샘플(한 마리 육성형) 모양
export const emptySample = (pokemon = null) => ({
  id: null, pokemon, item: '', ability: '', nature: '',
  sp: { hp: 0, atk: 0, def: 0, spa: 0, spd: 0, spe: 0 }, moves: ['', '', '', ''],
})

export const useLibrary = defineStore('library', () => {
  const s = load()
  const favTeams = ref(s.favTeams || [])       // 파티 요약 (API의 team_summary 그대로)
  const favSamples = ref(s.favSamples || [])
  const myTeams = ref(s.myTeams || [])         // { id, name, format, slots: [sample|null ×6], updatedAt }
  const mySamples = ref(s.mySamples || [])

  watch([favTeams, favSamples, myTeams, mySamples], () => {
    try {
      localStorage.setItem(KEY, JSON.stringify({
        favTeams: favTeams.value, favSamples: favSamples.value,
        myTeams: myTeams.value, mySamples: mySamples.value,
      }))
    } catch { /* 저장 불가 환경 */ }
  }, { deep: true })

  const isFavTeam = (id) => favTeams.value.some((t) => t.id === id)
  function toggleFavTeam(team) {
    favTeams.value = isFavTeam(team.id)
      ? favTeams.value.filter((t) => t.id !== team.id)
      : [{ ...team, savedAt: Date.now() }, ...favTeams.value]
  }

  function saveTeam(team) {
    const t = { ...team, id: team.id || newId('team'), updatedAt: Date.now() }
    const i = myTeams.value.findIndex((x) => x.id === t.id)
    if (i >= 0) myTeams.value.splice(i, 1, t)
    else myTeams.value.unshift(t)
    return t
  }
  const removeTeam = (id) => { myTeams.value = myTeams.value.filter((t) => t.id !== id) }

  function saveSample(sample) {
    const x = { ...sample, id: sample.id || newId('sample'), updatedAt: Date.now() }
    const i = mySamples.value.findIndex((y) => y.id === x.id)
    if (i >= 0) mySamples.value.splice(i, 1, x)
    else mySamples.value.unshift(x)
    return x
  }
  const removeSample = (id) => { mySamples.value = mySamples.value.filter((x) => x.id !== id) }
  const removeFavSample = (id) => { favSamples.value = favSamples.value.filter((x) => x.id !== id) }

  return {
    favTeams, favSamples, myTeams, mySamples,
    isFavTeam, toggleFavTeam, saveTeam, removeTeam, saveSample, removeSample, removeFavSample,
  }
})
