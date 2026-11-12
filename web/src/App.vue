<script setup lang="ts">
import { computed, onMounted, ref } from 'vue'
import { RouterLink, RouterView, useRoute } from 'vue-router'
import {
  Activity, BarChart3, BookOpen, ChevronDown, CircleHelp, Cloud,
  ExternalLink, FileStack, GitCompareArrows, Layers3, Map as MapIcon, Menu, Mountain,
  RefreshCw, Search, Settings2, ShieldCheck,
  Sparkles, Waypoints, X,
} from '@lucide/vue'
import { useReleaseStore } from './stores/release'

const route = useRoute()
const release = useReleaseStore()
const sidebarOpen = ref(false)
const settingsOpen = ref(false)
const apiInput = ref(release.apiBase)
const pageTitle = computed(() => String(route.meta.title || '项目总览'))
const isPublished = computed(() => release.manifest?.release_state === 'published')

const navigation = [
  { label: '项目总览', section: '工作台', to: '/', icon: Activity },
  { label: '方法对比', section: '工作台', to: '/comparison', icon: GitCompareArrows },
  { label: '时空地图', section: '空间分析', to: '/map', icon: MapIcon },
  { label: '街镇扩张', section: '空间分析', to: '/expansion', icon: BarChart3 },
  { label: '分类精度', section: '模型评价', to: '/accuracy', icon: ShieldCheck },
  { label: '地类转移', section: '模型评价', to: '/transitions', icon: Waypoints },
  { label: '驱动因素', section: '专题分析', to: '/drivers', icon: Sparkles },
  { label: '地形与洪涝', section: '专题分析', to: '/terrain', icon: Mountain },
  { label: '耕地与景观', section: '专题分析', to: '/landscape', icon: Layers3 },
  { label: '政策叠加', section: '专题分析', to: '/policies', icon: BookOpen },
  { label: '成果中心', section: '项目成果', to: '/results', icon: FileStack },
]
const sections = [...new Set(navigation.map((item) => item.section))]

function saveSettings() {
  try {
    release.updateApiBase(apiInput.value)
    settingsOpen.value = false
    release.refresh()
  } catch {
    apiInput.value = release.apiBase
  }
}

onMounted(() => release.refresh())
</script>

<template>
  <div class="app-shell">
    <div v-if="sidebarOpen" class="mobile-scrim" @click="sidebarOpen = false"></div>
    <aside class="sidebar" :class="{ 'sidebar-open': sidebarOpen }">
      <RouterLink to="/" class="brand" @click="sidebarOpen = false">
        <span class="brand-mark"><span></span><span></span><span></span><span></span></span>
        <span class="brand-copy"><strong>新都遥感</strong><small>REMOTE SENSING LAB</small></span>
      </RouterLink>

      <div class="project-switcher">
        <div class="project-thumb"><Layers3 :size="18" /></div>
        <div class="project-meta"><strong>城市扩张分析</strong><span>成都市 · 新都区</span></div>
        <ChevronDown :size="15" class="muted-icon" />
      </div>

      <nav class="side-nav" aria-label="主导航">
        <div v-for="section in sections" :key="section" class="nav-group">
          <p class="nav-heading">{{ section }}</p>
          <RouterLink
            v-for="item in navigation.filter((entry) => entry.section === section)"
            :key="item.to"
            :to="item.to"
            class="nav-link"
            :class="{ 'nav-link-active': route.path === item.to }"
            @click="sidebarOpen = false"
          >
            <component :is="item.icon" :size="17" :stroke-width="1.8" />
            <span>{{ item.label }}</span>
            <span v-if="item.to === '/map'" class="nav-live-dot"></span>
          </RouterLink>
        </div>
      </nav>

      <div class="sidebar-bottom">
        <div class="sidebar-status">
          <span class="status-led" :class="{ 'status-led-on': isPublished }"></span>
          <div><strong>{{ isPublished ? '批次已发布' : '等待成果发布' }}</strong><small>{{ release.manifest?.run_id || '原有分析 · 文档方案' }}</small></div>
          <button class="icon-button tiny" title="刷新接口状态" aria-label="刷新接口状态" @click="release.refresh()"><RefreshCw :size="14" :class="{ spinning: release.loading }" /></button>
        </div>
        <button class="nav-link settings-link" @click="settingsOpen = true"><Settings2 :size="17" /><span>接口设置</span></button>
        <div class="sidebar-foot"><span>契约版本 1.0.0</span><CircleHelp :size="14" /></div>
      </div>
    </aside>

    <main class="main-area">
      <header class="topbar">
        <div class="topbar-left">
          <button class="icon-button mobile-menu" title="打开导航" aria-label="打开导航" @click="sidebarOpen = true"><Menu :size="19" /></button>
          <div class="breadcrumbs"><span>新都区遥感分析</span><span class="crumb-slash">/</span><strong>{{ pageTitle }}</strong></div>
        </div>
        <div class="topbar-actions">
          <div class="release-chip" :class="{ 'release-chip-live': isPublished }"><span></span>{{ isPublished ? (release.manifest?.data_origin === 'mock' ? '联调示例' : '真实成果') : '未发布' }}</div>
          <button class="icon-button" title="搜索" aria-label="搜索"><Search :size="18" /></button>
          <span class="topbar-divider"></span>
          <button class="profile-button" title="项目设置" @click="settingsOpen = true"><span class="avatar">RS</span><ChevronDown :size="14" /></button>
        </div>
      </header>

      <div v-if="release.error" class="connection-banner">
        <Cloud :size="16" /><span>{{ release.error }}</span>
        <button @click="release.refresh()">重试</button>
        <button class="banner-close" aria-label="关闭" @click="release.error = null"><X :size="15" /></button>
      </div>
      <RouterView v-slot="{ Component }">
        <Transition name="page" mode="out-in"><component :is="Component" /></Transition>
      </RouterView>
    </main>

    <div v-if="settingsOpen" class="modal-backdrop" @click.self="settingsOpen = false">
      <section class="settings-modal" role="dialog" aria-modal="true" aria-labelledby="settings-title">
        <div class="modal-head"><div><span class="eyebrow">连接配置</span><h2 id="settings-title">接口设置</h2></div><button class="icon-button" aria-label="关闭" @click="settingsOpen = false"><X :size="18" /></button></div>
        <label class="field-label" for="api-base">API 基地址</label>
        <input id="api-base" v-model="apiInput" class="text-input" spellcheck="false" placeholder="http://localhost:8000/api/v1/" @keyup.enter="saveSettings" />
        <p class="field-hint">入口清单固定读取 <code>manifest.json</code>。路径将按接口契约的 `/api/v1/` 相对地址解析。</p>
        <div class="modal-foot"><span class="connection-test"><span class="status-led" :class="{ 'status-led-on': isPublished }"></span>{{ release.checkedAt ? `上次检查 ${release.checkedAt.toLocaleTimeString('zh-CN', { hour: '2-digit', minute: '2-digit' })}` : '尚未检查' }}</span><button class="primary-button" @click="saveSettings"><ExternalLink :size="15" />保存并连接</button></div>
      </section>
    </div>
  </div>
</template>
