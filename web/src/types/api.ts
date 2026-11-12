export type ResourceRef = {
  status: 'ready' | 'not_available'
  path: string | null
  reason: 'missing_input' | 'not_computed' | 'not_verified' | null
}

export type Manifest = {
  contract_version: string
  profile: string
  project_id: string
  project_name: string
  years: [number, number]
  boundary_year: number
  expected_township_count: number
  release_state: 'not_published' | 'published'
  run_id: string | null
  published_at: string | null
  data_origin: 'observed' | 'mock' | null
  resources: Record<string, ResourceRef>
}

export type ApiEnvelope<T> = {
  run_id: string
  data: T
}

export type ExpansionRow = {
  unit_id: string
  name: string
  unit_type: 'district' | 'street' | 'town'
  total_area_km2: number
  comparable_area_km2: number
  valid_ratio: number
  added_km2: number | null
  lost_km2: number | null
  net_km2: number | null
  annual_intensity_pct: number | null
}

export type ExpansionData = {
  elapsed_years: number
  district: ExpansionRow
  townships: ExpansionRow[]
}

export type MethodId = 'baseline' | 'optimized'

export type MethodAccuracy = {
  year: number
  holdout_sha256: string
  oa: number | null
  kappa: number | null
  built_up_f1: number | null
  confusion: number[][] | null
}

export type MethodResult = {
  id: MethodId
  model_name: string
  class_schema: string
  classes: { code: number; name: string; color: string }[]
  years: [number, number]
  boundary_sha256: string
  grid_sha256: string
  comparison_mask_sha256: string
  accuracy: MethodAccuracy[]
  expansion: ExpansionData | null
  maps: { year: number; path: string; legend: { name: string; color: string }[] }[]
  drivers: { name: string; q: number; p_value: number | null }[]
}

export type MethodComparisonData = {
  methods: MethodResult[]
}
