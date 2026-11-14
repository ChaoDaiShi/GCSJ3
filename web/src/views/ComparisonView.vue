<script setup lang="ts">
import { computed, onBeforeUnmount, ref, watch } from 'vue'
import { ArrowRight, ChartNoAxesCombined, Check, Download, GitCompareArrows, RefreshCw } from '@lucide/vue'
import { getResourceEnvelope } from '../services/api'
import { accuracyComparable, comparisonIssues, difference } from '../services/comparison'
import { useReleaseStore } from '../stores/release'
import type { MethodComparisonData, MethodId, MethodResult } from '../types/api'

const release = useReleaseStore()
const tabs = [
  { id: 'workflow', label: '分析方式' },
  { id: 'accuracy', label: '分类精度' },
  { id: 'expansion', label: '街镇扩张' },
  { id: 'maps', label: '分类图对照' },
  { id: 'drivers', label: '驱动因素' },
] as const
const activeTab = ref<typeof tabs[number]['id']>('workflow')
const year = ref(2021)
const metric = ref<'net_km2' | 'added_km2' | 'annual_intensity_pct'>('net_km2')
const data = ref<MethodComparisonData | null>(null)
const loading = ref(false)
const error = ref<string | null>(null)
const mapErrors = ref<string[]>([])
const resource = computed(() => release.manifest?.resources.method_comparison)
const baseline = computed(() => data.value?.methods.find((method) => method.id === 'baseline'))
const optimized = computed(() => data.value?.methods.find((method) => method.id === 'optimized'))
const issues = computed(() => baseline.value && optimized.value ? comparisonIssues(baseline.value, optimized.value) : [])
const comparable = computed(() => !!baseline.value && !!optimized.value && issues.value.length === 0)
const canCompareAccuracy = computed(() => baseline.value && optimized.value
  ? accuracyComparable(baseline.value, optimized.value, year.value) : false)
const years = computed(() => release.manifest?.years || [1992, 2021])
const selectedMethods = computed(() => [baseline.value, optimized.value])
const profiles = [
  { id: 'baseline' as const, label: '原有分析', model: '随机森林 RF', detail: '光谱指数分类与街镇扩张统计', tag: '保留原流程' },
  { id: 'optimized' as const, label: '文档方案', model: 'OBIA + Stacking', detail: '特征增强、集成分类与多维空间分析', tag: '独立对照方案' },
]
const steps = [
  { label: '特征构建', baseline: '6 个反射率波段 + NDVI、NDBI、MNDWI、BSI，共 10 维', optimized: '在原有特征上增加 UI、SAVI 与 5×5 GLCM 纹理，记录实际特征维数' },
  { label: '分类模型', baseline: '分年份训练随机森林，按像元分类', optimized: '对象分割与 RF、LightGBM、CatBoost 集成，使用逻辑回归融合' },
  { label: '空间后处理', baseline: 'GDAL Sieve 去除小斑块，保留原始与最终分类', optimized: '按实验配置执行空间平滑，并分别评价处理前后结果' },
  { label: '扩张统计', baseline: '共同有效范围内的新增、减少、净变化与年均强度', optimized: '保留同口径统计，增加填充式、边缘式、飞地式扩张与景观指标' },
  { label: '空间解释', baseline: '比较区级与九街镇的面积和扩张强度', optimized: '叠加地形、水系、交通和规划因子，计算 GeoDetector q 值与交互作用' },
]
let controller: AbortController | undefined

watch(() => [release.apiBase, release.manifest?.run_id, release.manifest?.release_state, resource.value], () => load(), { immediate: true })
watch(year, () => { mapErrors.value = [] })
onBeforeUnmount(() => controller?.abort())

