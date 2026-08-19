/**
 * API 層 — 單一開關切換 mock / live。
 *
 *   VITE_USE_MOCKS=true   → 完全離線，使用 src/mocks 的 fixtures（預設）
 *   VITE_USE_MOCKS=false  → 呼叫 FastAPI 後端，經 Vite proxy /api → localhost:2222
 *
 * live 模式下若後端無回應，會自動退回 mock 並在 UI 標示，
 * 確保 Demo 在任何情況下都不會開天窗。
 */
import type {
  ConsultResponse, VetSearchResponse, ImpactReplayResponse, AnswerPassport,
  CompareResponse, CompareArm, CompareCitation, CompareDimension, CompareDimensionKey, GateState,
} from './types'
import { ACT1_CONSULT, ACT2_VET_SEARCH, ACT3_IMPACT_REPLAY, AMBER_CONSULT, COMPARE_FIXTURE, COMPARE_QUESTION } from '../mocks'

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


/* ------------------------------------------------------------------ *
 * live ↔ UI 契約轉接層
 *
 * 後端 ConsultResponse 與前端 mock fixtures 的欄位形狀並不相同
 * （後端回 messages / danger_signs / state；UI 需要 content_blocks /
 * emergency_referral / gate_state 等）。此處把真實回應轉成 UI 形狀，
 * 缺少的區塊一律補空陣列，確保 UI 不會因 undefined.filter 而白畫面。
 * ------------------------------------------------------------------ */

/** 後端未提供轉介名冊時的佔位（Demo 用示範醫院見 mock） */
const EMPTY_REFERRAL = {
  urgency_zh: '立即就醫',
  window_zh: '不得延後',
  clinics: [] as unknown[],
}

/** 後端 applicable_scope 物件 → UI 用的字串陣列 */
function scopeToLines(scope: unknown, fb: unknown): string[] {
  if (Array.isArray(scope)) return scope as string[]
  if (scope && typeof scope === 'object') {
    const LABEL: Record<string, string> = {
      species: '物種', role: '適用角色', scenarios: '情境',
      rule_species_scope: '規則物種範圍', review_status: '審核狀態',
    }
    return Object.entries(scope as Record<string, unknown>).map(
      ([k, v]) => `${LABEL[k] ?? k}：${Array.isArray(v) ? v.join('、') : String(v)}`,
    )
  }
  return Array.isArray(fb) ? (fb as string[]) : []
}

/**
 * 合併後端 visit_summary 與 UI 展示骨架。
 * 後端只回傳確定性事實，示範用的寵物基本資料與授權碼仍取自 fixtures，
 * 並在 UI 上維持「示範資料」語意，不偽稱為後端產生。
 */
function adaptVisitSummary(
  raw: Record<string, unknown> | undefined,
  fb: Record<string, unknown>,
): unknown {
  if (!raw || typeof raw !== 'object') return fb
  if ('pet' in raw) return raw
  const symptoms = Array.isArray(raw.symptoms) ? (raw.symptoms as string[]) : []
  return {
    ...fb,
    chief_complaint_zh: symptoms.length ? symptoms.join('、') : fb.chief_complaint_zh,
    gate_state: normalizeGateState(raw.gate_state ?? fb.gate_state),
    note_zh: raw.note ?? (fb as Record<string, unknown>).note_zh,
  }
}

