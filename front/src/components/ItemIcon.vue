<script setup>
import { ref, watch } from 'vue'
import { img } from '@/api'

const props = defineProps({
  id: { type: String, default: '' },
  size: { type: Number, default: 24 },
})
const broken = ref(false)
watch(() => props.id, () => { broken.value = false })
</script>

<template>
  <span class="iicon" :style="{ width: size + 'px', height: size + 'px' }">
    <img v-if="id && !broken" :src="img.item(id)" :alt="id" @error="broken = true">
  </span>
</template>

<style scoped>
.iicon {
  flex: none; display: inline-flex; align-items: center; justify-content: center;
  border: 1px solid var(--c-line-strong); border-radius: 4px; background: var(--c-chip);
}
.iicon img { max-width: 100%; max-height: 100%; image-rendering: pixelated; }
</style>
