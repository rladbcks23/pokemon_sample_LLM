import { createRouter, createWebHistory } from 'vue-router'

const routes = [
  { path: '/', name: 'ranking', component: () => import('@/views/RankingView.vue'), meta: { nav: 'ranking' } },
  { path: '/pokemon', name: 'pokemon', component: () => import('@/views/PokemonListView.vue'), meta: { nav: 'pokemon' } },
  { path: '/pokemon/:id', name: 'pokemon-detail', component: () => import('@/views/PokemonDetailView.vue'), meta: { nav: 'pokemon' } },
  { path: '/teams', name: 'teams', component: () => import('@/views/TeamListView.vue'), meta: { nav: 'teams' } },
  { path: '/teams/:id', name: 'team-detail', component: () => import('@/views/TeamDetailView.vue'), meta: { nav: 'teams' } },
  { path: '/builder', name: 'builder', component: () => import('@/views/BuilderView.vue'), meta: { nav: 'builder' } },
  // ?slot=N: 파티 빌딩 N번 슬롯 편집, ?pokemon=id: 이 포켓몬으로 시작, ?sample=id: 내 샘플 열기
  { path: '/sample', name: 'sample', component: () => import('@/views/SampleView.vue'), meta: { nav: 'sample' } },
  { path: '/mypage', name: 'mypage', component: () => import('@/views/MyPageView.vue'), meta: { nav: 'mypage' } },
]

const router = createRouter({
  history: createWebHistory(import.meta.env.BASE_URL),
  routes,
  scrollBehavior: () => ({ top: 0 }),
})

export default router
