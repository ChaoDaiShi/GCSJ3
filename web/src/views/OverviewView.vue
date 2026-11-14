<script setup lang="ts">
import { computed } from 'vue'
import { RouterLink } from 'vue-router'
import { ArrowDownRight, ArrowRight, ArrowUpRight, CalendarDays, Check, Clock3, Database, Focus, GitCompareArrows, Layers3, Radio, ScanLine, ShieldAlert } from '@lucide/vue'
import MapCanvas from '../components/MapCanvas.vue'
import { useReleaseStore } from '../stores/release'

const release = useReleaseStore()
const manifest = computed(() => release.manifest)
const published = computed(() => manifest.value?.release_state === 'published')
const district = computed(() => manifest.value?.resources?.expansion?.status === 'ready')
</script>

<template>
  <div class="page-wrap overview-page">
    <section class="welcome-row">
      <div>
        <div class="eyebrow"><span class="eyebrow-line"></span>遥感分类 · 城市扩张 · 空间决策</div>
        <h1>成都市新都区 <span>1992 — 2021</span></h1>
        <p class="page-subtitle">基于多期遥感影像的土地覆被分类与城市扩张分析</p>
      </div>
      <div class="welcome-actions">
        <span class="period-label"><CalendarDays :size="15" /> 29 年观测跨度</span>
        <RouterLink to="/comparison" class="primary-button"><GitCompareArrows :size="16" />对比两种方式<ArrowRight :size="15" /></RouterLink>
      </div>
    </section>

    <section class="metric-strip" aria-label="项目核心指标">
      <article class="metric-cell">
        <div class="metric-top"><span>研究周期</span><CalendarDays :size="16" /></div>
        <strong>1992 <i>—</i> 2021</strong><small>两期遥感观测</small>
      </article>
      <article class="metric-cell">
        <div class="metric-top"><span>分析方案</span><Layers3 :size="16" /></div>
        <strong>原有 <i>+</i> 增强</strong><small>保留五类 RF · 独立对照文档方案</small>
      </article>
      <article class="metric-cell">
        <div class="metric-top"><span>统计单元</span><Focus :size="16" /></div>
        <strong>9 <i>个</i>街镇</strong><small>统一采用 2021 年边界</small>
      </article>
      <article class="metric-cell metric-state">
        <div class="metric-top"><span>成果状态</span><Radio :size="16" /></div>
        <strong>{{ published ? '已发布' : '待发布' }}</strong>
        <small>{{ manifest?.run_id || '等待双方案成果批次' }}</small>
      </article>
    </section>

    <section class="workspace-grid">
      <article class="map-panel">
        <div class="panel-heading map-heading">
          <div><div class="section-kicker">空间总览 <span>01 / MAP</span></div><h2>研究区与底图</h2></div>
          <RouterLink to="/map" class="text-link">进入地图 <ArrowRight :size="14" /></RouterLink>
        </div>
        <div class="map-frame"><MapCanvas compact /></div>
        <div class="map-caption">
          <div class="map-caption-label"><span class="map-caption-dot"></span><span>成都市新都区</span><small>范围示意底图</small></div>
          <span class="map-caption-note">行政边界待正式成果发布</span>
        </div>
      </article>

      <article class="release-panel">
        <div class="panel-heading"><div><div class="section-kicker">批次状态 <span>02 / RELEASE</span></div><h2>成果发布清单</h2></div><button class="icon-button" title="刷新发布清单" aria-label="刷新发布清单" @click="release.refresh()"><ScanLine :size="17" /></button></div>
        <div v-if="published" class="published-state">
          <div class="published-icon"><Check :size="19" /></div><strong>{{ manifest?.data_origin === 'mock' ? '联调示例批次' : '真实成果批次' }}</strong>
          <span class="run-id">{{ manifest?.run_id }}</span>
          <div class="release-detail"><span>发布于</span><b>{{ manifest?.published_at ? new Date(manifest.published_at).toLocaleDateString('zh-CN') : '—' }}</b></div>
          <div class="release-detail"><span>可用资源</span><b>{{ Object.values(manifest?.resources || {}).filter((r) => r.status === 'ready').length }} 项</b></div>
          <div v-if="manifest?.data_origin === 'mock'" class="mock-notice"><ShieldAlert :size="15" /> 联调示例数据，不代表研究结论</div>
        </div>
        <div v-else class="empty-release">
          <div class="empty-illustration"><div class="empty-orbit orbit-one"></div><div class="empty-orbit orbit-two"></div><div class="empty-core"><Database :size="21" /></div><span class="orbit-node"></span></div>
          <strong>分析成果尚未发布</strong>
          <p>原有分析与文档方案分别归档，完成独立精度评价后发布对比结果。</p>
          <div class="empty-checks">
            <div><Clock3 :size="14" /><span>发布批次</span><i>待生成</i></div>
            <div><Clock3 :size="14" /><span>街镇统计</span><i>待核验</i></div>
            <div><Clock3 :size="14" /><span>专题成果</span><i>待核验</i></div>
          </div>
        </div>
      </article>

      <article class="analysis-panel">
        <div class="panel-heading"><div><div class="section-kicker">扩张速览 <span>03 / CHANGE</span></div><h2>建设用地变化</h2></div><RouterLink to="/expansion" class="icon-button" title="查看扩张分析" aria-label="查看扩张分析"><ArrowRight :size="17" /></RouterLink></div>
        <div class="chart-placeholder">
          <div class="chart-y" aria-hidden="true"></div>
          <div class="chart-main">
            <div class="chart-gridline grid-top"></div><div class="chart-gridline grid-mid"></div><div class="chart-gridline grid-bottom"></div>
            <div class="chart-empty"><span class="chart-empty-symbol">--</span><span>等待街镇扩张统计</span></div>
            <div class="chart-x"><span>1992</span><span>2021</span></div>
          </div>
        </div>
        <div class="analysis-foot"><span>区级净增</span><strong>{{ district ? '读取中' : '—' }} <small>km²</small></strong><span class="foot-state"><ArrowUpRight :size="13" />待数据发布</span></div>
      </article>

      <article class="timeline-panel">
        <div class="panel-heading"><div><div class="section-kicker">研究设计 <span>04 / METHOD</span></div><h2>分析流程</h2></div><span class="year-tag">2021 边界基准</span></div>
        <div class="method-steps">
          <div class="method-step"><span class="step-index">01</span><span class="step-line"></span><div><strong>共同输入与独立留出</strong><small>同年份 · 同网格 · 冻结样本</small></div><span class="step-state">共同口径</span></div>
          <div class="method-step"><span class="step-index">02</span><span class="step-line"></span><div><strong>两套分类流程</strong><small>原有五类 RF · OBIA-Stacking 方案</small></div><span class="step-state">独立保留</span></div>
          <div class="method-step"><span class="step-index">03</span><span class="step-line"></span><div><strong>精度与变化评价</strong><small>独立留出 · 共同有效网格</small></div><span class="step-state">待核验</span></div>
          <div class="method-step"><span class="step-index">04</span><span class="step-line"></span><div><strong>统计与解释对照</strong><small>街镇扩张 · 地形交通 · 驱动因子</small></div><span class="step-state">待发布</span></div>
        </div>
        <div class="timeline-foot"><span><ArrowDownRight :size="14" />数据口径以发布批次来源记录为准</span><RouterLink to="/results">查看成果规范 <ArrowRight :size="13" /></RouterLink></div>
      </article>
    </section>

    <footer class="page-footer"><span>新都区遥感分类与城市扩张分析</span><span>研究展示平台 <i>·</i> API 契约 v1.0.0</span></footer>
  </div>
</template>
