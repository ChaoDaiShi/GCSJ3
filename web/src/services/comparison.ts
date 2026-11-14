import type { MethodResult } from '../types/api'

export function comparisonIssues(baseline: MethodResult, optimized: MethodResult): string[] {
  const issues: string[] = []
  if (baseline.years.join() !== optimized.years.join()) issues.push('观测年份不一致')
  if (!baseline.class_schema || baseline.class_schema !== optimized.class_schema
    || baseline.classes.map((item) => item.code).join() !== optimized.classes.map((item) => item.code).join()) {
    issues.push('地类体系不一致')
  }
  const scopes = [
    ['boundary_sha256', '行政边界'],
    ['grid_sha256', '分析网格'],
    ['comparison_mask_sha256', '共同有效范围'],
  ] as const
  for (const [key, label] of scopes) {
    if (!baseline[key] || baseline[key] !== optimized[key]) issues.push(`${label}不一致或未核验`)
  }
  return issues
}

export function accuracyComparable(baseline: MethodResult, optimized: MethodResult, year: number): boolean {
  const a = baseline.accuracy.find((item) => item.year === year)
  const b = optimized.accuracy.find((item) => item.year === year)
  return comparisonIssues(baseline, optimized).length === 0
    && !!a?.holdout_sha256 && a.holdout_sha256 === b?.holdout_sha256
}

export function difference(a: number | null | undefined, b: number | null | undefined): number | null {
  return typeof a === 'number' && typeof b === 'number' ? b - a : null
}
