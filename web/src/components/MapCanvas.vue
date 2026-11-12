<script setup lang="ts">
import { onMounted, onBeforeUnmount, ref } from 'vue'
import L from 'leaflet'
import 'leaflet/dist/leaflet.css'
import { LocateFixed, Minus, Plus } from '@lucide/vue'

defineProps<{ compact?: boolean }>()
const mapElement = ref<HTMLDivElement | null>(null)
const mapRef = ref<L.Map | null>(null)
const mapStatus = ref<'loading' | 'ready' | 'error'>('loading')
let fallbackTimer = 0
const start = () => {
  if (!mapElement.value || mapRef.value) return
  const map = L.map(mapElement.value, { zoomControl: false, attributionControl: true }).setView([30.72, 104.08], 10)
  const tiles = L.tileLayer('https://{s}.tile.openstreetmap.org/{z}/{x}/{y}.png', {
    maxZoom: 19,
    attribution: '&copy; <a href="https://www.openstreetmap.org/copyright">OpenStreetMap</a>',
  })
  tiles.on('tileload', () => { mapStatus.value = 'ready' })
  tiles.addTo(map)
  fallbackTimer = window.setTimeout(() => {
    if (mapStatus.value === 'loading') mapStatus.value = 'error'
  }, 5000)
  mapRef.value = map
  window.setTimeout(() => map.invalidateSize(), 80)
}
function zoom(delta: number) { mapRef.value?.setZoom((mapRef.value.getZoom() || 10) + delta) }
function locate() { mapRef.value?.setView([30.72, 104.08], 11) }
onMounted(start)
onBeforeUnmount(() => {
  window.clearTimeout(fallbackTimer)
  mapRef.value?.remove()
  mapRef.value = null
})
</script>

<template>
  <div class="map-canvas">
    <div ref="mapElement" class="leaflet-map"></div>
    <div class="map-overlay-label"><span class="map-pulse"></span><span>成都平原 · 区位示意</span></div>
    <div class="map-controls">
      <button title="放大" aria-label="放大地图" @click="zoom(1)"><Plus :size="17" /></button>
      <button title="缩小" aria-label="缩小地图" @click="zoom(-1)"><Minus :size="17" /></button>
      <span></span>
      <button title="定位研究区域" aria-label="定位研究区域" @click="locate"><LocateFixed :size="16" /></button>
    </div>
    <div v-if="mapStatus === 'error'" class="map-network-hint">在线底图不可达 · 示意网格</div>
    <div class="map-scale"><i></i><span>约 5 km</span></div>
  </div>
</template>