async function load() {
  controller?.abort()
  data.value = null
  error.value = null
  loading.value = false
  mapErrors.value = []
  const manifest = release.manifest
  if (manifest?.release_state !== 'published' || resource.value?.status !== 'ready' || !resource.value.path) return
  const request = new AbortController()
  controller = request
  loading.value = true
  try {
    const response = await getResourceEnvelope<MethodComparisonData>(resource.value.path, request.signal)
    if (request.signal.aborted) return
    if (response.run_id !== manifest.run_id) throw new Error('对比成果与当前发布批次不一致，请重新发布同一批次的结果。')
    data.value = response.data
  } catch (cause) {
    if (request.signal.aborted) return
    error.value = (cause as { status?: number }).status === 404
      ? '对比成果文件缺失，请检查当前批次的发布文件。'
      : (cause as Error).message
  } finally {
    if (controller === request) loading.value = false
  }
}

function result(id: MethodId) { return id === 'baseline' ? baseline.value : optimized.value }
function accuracy(method: MethodResult | undefined) { return method?.accuracy.find((item) => item.year === year.value) }
function classificationMap(method: MethodResult | undefined) { return method?.maps.find((item) => item.year === year.value) }
function number(value: number | null | undefined, digits = 2) { return typeof value === 'number' ? value.toFixed(digits) : '—' }
function percent(value: number | null | undefined) { return typeof value === 'number' ? `${(value * 100).toFixed(2)}%` : '—' }
function delta(value: number | null, digits = 2) { return value === null ? '—' : `${value > 0 ? '+' : ''}${value.toFixed(digits)}` }
function accuracyDelta(key: 'oa' | 'kappa' | 'built_up_f1', asPercent: boolean) {
  if (!canCompareAccuracy.value) return '待统一评价'
  const value = difference(accuracy(baseline.value)?.[key], accuracy(optimized.value)?.[key])
  return delta(value === null ? null : value * (asPercent ? 100 : 1), asPercent ? 2 : 3)
}
function assetUrl(path: string) { return new URL(path.replace(/^\/+/, ''), release.apiBase).toString() }
const accuracyMetrics = [
  { key: 'oa', label: '总体精度 OA', percent: true },
  { key: 'built_up_f1', label: '建设用地 F1', percent: false },
  { key: 'kappa', label: 'Kappa 系数', percent: false },
] as const
const townshipRows = computed(() => {
  const a = baseline.value?.expansion?.townships || []
  const b = optimized.value?.expansion?.townships || []
  return [...new Set([...a.map((row) => row.unit_id), ...b.map((row) => row.unit_id)])].map((id) => {
    const original = a.find((row) => row.unit_id === id)
    const improved = b.find((row) => row.unit_id === id)
    return { id, name: original?.name || improved?.name, a: original?.[metric.value], b: improved?.[metric.value] }
  })
})
const expansionComparable = computed(() => comparable.value
  && !!baseline.value?.expansion && !!optimized.value?.expansion
  && baseline.value.expansion.elapsed_years === optimized.value.expansion.elapsed_years)
const chartMaximum = computed(() => Math.max(0.001, ...townshipRows.value.flatMap((row) => [Math.abs(row.a ?? 0), Math.abs(row.b ?? 0)])))
const unit = computed(() => metric.value === 'annual_intensity_pct' ? '%/年' : 'km²')
const drivers = computed(() => [...(optimized.value?.drivers || [])].sort((a, b) => b.q - a.q))
const readyCount = computed(() => [baseline.value, optimized.value].filter(Boolean).length)
const emptyMessage = computed(() => {
  if (loading.value) return '正在读取本批次对比成果'
  if (error.value) return error.value
  if (resource.value?.reason === 'missing_input') return '对比所需的影像、样本或辅助因子尚未齐备'
  if (resource.value?.reason === 'not_verified') return '对比成果尚未完成核验'
  if (readyCount.value === 1) return '当前仅发布一套方案，另一套方案的指标保留为空'
  return '两套方案的对比成果尚未发布'
})

