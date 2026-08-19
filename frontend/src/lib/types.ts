/**
 * VetLink AI — Evidence Gate 核心型別定義
 * 對應提案書 第四節（四種狀態）與 第八節（回答護照）
 */

/** 四種閘門狀態 — 提案 §四 */
export type GateState = 'RED' | 'AMBER' | 'GREEN' | 'BLUE'

/** 三種角色 — 提案 §五 */
export type Role = 'owner' | 'vet' | 'admin'

/** 規則評估結果：成立(fired) 或 未成立(passed) — 護照必須同時顯示兩者 */
export interface RuleEvaluation {
  rule_id: string
  version: string
  name_zh: string
  /** true = 規則成立並觸發動作；false = 檢查通過、未觸發 */
  fired: boolean
  /** 該規則造成的系統動作 */
  action_zh: string
  /** 判定依據（引用使用者輸入的哪一段） */
  basis_zh?: string
  species?: string
  clinical_source?: string
  reviewed_by?: string
  reviewed_at?: string
}

/** 來源段落 — 主張級溯源的終點 */
export interface SourcePassage {
  passage_id: string
  doc_id: string
  doc_title_zh: string
  version: string
  /** 原始段落全文，點擊主張後顯示 */
  text: string
  page_ref?: string
  source_url?: string
  licence_no?: string
  issue_date_iso?: string
  expiry_date_iso?: string
  is_expired?: boolean
}

/** 單一主張 — 每項醫療/產品陳述都必須綁定來源 */
export interface Claim {
  claim_id: string
  text_zh: string
  /** 支持此主張的來源段落 ID；空陣列代表無證據，必須被刪除或拒答 */
  supported_by: string[]
  /** 主張驗證器結果 */
  verified: boolean
}

/** 文件版本資訊 — 提案 §八 */
export interface DocumentVersion {
  doc_id: string
  title_zh: string
  version: string
  issue_date_iso: string
  expiry_date_iso: string
  last_reviewed_iso?: string
  is_expired: boolean
  source_org: string
}

/** 拒絕原因分類 — 提案 §八 */
export type RefusalReason =
  | 'EMERGENCY_REDFLAG'
  | 'INSUFFICIENT_INFO'
  | 'ROLE_NOT_PERMITTED'
  | 'NO_EVIDENCE'
  | 'SOURCE_CONFLICT'
  | 'DOCUMENT_EXPIRED'

/** 回答護照 — 提案 §八 完整欄位 */
export interface AnswerPassport {
  audit_id: string
  gate_state: GateState
  applicable_roles: Role[]
  rules: RuleEvaluation[]
  claims: Claim[]
  passages: Record<string, SourcePassage>
  documents: DocumentVersion[]
  /** 適用範圍：物種、年齡等限制 */
  scope_zh: string[]
  refusal_reason?: RefusalReason
  refusal_detail_zh?: string
  /** 產品檢索是否被停止 — 第一幕的關鍵證據 */
  product_retrieval_halted: boolean
  halt_reason_zh?: string
  created_at_iso: string
}

/** 必要追問 — 黃色狀態專用，題目固定不由模型自由生成 */
export interface FollowUpQuestion {
  field: string
  question_zh: string
  options?: string[]
  required: boolean
}

/** 症狀時間軸節點 — 獸醫模式可見 */
export interface TimelineEntry {
  time_label_zh: string
  detail_zh: string
  severity: 'info' | 'warn' | 'critical'
}

/** /api/consult 回應 */
export interface ConsultResponse {
  gate_state: GateState
  headline_zh: string
  /** 飼主可見的分點內容 */
  content_blocks: ContentBlock[]
  follow_up_questions?: FollowUpQuestion[]
  emergency_referral?: EmergencyReferral
  visit_summary?: VisitSummary
  passport: AnswerPassport
  timeline?: TimelineEntry[]
  /** 檢索軌跡：文件庫 → 候選 → 主張 → 實際輸出（後端 retrieval 欄位） */
  retrieval?: RetrievalTrace
}

/* ------------------------------------------------------------------ *
 * 檢索軌跡
 *
 * 回答護照證明「每一句話都有來源」；檢索軌跡證明的是另一件事：
 * 系統從整個文件庫裡看了哪些、又為什麼沒看其他的。
 * 少了後者，「只講有來源的話」無法被反證 —— 因為看不到被略過的部分。
 * ------------------------------------------------------------------ */

/** 候選段落在漏斗裡走到哪一層 */
export type RetrievalStage =
  /** 已輸出給使用者 */
  | 'displayed'
  /** 通過主張驗證，但不在本次允許的輸出型別內 */
  | 'verified'
  /** 成為主張但未通過驗證，已刪除 */
  | 'unsupported'
  /** 檢索到但未成為主張（超出主張數上限） */
  | 'candidate'

export interface RetrievalCandidate {
  passage_id: string
  doc_id: string
  version: string
  text: string
  scenario_scope: string[]
  species_scope: string[]
  issue_date_iso?: string | null
  expiry_date_iso?: string | null
  is_expired: boolean
  review_status: string
  claim_id?: string | null
  stage: RetrievalStage
  stage_zh: string
}

