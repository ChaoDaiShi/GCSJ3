import { defineStore } from 'pinia'
import { ref } from 'vue'
import { getApiBase, getManifest, setApiBase } from '../services/api'
import type { Manifest } from '../types/api'

export const useReleaseStore = defineStore('release', () => {
  const manifest = ref<Manifest | null>(null)
  const apiBase = ref(getApiBase())
  const loading = ref(false)
  const error = ref<string | null>(null)
  const checkedAt = ref<Date | null>(null)

  async function refresh() {
    loading.value = true
    error.value = null
    try {
      manifest.value = await getManifest()
      checkedAt.value = new Date()
    } catch (cause) {
      manifest.value = null
      const status = (cause as { status?: number }).status
      error.value = status === 404
        ? '未找到发布清单，请检查后端是否已提供 /api/v1/manifest.json。'
        : '暂时无法连接发布接口，请确认 API 地址和服务状态。'
    } finally {
      loading.value = false
    }
  }

  function updateApiBase(value: string) {
    apiBase.value = setApiBase(value)
  }

  return { manifest, apiBase, loading, error, checkedAt, refresh, updateApiBase }
})
