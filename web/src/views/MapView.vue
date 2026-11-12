<script setup lang="ts">
import { computed, ref } from 'vue'
import { Eye, EyeOff, Layers3, Map as MapIcon, RotateCcw, SlidersHorizontal } from '@lucide/vue'
import MapCanvas from '../components/MapCanvas.vue'
import { useReleaseStore } from '../stores/release'

const release = useReleaseStore()
const selectedYear = ref(2021)
const visible = ref<Record<string, boolean>>({ boundary: true, classification: true, change: false })
const layers = computed(() => release.manifest?.resources?.layers?.status === 'ready')
function toggle(key: string) { visible.value[key] = !visible.value[key] }
</script>

<template>
  <div class="map-page">
    <div class="map-toolbar">
      <div><div class="eyebrow"><span class="eyebrow-line"></span>空间分析 / 地图浏览</div><h1>时空地图</h1></div>
      <div class="map-toolbar-actions"><div class="segmented"><button :class="{ selected: selectedYear === 1992 }" @click="selectedYear = 1992">1992</button><button :class="{ selected: selectedYear === 2021 }" @click="selectedYear = 2021">2021</button><button :class="{ selected: selectedYear === 0 }" @click="selectedYear = 0">变化</button></div><button class="icon-button" title="重置图层" aria-label="重置图层" @click="visible = { boundary: true, classification: true, change: false }"><RotateCcw :size="17" /></button></div>
    </div>
    <div class="map-workspace">
      <section class="map-main"><MapCanvas />
        <div class="map-data-notice"><span class="notice-icon"><Layers3 :size="16" /></span><div><strong>{{ layers ? '图层清单已就绪' : '专题图层尚未发布' }}</strong><small>{{ layers ? '当前批次图层按接口清单加载' : '当前显示区位底图，非研究区边界或分类结果' }}</small></div><span class="notice-version">{{ release.manifest?.run_id || 'NO RELEASE' }}</span></div>
      </section>
      <aside class="layer-drawer">
        <div class="drawer-heading"><div><span class="section-kicker">地图内容</span><h2>图层控制</h2></div><button class="icon-button" title="图层筛选" aria-label="图层筛选"><SlidersHorizontal :size="16" /></button></div>
        <div class="drawer-group"><span class="drawer-group-title">基础图层</span>
          <div class="layer-row"><span class="layer-swatch basemap-swatch"><MapIcon :size="14" /></span><span class="layer-name"><b>区位底图</b><small>OpenStreetMap</small></span><span class="layer-active">底图</span></div>
        </div>
        <div class="drawer-group"><span class="drawer-group-title">研究成果</span>
          <button class="layer-row layer-toggle" @click="toggle('boundary')"><span class="layer-swatch boundary-swatch"></span><span class="layer-name"><b>研究区边界</b><small>2021 统一边界</small></span><component :is="visible.boundary ? Eye : EyeOff" :size="16" class="toggle-eye" /></button>
          <button class="layer-row layer-toggle" @click="toggle('classification')"><span class="layer-swatch class-swatch"></span><span class="layer-name"><b>{{ selectedYear || 2021 }} 年分类图</b><small>四类 · 30 m</small></span><component :is="visible.classification ? Eye : EyeOff" :size="16" class="toggle-eye" /></button>
          <button class="layer-row layer-toggle" @click="toggle('change')"><span class="layer-swatch change-swatch"></span><span class="layer-name"><b>建设变化图</b><small>共同有效网格</small></span><component :is="visible.change ? Eye : EyeOff" :size="16" class="toggle-eye" /></button>
          <p class="drawer-empty">图层可见性为界面预览。发布清单就绪后将读取批次内真实图层。</p>
        </div>
        <div class="legend-box"><span class="drawer-group-title">分类图例 · {{ selectedYear || '变化' }}</span><template v-if="selectedYear !== 0"><div class="legend-row"><i class="legend-color urban"></i><span>城镇及建设用地</span><em>01</em></div><div class="legend-row"><i class="legend-color crop"></i><span>耕地</span><em>02</em></div><div class="legend-row"><i class="legend-color vegetation"></i><span>林草植被</span><em>03</em></div><div class="legend-row"><i class="legend-color water"></i><span>水体</span><em>04</em></div></template><template v-else><div class="legend-row"><i class="legend-color urban"></i><span>持续建设</span><em>01</em></div><div class="legend-row"><i class="legend-color added"></i><span>新增建设</span><em>02</em></div><div class="legend-row"><i class="legend-color lost"></i><span>减少建设</span><em>03</em></div><div class="legend-row"><i class="legend-color stable"></i><span>持续非建设</span><em>04</em></div></template><small class="legend-unavailable">接口默认图例 · 图层未加载</small></div>
        <div class="drawer-bottom"><span>坐标显示</span><strong>WGS 84 · EPSG:4326</strong></div>
      </aside>
    </div>
  </div>
</template>