export interface RetrievalExclusion {
  passage_id: string
  doc_id: string
  scenario_scope: string
  reason_zh: string
}

export interface RetrievalTrace {
  scenarios: string[]
  species?: string | null
  method_zh: string
  claim_limit: number
  candidates: RetrievalCandidate[]
  excluded: RetrievalExclusion[]
  counts: {
    library: number
    candidates: number
    claims: number
    verified: number
    displayed: number
    excluded: number
  }
}

/* ------------------------------------------------------------------ *
 * 文件庫瀏覽（GET /api/knowledge）
 * ------------------------------------------------------------------ */

export interface LibraryPassage {
  passage_id: string
  doc_id: string
  version: string
  text: string
  scenario_scope: string[]
  species_scope: string[]
  issue_date_iso?: string | null
  expiry_date_iso?: string | null
  is_expired: boolean
  review_status: string
  source_url?: string | null
  source_title?: string | null
  source_org?: string | null
  source_type: 'online' | 'internal' | 'government_open_data' | string
  fetched_at?: string | null
}

export interface LibraryProduct {
  licence_no: string
  name_zh: string
  name_en?: string | null
  company?: string | null
  dosage_form?: string | null
  ingredients_clean?: string | null
  indications_raw?: string | null
  species: string[]
  issue_date_iso?: string | null
  expiry_date_iso?: string | null
  is_expired: boolean
  expired_by_marker?: boolean
  expiry_date_raw?: string | null
  source_url?: string | null
  gate_zh: string
}

export interface KnowledgeLibrary {
  as_of: string
  role_zh: string
  education: {
    total: number
    online_total: number
    internal_total: number
    by_scenario: Record<string, number>
    by_source_org: Record<string, number>
    online_by_source_org: Record<string, number>
    note_zh: string
    passages: LibraryPassage[]
  }
  products: {
    unlocked: boolean
    total: number
    valid: number
    expired: number
    companion_animal: number
    ccpc_total: number
    source_zh: string
    note_zh: string
    records: LibraryProduct[]
  }
  expiry_gate: {
    date_only_expired_count: number
    examples: Array<{
      licence_no: string
      name_zh: string
      expiry_date_raw?: string | null
      expiry_date_iso?: string | null
      reason: string
    }>
    note_zh: string
  }
}

export interface ContentBlock {
  kind: 'danger_signs' | 'action' | 'education' | 'observe' | 'forbidden' | 'note'
  title_zh: string
  items: ContentItem[]
}

export interface ContentItem {
  text_zh: string
  /** 綁定的主張 ID，可點擊查看來源 */
  claim_id?: string
}

export interface EmergencyReferral {
  urgency_zh: string
  window_zh: string
  clinics: Clinic[]
  disclaimer_zh: string
}

export interface Clinic {
  name_zh: string
  district_zh: string
  phone: string
  is_24h: boolean
  /** 營業狀態是否經院所確認 — 提案要求不得宣稱未確認資訊 */
  status_confirmed: boolean
  distance_km: number
}

/** 就診摘要 — 交接給獸醫 */
export interface VisitSummary {
  summary_id: string
  pet: PetProfile
  chief_complaint_zh: string
  structured_fields: Array<{ label_zh: string; value_zh: string }>
  authorization_code: string
  expires_at_iso: string
}

export interface PetProfile {
  name_zh: string
  species_zh: string
  breed_zh: string
  sex_zh: string
  age_zh: string
  weight_kg: number
  neutered: boolean
}

/** 藍色模式產品檢索結果 — 對應真實農業部開放資料欄位 */
export interface ProductRecord {
  licence_no: string
  name_zh: string
  name_en: string
  company: string
  dosage_form: string
  ingredients_clean: string
  indications_raw: string
  species: string[]
  is_companion_animal: boolean
  issue_date_iso: string
  expiry_date_iso: string
  is_expired: boolean
  doc_id: string
  version: string
  source_url: string
  /** 該產品資訊對應的主張（可點擊溯源） */
  claim_id?: string
}

export interface VetSearchResponse {
  query_zh: string
  total: number
  /** 通過效期閘門的產品 */
  results: ProductRecord[]
  /** 被效期閘門擋下的產品 — 展示閘門確實在運作 */
  filtered_out: Array<{ record: ProductRecord; reason_zh: string }>
  passport: AnswerPassport
}

/* ---------- Impact Replay — 提案 §九 ---------- */

export type ImpactRisk = 'HIGH' | 'MEDIUM' | 'LOW'

export interface DiffSegment {
  kind: 'added' | 'removed' | 'unchanged'
  text: string
}

export interface PassageDiff {
  passage_id: string
  section_zh: string
  old_version: string
  new_version: string
  segments: DiffSegment[]
  change_summary_zh: string
}

export interface AffectedAnswer {
  audit_id: string
  asked_at_iso: string
  role: Role
  question_zh: string
  cited_passage_id: string
  cited_claim_zh: string
  risk: ImpactRisk
  risk_reason_zh: string
  /** 系統處置 */
  action_zh: string
  new_status_zh: string
}

