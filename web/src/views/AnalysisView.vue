<script setup lang="ts">
import { computed, ref, watch } from 'vue'
import { useRoute } from 'vue-router'
import { ArrowRight, Database, FileWarning } from '@lucide/vue'
import { useReleaseStore } from '../stores/release'
import { getResource } from '../services/api'

const route = useRoute()
const release = useReleaseStore()
const resource = computed(() => String(route.meta.resource || ''))
const refData = computed(() => release.manifest?.resources?.[resource.value])
const ready = computed(() => refData.value?.status === 'ready')
const data = ref<Record<string, unknown> | null>(null)
const loading = ref(false)
const resourceError = ref<string | null>(null)
const expansionRows = computed(() => Array.isArray(data.value?.townships) ? data.value.townships as Record<string, unknown>[] : [])
const dataKeys = computed(() => data.value ? Object.keys(data.value) : [])
let controller: AbortController | undefined

watch([resource, () => refData.value?.path, ready], async () => {
  await loadResource()
}, { immediate: true })

async function loadResource() {
  controller?.abort()
  data.value = null
  resourceError.value = null
  if (!ready.value || !refData.value?.path) return
  controller = new AbortController()
  loading.value = true
  try {
    data.value = await getResource<Record<string, unknown>>(refData.value.path, controller.signal)
  } catch (cause) {
    if ((cause as Error).name === 'AbortError') return
    resourceError.value = (cause as { status?: number }).status === 404
      ? '成果文件缺失：发布清单标记为 ready，但对应文件返回 404。'
      : '读取成果文件失败，请检查服务状态或资源路径。'
  } finally {
    loading.value = false
  }
}

async function refreshResource() {
  await release.refresh()
  await loadResource()
}

const descriptions: Record<string, string> = {
  expansion: '比较区级与九街镇 1992—2021 年建设用地面积、净变化与年均扩张强度。',
  accuracy: '查看独立留出集评价、混淆矩阵与 SVM、随机森林、OBIA-Stacking 模型对照。',
  transitions: '追踪四类地物在共同有效范围内的面积转移与街镇差异。',
  drivers: '浏览地形、交通、水系与政策因子的地理探测器 q 值和交互结果。',
  terrain: '分析新增建设的地形梯度分布、水系缓冲区暴露与高程重心。',
  landscape: '查看耕地转出、农田参考范围与景观斑块格局变化。',
  policies: '沿政策时间轴检查规划事件及功能区空间叠加统计。',
}
const title = computed(() => String(route.meta.title || '专题分析'))
const formatNumber = (value: unknown, digits = 2) => typeof value === 'number' ? value.toFixed(digits) : '—'
</script>

<template>
  <div class="page-wrap analysis-page">
    <div class="analysis-header"><div><div class="eyebrow"><span class="eyebrow-line"></span>{{ route.meta.section }} / 研究分析</div><h1>{{ title }}</h1><p class="page-subtitle">{{ descriptions[resource] }}</p></div><div class="analysis-batch"><span class="status-led" :class="{ 'status-led-on': ready }"></span><span>{{ release.manifest?.run_id || '等待成果批次' }}</span></div></div>
    <div class="analysis-tabs"><span class="tab-active">{{ title }}</span><span>1992 — 2021</span><span>2021 统一边界</span></div>
    <section v-if="ready && data" class="analysis-data">
      <div class="data-toolbar"><div><span class="data-live"></span><span>资源读取成功</span><code>{{ refData?.path }}</code></div><span class="data-run">{{ release.manifest?.run_id }}</span></div>
      <template v-if="resource === 'expansion'">
        <div class="data-summary">
          <div><span>统计周期</span><strong>{{ data.elapsed_years || 29 }}<small> 年</small></strong></div>
          <div><span>街镇单元</span><strong>{{ expansionRows.length }}<small> 个</small></strong></div>
          <div><span>区级净变化</span><strong>{{ formatNumber((data.district as Record<string, unknown> | undefined)?.net_km2) }}<small> km²</small></strong></div>
          <div><span>年度扩张强度</span><strong>{{ formatNumber((data.district as Record<string, unknown> | undefined)?.annual_intensity_pct, 3) }}<small> %/年</small></strong></div>
        </div>
        <div class="data-table-wrap"><table class="data-table"><thead><tr><th>统计单元</th><th>辖区面积 km²</th><th>可比面积 km²</th><th>有效覆盖</th><th>新增 km²</th><th>净变化 km²</th><th>年均强度 %</th></tr></thead><tbody>
          <tr v-for="row in [data.district as Record<string, unknown>, ...expansionRows]" :key="String(row.unit_id)"><td><b>{{ row.name }}</b><small>{{ row.unit_type === 'district' ? '区级汇总' : row.unit_type }}</small></td><td>{{ formatNumber(row.total_area_km2) }}</td><td>{{ formatNumber(row.comparable_area_km2) }}</td><td>{{ typeof row.valid_ratio === 'number' ? `${(row.valid_ratio * 100).toFixed(1)}%` : '—' }}</td><td>{{ formatNumber(row.added_km2) }}</td><td :class="{ 'positive-value': typeof row.net_km2 === 'number' && row.net_km2 > 0, 'negative-value': typeof row.net_km2 === 'number' && row.net_km2 < 0 }">{{ formatNumber(row.net_km2) }}</td><td>{{ formatNumber(row.annual_intensity_pct, 3) }}</td></tr>
        </tbody></table></div>
      </template>
      <template v-else>
        <div class="generic-data-head"><div class="empty-file-icon"><Database :size="22" /></div><span class="section-kicker">{{ resource }}.json</span><h2>{{ title }}资源已加载</h2><p>此批次数据包含 {{ dataKeys.length }} 个顶层字段。</p></div>
        <div class="data-key-grid"><div v-for="key in dataKeys" :key="key"><span>{{ key }}</span><b>{{ Array.isArray(data?.[key]) ? `${(data?.[key] as unknown[]).length} 条记录` : typeof data?.[key] === 'object' && data?.[key] ? '结构化对象' : String(data?.[key] ?? '—') }}</b></div></div>
      </template>
    </section>
    <section v-else class="analysis-empty">
      <div class="empty-grid"><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i><i></i></div>
      <div class="empty-content">
        <div class="empty-file-icon"><component :is="ready ? Database : FileWarning" :size="23" /></div>
        <span class="section-kicker">{{ resource }}.json</span>
        <h2>{{ loading ? '正在读取资源…' : resourceError ? '成果文件不可用' : refData?.status === 'not_available' ? '此项成果暂不可用' : ready ? '等待资源加载' : '等待分析成果发布' }}</h2>
        <p>{{ resourceError || (refData?.status === 'not_available' ? '离线流程未发布此项资源，具体原因见下方。' : '此模块已接入发布清单。对应资源就绪后，页面将按当前 run_id 读取。') }}</p>
        <div class="empty-resource"><span>资源状态</span><b>{{ resourceError ? '文件缺失或读取失败' : refData?.status === 'not_available' ? '暂不可用' : ready ? '正在读取' : '尚无发布清单' }}</b><small>{{ refData?.reason || (ready ? refData?.path : '需要可访问的 manifest.json') }}</small></div>
        <button class="outline-button" @click="refreshResource">刷新发布状态 <ArrowRight :size="14" /></button>
      </div>
    </section>
    <footer class="page-footer"><span>指标与评价结果由离线流程生成</span><span>浏览器仅负责读取、筛选与展示</span></footer>
  </div>
</template>
