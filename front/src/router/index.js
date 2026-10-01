import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  // 랭킹은 포켓몬 탭(사용률 순)과 겹쳐서 메뉴에서 숨김. 첫 화면은 포켓몬, /ranking 주소로는 아직 열림
  { path: '/', redirect: '/pokemon' },
  { path: '/ranking', name: 'ranking', component: () => import('@/views/RankingView.vue'), meta: { nav: 'ranking' } },
  { path: '/pokemon', name: 'pokemon', component: () => import('@/views/PokemonListView.vue'), meta: { nav: 'pokemon' } },
  { path: '/pokemon/:id', name: 'pokemon-detail', component: () => import('@/views/PokemonDetailView.vue'), meta: { nav: 'pokemon' } },
  // 샘플 탭: 포켓몬 샘플(/samples) / 파티 샘플(/teams)
  { path: '/samples', name: 'samples', component: () => import('@/views/SampleListView.vue'), meta: { nav: 'samples' } },
  { path: '/teams', name: 'teams', component: () => import('@/views/TeamListView.vue'), meta: { nav: 'samples' } },
  { path: '/teams/:id', name: 'team-detail', component: () => import('@/views/TeamDetailView.vue'), meta: { nav: 'samples' } },
  { path: '/builder', name: 'builder', component: () => import('@/views/BuilderView.vue'), meta: { nav: 'builder' } },
  // ?slot=N: 파티 빌딩 N번 슬롯 편집, ?pokemon=id: 이 포켓몬으로 시작, ?sample=id: 내 샘플 열기
  { path: '/sample', name: 'sample', component: () => import('@/views/SampleView.vue'), meta: { nav: 'sample' } },
  { path: '/speed', name: 'speed', component: () => import('@/views/SpeedView.vue'), meta: { nav: 'speed' } },
  { path: '/mypage', name: 'mypage', component: () => import('@/views/MyPageView.vue'), meta: { nav: 'mypage' } },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

export default router