/** 把後端 AnswerPassport 轉成 UI 期待的形狀 */
function adaptPassport(raw: Record<string, unknown> | undefined, fallback: unknown): unknown {
  if (!raw || typeof raw !== 'object') return fallback
  // 已是 UI 形狀（mock）則原樣返回
  if ('rules' in raw) return raw

  const fired = Array.isArray(raw.rules_fired) ? (raw.rules_fired as Record<string, unknown>[]) : []
  const failed = Array.isArray(raw.rules_failed) ? (raw.rules_failed as Record<string, unknown>[]) : []
  const fb = (fallback ?? {}) as Record<string, unknown>

  return {
    ...fb,
    ...raw,
    gate_state: normalizeGateState(raw.answer_state ?? fb.gate_state),
    // 後端分成 rules_fired / rules_failed，UI 使用單一 rules 陣列 + fired 旗標
    rules: [
      // basis_zh 顯示後端產生的自然語言說明（reason_zh）；
      // 機器判定式 detail 僅保留在 raw_detail，供稽核而非給使用者閱讀。
      ...fired.map((r) => ({
        rule_id: r.rule_id, version: r.version, name_zh: r.title,
        action_zh: r.action_zh || '觸發對應閘門動作',
        basis_zh: r.reason_zh || '',
        clinical_source: r.owner_message || '',
        raw_detail: r.detail,
        severity: r.severity, scenario_zh: r.scenario, fired: true,
      })),
      ...failed.map((r) => ({
        rule_id: r.rule_id, version: r.version, name_zh: r.title,
        action_zh: r.action_zh || '未成立',
        basis_zh: r.reason_zh || '',
        raw_detail: r.detail,
        severity: r.severity, scenario_zh: r.scenario, fired: false,
      })),
    ],
    // 後端 claim_bindings：claim_text / supported / passages[]
    // UI Claim：text_zh / verified / supported_by[](passage_id)
    claims: (Array.isArray(raw.claim_bindings) ? raw.claim_bindings : []).map(
      (c: Record<string, unknown>) => ({
        claim_id: c.claim_id,
        text_zh: c.claim_text,
        verified: c.supported,
        supported_by: (Array.isArray(c.passages) ? c.passages : []).map(
          (x: Record<string, unknown>) => x.passage_id,
        ),
        passages: c.passages ?? [],
      }),
    ),
    documents: (Array.isArray(raw.document_versions) ? raw.document_versions : []).map(
      (d: Record<string, unknown>) => ({
        ...d,
        doc_title_zh: d.doc_title_zh ?? d.doc_id,
        last_reviewed_at_iso: d.last_reviewed_at,
      }),
    ),
    // 後端把段落內嵌在各 claim 底下；UI 需要一份攤平的 passages 供點擊溯源
    passages: (Array.isArray(raw.claim_bindings) ? raw.claim_bindings : [])
      .flatMap((c: Record<string, unknown>) => (Array.isArray(c.passages) ? c.passages : []))
      .map((x: Record<string, unknown>) => ({ ...x, doc_title_zh: x.doc_title_zh ?? x.doc_id }))
      .filter(
        (x: Record<string, unknown>, i: number, arr: Record<string, unknown>[]) =>
          arr.findIndex((y) => y.passage_id === x.passage_id) === i,
      ),
    applicable_roles: raw.applicable_role ? [raw.applicable_role] : (fb.applicable_roles ?? []),
    created_at_iso: (raw.created_at as string) ?? fb.created_at_iso,
    refusal_detail_zh: (raw.refusal_detail as string) ?? fb.refusal_detail_zh,
    halt_reason_zh: (raw.refusal_detail as string) ?? fb.halt_reason_zh,
    // 後端 applicable_scope 是物件（species/role/scenarios…），UI 需要字串陣列
    scope_zh: scopeToLines(raw.applicable_scope, fb.scope_zh),
  }
}

/** 把後端 ConsultResponse 轉成 UI 期待的形狀 */
function adaptConsult(raw: Record<string, unknown>, fallback: ConsultResponse): ConsultResponse {
  if (!raw || typeof raw !== 'object') return fallback
  // 已是 UI 形狀（mock 或未來後端對齊）則原樣返回
  if ('content_blocks' in raw && 'gate_state' in raw) return raw as unknown as ConsultResponse

  const messages = Array.isArray(raw.messages) ? (raw.messages as string[]) : []
  const dangers = Array.isArray(raw.danger_signs) ? (raw.danger_signs as string[]) : []

  return {
    ...(fallback as unknown as Record<string, unknown>),
    ...raw,
    gate_state: normalizeGateState(raw.state ?? (raw as Record<string, unknown>).gate_state),
    headline_zh: (raw.headline as string) ?? fallback.headline_zh,
    // 後端以 messages / danger_signs 表達內容，轉為 UI 的 content_blocks
    // UI 的 Block.items 放的是 claim_id（供點擊溯源）。
    // 後端把已驗證主張放在 passport.claim_bindings，訊息文字放 messages，
    // 因此以 claim_id 為主、messages/danger_signs 作為無主張時的純文字後備。
    content_blocks: (() => {
      const cb = Array.isArray((raw.passport as Record<string, unknown>)?.claim_bindings)
        ? ((raw.passport as Record<string, unknown>).claim_bindings as Record<string, unknown>[])
        : []
      // Block.items 需要 { claim_id, text_zh } 物件，帶 claim_id 才會渲染成可點擊溯源按鈕
      const claimItems = cb
        .filter((c) => c.supported)
        .map((c) => ({ claim_id: String(c.claim_id), text_zh: String(c.claim_text ?? '') }))
      return [
        ...(claimItems.length
          ? [{ kind: 'education', title_zh: '經審核的衛教與觀察事項', items: claimItems }]
          : messages.length
            ? [{
                kind: 'action',
                title_zh: '系統判定與立即行動',
                items: messages.map((t) => ({ text_zh: t })),
              }]
            : []),
        ...(dangers.length
          ? [{
              kind: 'danger_signs',
              title_zh: '危險徵兆',
              items: dangers.map((t) => ({ text_zh: t })),
            }]
          : []),
      ]
    })(),
    // 後端目前不回傳急診名冊與時間軸，補空結構避免 UI 崩潰
    // 後端不提供醫院名冊（正式版由院所資料源確認營業狀態），
    // 這裡沿用 fixtures 的示範名冊，避免急診轉介區塊在 live 模式空白。
    emergency_referral:
      (raw.emergency_referral as unknown) ?? fallback.emergency_referral ?? EMPTY_REFERRAL,
    timeline: (raw.timeline as unknown[]) ?? fallback.timeline ?? [],
    // 後端 visit_summary 僅含結構化事實（species/symptoms/fired_rules…），
    // 缺少 UI 展示用的 pet/summary_id/authorization_code 等欄位。
    // 保留 mock 的展示骨架，僅以後端真實值覆寫可對應的部分。
    visit_summary: adaptVisitSummary(
      raw.visit_summary as Record<string, unknown>,
      fallback.visit_summary as unknown as Record<string, unknown>,
    ),
    passport: adaptPassport(raw.passport as Record<string, unknown>, fallback.passport),
  } as unknown as ConsultResponse
}

