<script setup lang="ts">
import { computed } from 'vue'
import { Download, FileImage, FileSpreadsheet, FileText, PackageOpen, RefreshCw } from '@lucide/vue'
import { useReleaseStore } from '../stores/release'

const release = useReleaseStore()
const ready = computed(() => release.manifest?.resources?.artifacts?.status === 'ready')
const groups = [
  { title: '专题图件', icon: FileImage, ids: ['fig01_features', 'fig02_ablation', 'fig03_landuse_transitions', 'fig04_township_centroids', 'fig05_terrain_flood', 'fig06_drivers'] },
  { title: '分析主表', icon: FileSpreadsheet, ids: ['table01_accuracy', 'table02_township_expansion', 'table03_drivers'] },
  { title: '空间数据与报告', icon: FileText, ids: ['raster', 'vector_archive', 'report', 'dem'] },
]
</script>

<template>
  <div class="page-wrap results-page">
    <div class="analysis-header"><div><div class="eyebrow"><span class="eyebrow-line"></span>项目成果 / 文件目录</div><h1>成果中心</h1><p class="page-subtitle">专题图、汇总表、栅格数据与来源记录统一归档于同一发布批次。</p></div><button class="outline-button" @click="release.refresh()"><RefreshCw :size="15" />刷新清单</button></div>
    <div class="results-toolbar"><span>{{ release.manifest?.run_id || '尚无发布批次' }}</span><span class="results-count">{{ ready ? '成果索引已就绪' : '0 项可下载' }}</span></div>
    <section v-for="group in groups" :key="group.title" class="artifact-group">
      <div class="artifact-heading"><component :is="group.icon" :size="17" /><h2>{{ group.title }}</h2><span>{{ group.ids.length.toString().padStart(2, '0') }}</span></div>
      <div class="artifact-list"><div v-for="(id, index) in group.ids" :key="id" class="artifact-row"><span class="artifact-index">{{ String(index + 1).padStart(2, '0') }}</span><div class="artifact-info"><b>{{ id.startsWith('fig') ? `专题图 ${id.slice(3, 5)}` : id.startsWith('table') ? `主表 ${id.slice(5, 7)}` : ({ raster: '分类与变化 GeoTIFF', vector_archive: '矢量数据包', report: '综合分析报告', dem: '数字高程模型' } as Record<string, string>)[id] }}</b><small>{{ id }}</small></div><span class="artifact-pending">待发布</span><button class="icon-button" title="下载不可用" aria-label="下载不可用" disabled><Download :size="16" /></button></div></div>
    </section>
    <div class="artifact-note"><PackageOpen :size="17" /><span>成果文件由离线分析流程生成。此处仅展示发布索引中已核验的文件，不会将示例数据作为正式成果提供。</span></div>
    <footer class="page-footer"><span>成果目录依据 artifacts.json</span><span>文件路径由发布清单提供</span></footer>
  </div>
</template>
