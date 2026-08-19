/**
 * API 層 — 單一開關切換 mock / live。
 *
 *   VITE_USE_MOCKS=true   → 完全離線，使用 src/mocks 的 fixtures（預設）
 *   VITE_USE_MOCKS=false  → 呼叫 FastAPI 後端，經 Vite proxy /api → localhost:8000
 *
 * live 模式下若後端無回應，會自動退回 mock 並在 UI 標示，
 * 確保 Demo 在任何情況下都不會開天窗。
 */
import type { ConsultResponse, VetSearchResponse, ImpactReplayResponse, AnswerPassport } from './types'
import { ACT1_CONSULT, ACT2_VET_SEARCH, ACT3_IMPACT_REPLAY, AMBER_CONSULT } from '../mocks'

/**
 * 後端 (FastAPI) 以 "YELLOW" 表示「資訊不足」狀態，
 * 前端型別統一使用 "AMBER"。此處在資料入口一次正規化，
 * 使 UI 層永遠只需處理 RED / AMBER / GREEN / BLUE 四值。
 */
export function normalizeGateState(v: unknown): string {
  return v === 'YELLOW' ? 'AMBER' : (v as string)
}

/** 遞迴改寫回應中所有 gate_state 欄位（含巢狀 passport） */
function normalizeGates<T>(data: T): T {
  if (Array.isArray(data)) return data.map((x) => normalizeGates(x)) as unknown as T
  if (data && typeof data === 'object') {
    const out: Record<string, unknown> = {}
    for (const [k, v] of Object.entries(data as Record<string, unknown>)) {
      out[k] = k === 'gate_state' ? normalizeGateState(v) : normalizeGates(v)
    }
    return out as T
  }
  return data
}

/** 單一開關 */
export const USE_MOCKS: boolean = import.meta.env.VITE_USE_MOCKS !== 'false'

export type DataSource = 'mock' | 'live' | 'live-fallback'

let lastSource: DataSource = USE_MOCKS ? 'mock' : 'live'
export const getLastSource = (): DataSource => lastSource

const delay = (ms: number) => new Promise((r) => setTimeout(r, ms))

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const ctrl = new AbortController()
  const timer = setTimeout(() => ctrl.abort(), 6000)
  try {
    const res = await fetch(path, {
      ...init,
      signal: ctrl.signal,
      headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
    })
    if (!res.ok) throw new Error(`${res.status} ${res.statusText}`)
    // 後端 YELLOW → 前端 AMBER，在此統一正規化
    return normalizeGates((await res.json()) as T)
  } finally {
    clearTimeout(timer)
  }
}

/** live 呼叫失敗時退回 mock，Demo 永不中斷 */
async function withFallback<T>(live: () => Promise<T>, mock: T): Promise<T> {
  if (USE_MOCKS) {
    lastSource = 'mock'
    await delay(280)
    return mock
  }
  try {
    const r = await live()
    lastSource = 'live'
    return r
  } catch (e) {
    console.warn('[VetLink] 後端無回應，已退回 mock 資料：', e)
    lastSource = 'live-fallback'
    return mock
  }
}

/** POST /api/consult — 閘門判定 + 回答護照 */
export function consult(payload: { question_zh: string; role?: string; case_id?: string }): Promise<ConsultResponse> {
  const mock = payload.case_id === 'amber' ? AMBER_CONSULT : ACT1_CONSULT
  return withFallback(
    () => request<ConsultResponse>('/api/consult', { method: 'POST', body: JSON.stringify(payload) }),
    mock,
  )
}

/** POST /api/vet/search — 藍色模式產品檢索（需授權 token） */
export function vetSearch(payload: { query_zh: string; auth_token: string; case_id?: string }): Promise<VetSearchResponse> {
  return withFallback(
    () =>
      request<VetSearchResponse>('/api/vet/search', {
        method: 'POST',
        body: JSON.stringify(payload),
        headers: { Authorization: `Bearer ${payload.auth_token}` },
      }),
    ACT2_VET_SEARCH,
  )
}

/** GET /api/passport/{audit_id} */
export function getPassport(auditId: string): Promise<AnswerPassport> {
  const mock =
    auditId === ACT2_VET_SEARCH.passport.audit_id ? ACT2_VET_SEARCH.passport : ACT1_CONSULT.passport
  return withFallback(() => request<AnswerPassport>(`/api/passport/${auditId}`), mock)
}

/** POST /api/admin/impact-replay */
export function impactReplay(payload: { doc_id: string; new_version: string }): Promise<ImpactReplayResponse> {
  return withFallback(
    () => request<ImpactReplayResponse>('/api/admin/impact-replay', { method: 'POST', body: JSON.stringify(payload) }),
    ACT3_IMPACT_REPLAY,
  )
}

/** GET /api/health */
export async function health(): Promise<{ ok: boolean }> {
  if (USE_MOCKS) return { ok: true }
  try {
    await request<unknown>('/api/health')
    return { ok: true }
  } catch {
    return { ok: false }
  }
}
