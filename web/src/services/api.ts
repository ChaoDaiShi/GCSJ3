import type { ApiEnvelope, Manifest } from '../types/api'

const STORAGE_KEY = 'xindu-api-base'
const DEFAULT_BASE = `${window.location.origin}/api/v1/`

export function getApiBase() {
  const saved = localStorage.getItem(STORAGE_KEY)
  return normalizeBase(saved || DEFAULT_BASE)
}

export function setApiBase(value: string) {
  const base = normalizeBase(value)
  localStorage.setItem(STORAGE_KEY, base)
  return base
}

function normalizeBase(value: string) {
  const trimmed = value.trim()
  if (!trimmed) throw new Error('请输入 API 基地址')
  const url = new URL(trimmed, window.location.origin)
  url.pathname = `${url.pathname.replace(/\/+$/, '')}/`
  return url.toString()
}

export async function getManifest(signal?: AbortSignal): Promise<Manifest> {
  return getJson<Manifest>('manifest.json', signal, true)
}

export async function getResource<T>(path: string, signal?: AbortSignal): Promise<T> {
  return getResourceEnvelope<T>(path, signal).then((response) => response.data)
}

export async function getResourceEnvelope<T>(path: string, signal?: AbortSignal): Promise<ApiEnvelope<T>> {
  return getJson<ApiEnvelope<T>>(path, signal)
}

async function getJson<T>(path: string, signal?: AbortSignal, root = false): Promise<T> {
  const base = getApiBase()
  const url = root ? new URL(path, base) : new URL(path.replace(/^\/+/, ''), base)
  const response = await fetch(url, {
    headers: { Accept: 'application/json' },
    signal,
  })
  if (!response.ok) {
    const error = new Error(`HTTP ${response.status}`)
    Object.assign(error, { status: response.status })
    throw error
  }
  return response.json() as Promise<T>
}