/** POST /api/consult — 閘門判定 + 回答護照 */
export function consult(payload: { question_zh: string; role?: string; case_id?: string }): Promise<ConsultResponse> {
  const mock = payload.case_id === 'amber' ? AMBER_CONSULT : ACT1_CONSULT
  // 後端 ConsultRequest 使用 text 欄位，並需要結構化的物種/排尿狀態才能觸發規則
  const body: Record<string, unknown> = {
    text: payload.question_zh,
    role: payload.role ?? 'owner',
  }
  if (payload.case_id !== 'amber') {
    body.species = 'cat'
    body.can_urinate = false
  }
  return withFallback(
    async () => {
      const raw = await request<Record<string, unknown>>('/api/consult', {
        method: 'POST',
        body: JSON.stringify(body),
      })
      return adaptConsult(raw, mock)
    },
    mock,
  )
}

/** POST /api/vet/search — 藍色模式產品檢索（需授權 token） */
export function vetSearch(payload: { query_zh: string; auth_token: string; case_id?: string }): Promise<VetSearchResponse> {
  return withFallback(
    () =>
      request<VetSearchResponse>('/api/vet/search', {
        method: 'POST',
        // 後端 VetSearchRequest 使用 query，且 species 為產品檢索的必要條件
        body: JSON.stringify({ query: payload.query_zh, species: 'cat' }),
        headers: { 'X-Vet-Token': payload.auth_token },
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

/* ------------------------------------------------------------------ *
 * A/B/C 三組對照 (提案 §12.1)
 *
 * 後端 /api/compare 的形狀已直接對齊 UI，僅需補上缺漏欄位的預設值，
 * 避免任何一組 arm 缺 dimensions 時 UI 崩潰。
 * 沿用既有轉接層慣例：不改動既有 adapter，另立一個。
 * ------------------------------------------------------------------ */

const EMPTY_DIM = (label_zh: string): CompareDimension => ({
  value: false, label_zh, good: false, detail_zh: '—',
})

/** 補齊後端可能缺漏的欄位，確保 UI 永遠拿得到四個維度 */
function adaptCompare(raw: Record<string, unknown>, fallback: CompareResponse): CompareResponse {
  if (!raw || typeof raw !== 'object' || !Array.isArray(raw.arms)) return fallback

  const arms = (raw.arms as Record<string, unknown>[]).map((a): CompareArm => {
    const dims = (a.dimensions ?? {}) as Record<string, CompareDimension>
    return {
      ...(a as unknown as CompareArm),
      // 後端 C 組回 "RED"/"YELLOW"…；統一正規化為前端四值
      gate_state: a.gate_state ? (normalizeGateState(a.gate_state) as GateState) : null,
      citations: Array.isArray(a.citations) ? (a.citations as CompareCitation[]) : [],
      policy_violations: Array.isArray(a.policy_violations) ? (a.policy_violations as string[]) : [],
      dimensions: {
        gives_dosage: dims.gives_dosage ?? EMPTY_DIM('是否提供劑量'),
        has_sources: dims.has_sources ?? EMPTY_DIM('是否有來源'),
        auditable: dims.auditable ?? EMPTY_DIM('是否可稽核'),
        blocks_emergency: dims.blocks_emergency ?? EMPTY_DIM('是否攔截急症'),
      },
    }
  })

  return {
    ...fallback,
    ...(raw as unknown as CompareResponse),
    arms,
    dimension_order: (Array.isArray(raw.dimension_order) && raw.dimension_order.length
      ? raw.dimension_order
      : fallback.dimension_order) as CompareDimensionKey[],
  }
}

/** POST /api/compare — A（一般 LLM）／B（單純 RAG）／C（VetLink AI）同輸入對照 */
export function compare(payload?: { question_zh?: string }): Promise<CompareResponse> {
  return withFallback(
    async () => {
      const raw = await request<Record<string, unknown>>('/api/compare', {
        method: 'POST',
        body: JSON.stringify({ question_zh: payload?.question_zh ?? COMPARE_QUESTION }),
      })
      return adaptCompare(raw, COMPARE_FIXTURE)
    },
    COMPARE_FIXTURE,
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
