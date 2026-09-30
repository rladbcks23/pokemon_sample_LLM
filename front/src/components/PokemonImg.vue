<script setup>
import { ref, watch } from 'vue'
import { img } from '@/api'

// 포켓몬 이미지. 파일이 없으면 디자인의 빗금 자리표시로
const props = defineProps({
  id: { type: String, default: '' },
  size: { type: Number, default: 56 },
  dim: { type: Boolean, default: false },
})
const broken = ref(false)
watch(() => props.id, () => { broken.value = false })
</script>

<template>
  <div class="pimg" :class="{ empty: !id || broken, dim }" :style="{ width: size + 'px', height: size + 'px' }">
    <img v-if="id && !broken" :src="img.pokemon(id)" :alt="id" loading="lazy" @error="broken = true">
  </div>
</template>

<style scoped>
.pimg { flex: none; display: flex; align-items: center; justify-content: center; }
.pimg img { width: 100%; height: 100%; object-fit: contain; image-rendering: auto; }
.pimg.empty {
  background: repeating-linear-gradient(135deg, #eceae5 0 5px, #f7f6f3 5px 10px);
  border: 1px solid var(--c-line);
}
.pimg.dim { opacity: .35; }
</style>