export interface ReviewTask {
  task_id: string
  audit_id: string
  assignee_zh: string
  due_date_iso: string
  priority: ImpactRisk
  status_zh: string
}

export interface AuditLogEntry {
  ts_iso: string
  actor_zh: string
  event_zh: string
  detail_zh: string
}

export interface ImpactReplayResponse {
  doc_id: string
  doc_title_zh: string
  old_version: string
  new_version: string
  effective_date_iso: string
  diffs: PassageDiff[]
  affected: AffectedAnswer[]
  tasks: ReviewTask[]
  audit_log: AuditLogEntry[]
  stats: {
    scanned_answers: number
    affected_answers: number
    high: number
    medium: number
    low: number
  }
}

/* ------------------------------------------------------------------ *
 * A/B/C 三組對照 (提案 §12.1)
 * ------------------------------------------------------------------ */

export type CompareArmId = 'A' | 'B' | 'C'

/** 四個對比維度之一。good=true 表示這格對該組是「加分」。 */
export interface CompareDimension {
  value: boolean
  label_zh: string
  good: boolean
  detail_zh: string
}

export type CompareDimensionKey =
  | 'gives_dosage'
  | 'has_sources'
  | 'auditable'
  | 'blocks_emergency'

export interface CompareCitation {
  doc_id: string
  title_zh: string
  passage_id?: string
  note_zh: string
  is_expired?: boolean
}

export interface CompareRuleRef {
  rule_id: string
  version: string
  title: string
  reason_zh: string
  action_zh: string
}

export interface CompareArm {
  arm: CompareArmId
  name_zh: string
  subtitle_zh: string
  architecture_zh: string
  /** A、B 為對照組，UI 必須以警示樣式呈現 */
  is_baseline: boolean
  /** 無 API 金鑰時的預錄範例，絕不可呈現為即時呼叫 */
  is_prerecorded: boolean
  label_zh: string
  answer_zh: string
  messages?: string[]
  danger_signs?: string[]
  citations: CompareCitation[]
  audit_id: string | null
  gate_state: GateState | null
  state_label_zh?: string
  product_retrieval_halted?: boolean
  blocked_output_types?: string[]
  refusal_reason?: string
  refusal_detail_zh?: string
  rules_fired?: CompareRuleRef[]
  claim_count?: number
  verified_claim_count?: number
  policy_violations: string[]
  passport?: AnswerPassport
  note_zh: string
  dimensions: Record<CompareDimensionKey, CompareDimension>
  verdict_zh: string
}

export interface CompareResponse {
  question_zh: string
  is_flagship_case: boolean
  live_llm_available: boolean
  any_prerecorded: boolean
  disclaimer_zh: string
  arms: CompareArm[]
  dimension_order: CompareDimensionKey[]
  conclusion_zh: string
}

/* ------------------------------------------------------------------ *
 * 有效性驗證 — 獨立留出測試集 (GET /api/eval/holdout)
 *
 * 注意：後端以 "YELLOW" 表示資訊不足狀態，本頁的狀態欄位是
 * 評測原始輸出（非 gate_state 欄位），因此不會經過 api.ts 的
 * 自動正規化，顯示時需自行轉成 AMBER。
 * ------------------------------------------------------------------ */

export interface HoldoutMetric {
  key: string
  name_zh: string
  target: number
  /** min = 越高越好；max = 越低越好（違規率） */
  direction: 'min' | 'max'
  measured: number | null
  numerator: number
  denominator: number
  passed: boolean | null
  failures: Array<{ case_id: string; detail: string }>
  failure_count: number
}

export interface HoldoutCaseResult {
  case_id: string
  group: string
  perturbation: string
  text: string
  expect_state: string | null
  safe_states: string[]
  actual_state: string
  refusal: string
  halted: boolean
  halt_ok: boolean
  has_referral: boolean
  has_emergency_referral: boolean
  asks_questions: boolean
  leaks: string[]
  fired_rules: string[]
  basis: string
}

export interface HoldoutContrastArm {
  dataset: string
  label_zh: string
  total: number
  caught: number
  recall: number | null
}

export interface HoldoutResults {
  generated_at: string
  dataset: string
  as_of: string
  rules_bundle_version?: string
  cached: boolean
  case_set: {
    total: number
    by_group: Record<string, number>
    by_perturbation: Record<string, number>
    red_truth: number
    green_truth: number
    paraphrase_groups: number
  }
  environment: {
    llm_in_gate_path: boolean
    llm_structuring: string
    llm_translation: string
    llm_key_present: boolean
    llm_model: string
  }
  metrics: HoldoutMetric[]
  confusion_matrix: Record<string, Record<string, number>>
  red_recall_by_perturbation: Record<string, { total: number; caught: number; recall: number | null }>
  paraphrase_groups: Record<string, { states: string[]; consistent: boolean; all_unsafe: boolean }>
  contrast: {
    metric_zh: string
    case_bank: HoldoutContrastArm
    holdout: HoldoutContrastArm | null
    note_zh: string
  }
  cases: HoldoutCaseResult[]
  caveats: string[]
}