function exportCsv() {
  const records = [['统计单元', `原有分析 ${unit.value}`, `文档方案 ${unit.value}`, `差值 ${unit.value}`],
    ...townshipRows.value.map((row) => [row.name || row.id, row.a ?? '', row.b ?? '',
      expansionComparable.value ? difference(row.a, row.b) ?? '' : '口径未统一'])]
  const csv = '\uFEFF' + records.map((row) => row.map((cell) => `"${String(cell).replace(/"/g, '""')}"`).join(',')).join('\r\n')
  const url = URL.createObjectURL(new Blob([csv], { type: 'text/csv;charset=utf-8;' }))
  const anchor = document.createElement('a')
  anchor.href = url
  anchor.download = `method-comparison-${release.manifest?.run_id}-${metric.value}.csv`
  anchor.click()
  URL.revokeObjectURL(url)
}
</script>

<template>
  <div class="page-wrap comparison-page">
    <header class="analysis-header">
      <div><div class="eyebrow"><span class="eyebrow-line"></span>研究分析 / 双方案对照</div><h1>两种分析方式对比</h1><p class="page-subtitle">原有随机森林与街镇统计 · 文档提出的特征增强与多维空间分析</p></div>
      <button class="outline-button" :disabled="loading || release.loading" @click="release.refresh()"><RefreshCw :size="14" :class="{ spinning: loading || release.loading }" />刷新成果</button>
    </header>

    <div v-if="release.manifest?.data_origin === 'mock'" class="comparison-notice">当前为联调示例数据，不代表真实研究结论。</div>
    <div class="comparison-context"><span>{{ years.join(' — ') }}</span><span>{{ release.manifest?.boundary_year || 2021 }} 统一边界</span><span>30 m 定量网格</span><span>{{ readyCount }}/2 套成果就绪</span></div>

    <div class="method-pair">
      <article v-for="profile in profiles" :key="profile.id" class="method-profile" :class="profile.id">
        <div class="method-profile-top"><span class="method-marker">{{ profile.id === 'baseline' ? 'A' : 'B' }}</span><strong>{{ profile.label }}</strong><span class="method-tag">{{ profile.tag }}</span></div>
        <h2>{{ result(profile.id)?.model_name || profile.model }}</h2>
        <p>{{ profile.detail }}</p>
        <div class="method-profile-foot"><span>{{ result(profile.id) ? `${result(profile.id)!.classes.length} 类地物` : profile.id === 'baseline' ? '原有五类地物' : '地类体系待实验确认' }}</span><span :class="{ 'method-published': result(profile.id) }">{{ result(profile.id) ? '本批次已发布' : '等待真实成果' }}</span></div>
      </article>
    </div>

    <div class="comparison-status" role="status">
      <Check v-if="comparable" :size="16" /><GitCompareArrows v-else :size="16" />
      <span>{{ comparable ? '年份、地类、边界、网格与共同有效范围一致' : readyCount === 2 ? issues.join('；') : emptyMessage }}</span>
      <small v-if="release.manifest?.run_id">{{ release.manifest.run_id }}</small>
    </div>

    <div class="comparison-tabs" role="tablist" aria-label="方法对比专题">
      <button v-for="tab in tabs" :id="`tab-${tab.id}`" :key="tab.id" role="tab" :aria-selected="activeTab === tab.id" :aria-controls="`panel-${tab.id}`" :class="{ active: activeTab === tab.id }" @click="activeTab = tab.id">{{ tab.label }}</button>
    </div>

    <section :id="`panel-${activeTab}`" class="comparison-panel" role="tabpanel" :aria-labelledby="`tab-${activeTab}`">
      <template v-if="activeTab === 'workflow'">
        <div class="comparison-section-heading"><h2>从面积变化到空间解释</h2><span>两套流程独立保留</span></div>
        <div class="workflow-table-wrap"><table class="workflow-table"><thead><tr><th>分析环节</th><th><i class="method-dot baseline"></i>A · 原有分析</th><th><i class="method-dot optimized"></i>B · 文档方案</th></tr></thead>
          <tbody><tr v-for="(step, index) in steps" :key="step.label"><th><small>{{ String(index + 1).padStart(2, '0') }}</small>{{ step.label }}</th><td>{{ step.baseline }}</td><td>{{ step.optimized }}</td></tr></tbody>
        </table></div>
        <div class="comparison-notes"><p><strong>共同评价口径</strong>两套模型需沿用同一冻结的空间分组留出集；增强方案的交叉验证也需按地块分组。</p><p><strong>结果解读</strong>q 值表示空间分异解释力；规划叠加和两期变化不能直接证明因果关系，也不能推算政策前后的速率突变。</p></div>
        <button class="text-link comparison-next" @click="activeTab = 'accuracy'">查看分类精度对照 <ArrowRight :size="14" /></button>
      </template>

      <template v-else-if="activeTab === 'accuracy'">
        <div class="comparison-section-heading"><h2>独立留出集评价</h2><div class="segmented" aria-label="评价年份"><button v-for="item in years" :key="item" :class="{ selected: year === item }" :aria-pressed="year === item" @click="year = item">{{ item }}</button></div></div>
        <p class="comparison-caption">{{ canCompareAccuracy ? '当前年份使用同一留出集，差值为文档方案减原有分析。' : '留出集和地类体系一致后显示精度差值。' }}</p>
        <div class="accuracy-comparison"><article v-for="item in accuracyMetrics" :key="item.key">
          <h3>{{ item.label }}</h3>
          <div v-for="(method, index) in selectedMethods" :key="index" class="accuracy-value"><span><i class="method-dot" :class="profiles[index]!.id"></i>{{ profiles[index]!.label }}</span><strong>{{ item.percent ? percent(accuracy(method)?.[item.key]) : number(accuracy(method)?.[item.key], 3) }}</strong></div>
          <div class="accuracy-delta"><span>{{ item.percent ? '差值 / 百分点' : '差值' }}</span><b>{{ accuracyDelta(item.key, item.percent) }}</b></div>
        </article></div>
        <div class="confusion-pair"><article v-for="profile in profiles" :key="profile.id"><h3>{{ profile.label }} · 混淆矩阵</h3>
          <div v-if="accuracy(result(profile.id))?.confusion" class="data-table-wrap"><table class="confusion-table"><caption>行是真值 · 列是预测</caption><thead><tr><th>真值 / 预测</th><th v-for="cls in result(profile.id)!.classes" :key="cls.code">{{ cls.name }}</th></tr></thead><tbody><tr v-for="(row, index) in accuracy(result(profile.id))!.confusion!" :key="index"><th>{{ result(profile.id)!.classes[index]?.name }}</th><td v-for="(count, column) in row" :key="column" :class="{ diagonal: index === column }">{{ count }}</td></tr></tbody></table></div>
          <p v-else class="comparison-placeholder">当前年份的混淆矩阵尚未发布</p>
        </article></div>
      </template>

      <template v-else-if="activeTab === 'expansion'">
        <div class="comparison-section-heading"><h2>同一街镇的扩张差异</h2><div class="comparison-actions"><select v-model="metric" aria-label="扩张指标"><option value="net_km2">净变化面积</option><option value="added_km2">新增建设面积</option><option value="annual_intensity_pct">年均扩张强度</option></select><button class="icon-button" title="导出对比 CSV" aria-label="导出对比 CSV" :disabled="!townshipRows.length" @click="exportCsv"><Download :size="17" /></button></div></div>
        <div class="comparison-chart-legend"><span><i class="method-dot baseline"></i>原有分析</span><span><i class="method-dot optimized"></i>文档方案</span><span>{{ unit }}</span></div>
        <template v-if="townshipRows.length">
          <div class="township-chart"><div v-for="row in townshipRows" :key="row.id" class="township-chart-row"><strong>{{ row.name }}</strong><div class="paired-bars"><div v-for="(value, index) in [row.a, row.b]" :key="index" class="bar-track"><div class="bar-half negative"><i v-if="typeof value === 'number' && value < 0" :class="profiles[index]!.id" :style="{ width: `${Math.abs(value) / chartMaximum * 100}%` }"></i></div><div class="bar-half positive"><i v-if="typeof value === 'number' && value >= 0" :class="profiles[index]!.id" :style="{ width: `${value / chartMaximum * 100}%` }"></i></div></div></div><span>{{ number(row.a) }} / {{ number(row.b) }}</span></div></div>
          <div class="data-table-wrap"><table class="data-table comparison-data-table"><thead><tr><th>街镇</th><th>原有分析 {{ unit }}</th><th>文档方案 {{ unit }}</th><th>差值 B − A</th></tr></thead><tbody><tr v-for="row in townshipRows" :key="row.id"><td><b>{{ row.name }}</b></td><td>{{ number(row.a, 3) }}</td><td>{{ number(row.b, 3) }}</td><td>{{ expansionComparable ? delta(difference(row.a, row.b), 3) : '待统一口径' }}</td></tr></tbody></table></div>
        </template>
        <div v-else class="comparison-empty"><ChartNoAxesCombined :size="30" /><h3>街镇对比统计待发布</h3><p>新增、净变化和年均强度均保留为空。</p></div>
        <p class="comparison-caption">差值仅反映两套分析结果的差异，不直接表示哪套结果更准确。{{ expansionComparable ? '' : '统计范围或周期尚未统一，暂不计算差值。' }}</p>
      </template>

      <template v-else-if="activeTab === 'maps'">
        <div class="comparison-section-heading"><h2>同年份分类图</h2><div class="segmented" aria-label="分类图年份"><button v-for="item in years" :key="item" :class="{ selected: year === item }" :aria-pressed="year === item" @click="year = item">{{ item }}</button></div></div>
        <div class="classification-pair"><figure v-for="profile in profiles" :key="profile.id"><figcaption><i class="method-dot" :class="profile.id"></i>{{ profile.label }}<span>{{ year }}</span></figcaption><div class="classification-image">
          <img v-if="classificationMap(result(profile.id)) && !mapErrors.includes(profile.id)" :src="assetUrl(classificationMap(result(profile.id))!.path)" :alt="`${profile.label} ${year} 年土地覆被分类图`" @error="mapErrors.push(profile.id)" />
          <div v-else class="comparison-map-empty"><GitCompareArrows :size="26" /><span>{{ mapErrors.includes(profile.id) ? '分类图读取失败' : '该方案分类图尚未发布' }}</span></div>
        </div><div class="classification-legend"><span v-for="item in classificationMap(result(profile.id))?.legend" :key="item.name"><i :style="{ background: item.color }"></i>{{ item.name }}</span></div></figure></div>
        <p class="comparison-caption">两图按各自发布的地类图例展示。{{ comparable ? '两套成果的分析范围一致。' : '分析口径尚未统一，暂不作像元差异判读。' }}</p>
      </template>

      <template v-else>
        <div class="comparison-section-heading"><h2>空间分异解释力</h2><span>GeoDetector · q ∈ [0, 1]</span></div>
        <div class="driver-comparison"><article><h3><i class="method-dot baseline"></i>原有分析</h3><p>输出区级与街镇扩张面积、年均强度和空间分布。</p><div class="driver-scope">原有流程不计算 q 值</div></article>
          <article><h3><i class="method-dot optimized"></i>文档方案</h3><div v-if="drivers.length" class="driver-bars"><div v-for="factor in drivers" :key="factor.name"><span>{{ factor.name }}</span><div><i :style="{ width: `${factor.q * 100}%` }"></i></div><strong>{{ factor.q.toFixed(3) }}</strong><small>p {{ factor.p_value === null ? '未发布' : `= ${factor.p_value.toFixed(3)}` }}</small></div></div><p v-else class="comparison-placeholder">因子 q 值与显著性结果尚未发布</p></article></div>
        <p class="comparison-caption">q 值表示空间分异解释力，不表示因果效应。辅助数据需核对年份、来源及离散化方式；文档中的示例数值不作为研究结果。</p>
      </template>
    </section>
    <footer class="page-footer"><span>两套分析独立归档 · 同一发布批次对照</span><span>{{ readyCount === 2 ? '保留原结果与增强结果' : emptyMessage }}</span></footer>
  </div>
</template>
