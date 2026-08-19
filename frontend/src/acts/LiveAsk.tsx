/**
 * 實際使用（LIVE）— 飼主真的可以自己提問的頁面。
 *
 * 這頁與 Act1/Act2/Act3/Compare 的性質完全不同：
 * 那些是為評審設計的劇本式導覽，輸入固定、結果可預期；
 * 這頁是「產品本身」——使用者輸入任何問題，畫面上出現什麼，
 * 就是後端 Evidence Gate 真的判定出來的結果。
 *
 * 因此本頁有三條不可妥協的原則：
 *   1. 永不使用 mock 備援。後端不通就明講，不拿罐頭答案冒充真實回應。
 *   2. 追問（黃色）是真的互動：使用者填完必要欄位重送，狀態會真的重新判定。
 *   3. 飼主角色的輸出邊界由後端 blocked_output_types 決定，UI 只呈現、不繞過。
 */
import { useEffect, useMemo, useRef, useState } from 'react'
import type { ConsultResponse, FollowUpQuestion, GateState, RetrievalTrace } from '../lib/types'
import { consultFree, healthLive, ConsultError, type ConsultFields, type ConsultFailureKind } from '../lib/api'
import { GATE_META } from '../lib/gateStates'
import { AnswerPassportCard, ClaimButton } from '../components/Passport'
import {
  IconArrowRight, IconQuestion, IconStop, IconCheck, IconShield, IconAlert,
  IconBan, IconClock, IconUser, IconList, IconSearch,
} from '../components/Icons'

/* ================================================================== *
 * 追問欄位 → 輸入控制項的對應表
 *
 * 後端 required_questions 只給 {field, question}，沒有型別資訊。
 * 這裡依欄位語意決定該用數字、是非還是選單，並負責把值轉成
 * 後端 schema 接受的型別（例如 current_medications 必須是陣列，
 * mentation 必須是 normal/lethargic/collapsed/unknown 其中之一）。
 * ================================================================== */

type FieldKind = 'number' | 'yesno' | 'select' | 'text'

interface FieldSpec {
  kind: FieldKind
  /** 數字欄位的單位提示 */
  unit?: string
  placeholder?: string
  /** select 用：顯示中文、送出後端接受的值 */
  options?: Array<{ label: string; value: string }>
  /** yesno 用：true / false 各自的中文說法 */
  yes?: string
  no?: string
  hint?: string
}

const FIELD_SPECS: Record<string, FieldSpec> = {
  body_weight_kg: { kind: 'number', unit: '公斤', placeholder: '例如 4.5', hint: '體重會影響安全評估範圍，請盡量填實際數字。' },
  duration_hours: { kind: 'number', unit: '小時', placeholder: '例如 24', hint: '從第一次注意到症狀算起，大約幾小時。' },
  temperature_c: { kind: 'number', unit: '°C', placeholder: '例如 38.5' },
  age_months: { kind: 'number', unit: '月', placeholder: '例如 36' },
  vomit_count_24h: { kind: 'number', unit: '次', placeholder: '例如 3' },

  can_urinate: { kind: 'yesno', yes: '有尿出來', no: '尿不出來', hint: '完全尿不出來屬於急症紅旗，公貓可能數小時內危及生命。' },
  vomiting: { kind: 'yesno', yes: '有嘔吐', no: '沒有嘔吐' },
  can_keep_water: { kind: 'yesno', yes: '喝得下、留得住', no: '喝了就吐' },

  severity: {
    kind: 'select',
    options: [
      { label: '輕微（偶爾發生，精神食慾正常）', value: '輕微（偶爾發生，精神食慾正常）' },
      { label: '中等（頻繁發生，但仍願意吃喝）', value: '中等（頻繁發生，但仍願意吃喝）' },
      { label: '嚴重（持續發生，精神或食慾明顯變差）', value: '嚴重（持續發生，精神或食慾明顯變差）' },
    ],
  },
  mentation: {
    kind: 'select',
    // 值必須是後端 Mentation enum，中文僅為顯示
    options: [
      { label: '正常，跟平常一樣有活力', value: 'normal' },
      { label: '精神變差、比較沒力氣', value: 'lethargic' },
      { label: '虛脫、站不太起來', value: 'collapsed' },
      { label: '不確定', value: 'unknown' },
    ],
  },
  breathing_effort: {
    kind: 'select',
    options: [
      { label: '呼吸正常', value: 'normal' },
      { label: '呼吸比較用力、比較喘', value: 'increased' },
      { label: '明顯呼吸困難、張口呼吸', value: 'severe' },
    ],
  },
  mucous_membrane_color: {
    kind: 'select',
    options: [
      { label: '牙齦粉紅色（正常）', value: 'pink' },
      { label: '牙齦偏白', value: 'pale' },
      { label: '牙齦偏藍或偏紫', value: 'cyanotic' },
      { label: '沒看過／不確定', value: 'unknown' },
    ],
  },
  sex: {
    kind: 'select',
    options: [
      { label: '公', value: 'male' },
      { label: '母', value: 'female' },
      { label: '不確定', value: 'unknown' },
    ],
  },

  current_medications: {
    kind: 'text',
    placeholder: '例如：心絲蟲預防藥、皮膚保健品（沒有就留空）',
    hint: '包含處方藥、保健品與外用藥。可用「、」或逗號分隔多項；沒有請留空。',
  },
}

const FALLBACK_SPEC: FieldSpec = { kind: 'text', placeholder: '請輸入' }
const specFor = (field: string): FieldSpec => FIELD_SPECS[field] ?? FALLBACK_SPEC

/** 使用者在追問表單裡輸入的原始字串（統一存字串，送出前才轉型） */
type RawAnswers = Record<string, string>

/**
 * 把追問表單的原始字串轉成後端 schema 接受的型別。
 * 這是本頁最容易出錯的一段：送錯型別後端會直接 422，
 * 例如 current_medications 送字串（而非陣列）就會失敗。
 */
function toConsultFields(raw: RawAnswers, questions: FollowUpQuestion[] = []): ConsultFields {
  const out: Record<string, unknown> = {}

  // 被問到、但使用者留白的「目前用藥」代表「沒有在用藥」，
  // 必須明確送出空陣列；完全不送的話後端會判定此欄位仍缺值，狀態會卡在黃色。
  for (const q of questions) {
    if (isOptionalBlank(q.field) && !(q.field in raw)) out[q.field] = []
  }

  for (const [field, value] of Object.entries(raw)) {
    const v = value.trim()
    const spec = specFor(field)

    if (field === 'current_medications') {
      // 空值代表「沒有在用藥」，仍必須送出空陣列，
      // 否則後端會判定此欄位未填，狀態繼續卡在黃色。
      out[field] = v === '' ? [] : v.split(/[、,，\s]+/).filter(Boolean)
      continue
    }
    if (v === '') continue

    if (spec.kind === 'number') {
      const n = Number(v)
      if (!Number.isNaN(n)) out[field] = n
      continue
    }
    if (spec.kind === 'yesno') {
      out[field] = v === 'yes'
      continue
    }
    out[field] = v
  }
  return out as ConsultFields
}

/**
 * 「目前用藥」留白是有意義的答案（＝沒有在用藥），
 * 因此不強迫使用者先打字才算完成，否則沒在用藥的飼主會卡在黃色出不去。
 */
const isOptionalBlank = (field: string) => field === 'current_medications'

/**
 * 某一題是否已作答（留白即答案的欄位一律視為已答）。
 *
 * 刻意**不** export：這個檔案同時 export React 元件，多一個非元件的 export
 * 會讓 React Fast Refresh 失效（"export is incompatible"），
 * 於是每次存檔都變成整頁重載 —— 對話紀錄跟著被清光，這頁最需要保留的
 * 就是那串對話。只在本檔使用，沒有 export 的必要。
 */
function isAnswered(field: string, raw: RawAnswers): boolean {
  if (isOptionalBlank(field)) return true
  return (raw[field] ?? '').trim() !== ''
}

/** 追問是否已可送出 */
function isComplete(questions: FollowUpQuestion[], raw: RawAnswers): boolean {
  return questions.every((q) => isAnswered(q.field, raw))
}

/* ================================================================== *
 * 對話紀錄
 * ================================================================== */

interface UserTurn {
  kind: 'user'
  id: string
  text: string
  /** 這一輪隨問題一起送出的結構化欄位（供「送出了什麼」透明呈現） */
  fields: ConsultFields
  /** 是否為補答追問後的重送 */
  isFollowUp: boolean
}

interface AnswerTurn {
  kind: 'answer'
  id: string
  data: ConsultResponse
  /** 後端回傳的原始追問（未經 UI 補值） */
  questions: FollowUpQuestion[]
}

interface ErrorTurn {
  kind: 'error'
  id: string
  message: string
  /** 失敗種類 —— 決定要請使用者做什麼，不可用訊息字串猜 */
  failure: ConsultFailureKind
}

type Turn = UserTurn | AnswerTurn | ErrorTurn

const SPECIES_LABEL: Record<'cat' | 'dog', string> = { cat: '貓', dog: '狗' }

/** 一鍵示範問題 — 刻意涵蓋紅色與黃色兩條路徑，讓使用者兩種都感受得到 */
const STARTERS: Array<{ text: string; expect: GateState; note: string }> = [
  {
    text: '我的貓一直進砂盆但尿不出來，可以先吃什麼藥？',
    expect: 'RED',
    note: '急症紅旗：系統會在檢索任何產品前就停止',
  },
  {
    text: '我家狗狗一直抓耳朵，還有臭味',
    expect: 'AMBER',
    note: '資訊不足：系統會先問必要問題',
  },
  {
    text: '貓咪蹲在廁所裡好久都沒有東西出來',
    expect: 'RED',
    note: '沒有出現關鍵字，仍能判為急症',
  },
  {
    text: '我家貓咪最近有點軟便，該注意什麼？',
    expect: 'AMBER',
    note: '一般諮詢：走完整追問流程',
  },
]

let turnSeq = 0
const nextId = () => `t${++turnSeq}`

export function LiveAsk() {
  const [species, setSpecies] = useState<'cat' | 'dog' | null>(null)
  const [draft, setDraft] = useState('')
  const [turns, setTurns] = useState<Turn[]>([])
  const [loading, setLoading] = useState(false)
  /** 針對「最後一個黃色回覆」的追問答案 */
  const [answers, setAnswers] = useState<RawAnswers>({})
  const [backend, setBackend] = useState<'checking' | 'up' | 'down'>('checking')
  const [bundle, setBundle] = useState('')

  const bottomRef = useRef<HTMLDivElement>(null)
  const taRef = useRef<HTMLTextAreaElement>(null)

  /** 誠實的狀態指示：真的去打 /api/health，不看 VITE_USE_MOCKS */
  useEffect(() => {
    let alive = true
    const check = () =>
      healthLive().then((h) => {
        if (!alive) return
        setBackend(h.ok ? 'up' : 'down')
        if (h.ok && h.detail) setBundle(h.detail)
      })
    check()
    const t = setInterval(check, 20000)
    return () => { alive = false; clearInterval(t) }
  }, [])

  useEffect(() => {
    bottomRef.current?.scrollIntoView({ behavior: 'smooth', block: 'end' })
  }, [turns.length, loading])

  /** 目前最後一則回覆；只有它的追問可以作答 */
  const lastAnswer = useMemo(() => {
    for (let i = turns.length - 1; i >= 0; i--) {
      const t = turns[i]
      if (t.kind === 'answer') return t
    }
    return null
  }, [turns])

  const pendingQuestions =
    lastAnswer && lastAnswer.data.gate_state === 'AMBER' ? lastAnswer.questions : []

  /** 送出一次真實的閘門判定 */
  const send = async (text: string, extra: ConsultFields, isFollowUp: boolean) => {
    const trimmed = text.trim()
    if (!trimmed || loading) return

    const fields: ConsultFields = { ...extra }
    // 只有使用者「這一刻真的選了」物種才送出。
    // 補答追問時 extra 已帶著原始那一輪的 species，不可被目前選擇器覆蓋，
    // 否則同一場對話裡換問另一種動物會把舊物種帶進新問題 ——
    // 貓與狗的用藥安全差異極大，帶錯物種等於送出錯誤前提。
    if (species && !('species' in fields)) fields.species = species

    setTurns((prev) => [...prev, { kind: 'user', id: nextId(), text: trimmed, fields, isFollowUp }])
    setLoading(true)
    try {
      const data = await consultFree(trimmed, fields)
      setTurns((prev) => [
        ...prev,
        { kind: 'answer', id: nextId(), data, questions: data.follow_up_questions ?? [] },
      ])
      // 新一輪回覆 → 清掉上一輪的追問草稿
      setAnswers({})
      // 這裡刻意「不」把後端推斷出的物種寫回選擇器。
      // 選擇器代表的是使用者的明示選擇；若讓上一題推斷出的物種留在上面，
      // 下一題問另一種動物時就會被悄悄套上錯誤物種。
      // 後端本來就會從描述自行推斷，UI 不需要、也不應該替使用者記住這件事。
    } catch (e) {
      const failure: ConsultFailureKind = e instanceof ConsultError ? e.kind : 'client'
      setTurns((prev) => [
        ...prev,
        {
          kind: 'error',
          id: nextId(),
          message: e instanceof Error ? e.message : String(e),
          failure,
        },
      ])
      // 只有真的連不上／逾時才代表後端掛了。
      // 後端回 200 但前端解析失敗時把狀態列標成「後端離線」是錯誤指控。
      if (failure === 'unreachable' || failure === 'timeout') setBackend('down')
    } finally {
      setLoading(false)
    }
  }

  const submitDraft = () => {
    const t = draft.trim()
    if (!t) return
    setDraft('')
    void send(t, {}, false)
  }

  /** 補答追問後重送：帶上原始問題 + 已填欄位，讓後端重新判定 */
  const submitFollowUp = () => {
    if (!lastAnswer) return
    // 找出這一輪對應的原始提問文字
    let originalText = ''
    let carried: ConsultFields = {}
    for (let i = turns.length - 1; i >= 0; i--) {
      const t = turns[i]
      if (t.kind === 'user') { originalText = t.text; carried = t.fields; break }
    }
    void send(
      originalText,
      { ...carried, ...toConsultFields(answers, lastAnswer.questions) },
      true,
    )
  }

  const onKeyDown = (e: React.KeyboardEvent<HTMLTextAreaElement>) => {
    if (e.key === 'Enter' && !e.shiftKey && !e.nativeEvent.isComposing) {
      e.preventDefault()
      submitDraft()
    }
  }

  const complete = pendingQuestions.length > 0 && isComplete(pendingQuestions, answers)
  const empty = turns.length === 0

  return (
    <div className="stack gap-6 live">
      <LiveHeader backend={backend} bundle={bundle} />

      <SpeciesPicker value={species} onChange={setSpecies} />

      {/* ---- 對話區 ---- */}
      <div className="live__thread stack gap-5" aria-live="polite">
        {empty && !loading && <EmptyState onPick={(t) => { setDraft(t); taRef.current?.focus() }} />}

        {turns.map((t) =>
          t.kind === 'user' ? (
            <UserBubble key={t.id} turn={t} />
          ) : t.kind === 'answer' ? (
            <AnswerCard key={t.id} data={t.data} />
          ) : (
            <ErrorCard key={t.id} message={t.message} failure={t.failure} />
          ),
        )}

        {loading && <ThinkingCard />}
        <div ref={bottomRef} />
      </div>

      {/* ---- 黃色追問表單：本頁的核心互動 ---- */}
      {pendingQuestions.length > 0 && !loading && (
        <FollowUpForm
          questions={pendingQuestions}
          answers={answers}
          onChange={(f, v) => setAnswers((a) => ({ ...a, [f]: v }))}
          complete={complete}
          onSubmit={submitFollowUp}
        />
      )}

      {/* ---- 輸入列 ---- */}
      <div className="live__composer">
        <label className="label" htmlFor="live-input">描述你家寶貝的狀況</label>
        <div className="live__composer-row">
          <textarea
            id="live-input"
            ref={taRef}
            className="live__ta"
            rows={3}
            placeholder="例如：我家貓咪從昨天開始一直進砂盆，但好像都沒有尿出來…（Enter 送出，Shift+Enter 換行）"
            value={draft}
            onChange={(e) => setDraft(e.target.value)}
            onKeyDown={onKeyDown}
            disabled={loading}
          />
          <button
            type="button"
            className="btn btn--primary btn--lg live__send"
            onClick={submitDraft}
            disabled={loading || draft.trim() === ''}
          >
            {loading ? '判定中…' : '送出'}
            {!loading && <IconArrowRight size={18} />}
          </button>
        </div>
        <p className="muted">
          VetLink AI 不做診斷、不提供劑量、不給處方藥購買管道。
          最終診斷與用藥決策一律交由執業獸醫師。
        </p>
      </div>
    </div>
  )
}

/* ================================================================== *
 * 頁首與狀態指示
 * ================================================================== */

function LiveHeader({ backend, bundle }: { backend: 'checking' | 'up' | 'down'; bundle: string }) {
  return (
    <header className="live__hero">
      <div className="live__hero-main">
        <span className="live__hero-mark"><IconShield size={26} /></span>
        <div className="stack gap-2">
          <h1 className="live__hero-title">我要提問</h1>
          <p className="live__hero-sub">
            輸入任何關於毛小孩的狀況，Evidence Gate 會先判斷這次<b>能不能回答、能回答到什麼程度</b>，
            再決定要給你衛教、追問，還是請你立刻就醫。
          </p>
        </div>
      </div>
      <BackendChip backend={backend} bundle={bundle} />
    </header>
  )
}

/**
 * 誠實的資料來源指示。
 * 這頁的價值建立在「答案是真的」，因此後端不通時必須明說，
 * 不能靜默退回罐頭資料還讓畫面看起來一切正常。
 */
function BackendChip({ backend, bundle }: { backend: 'checking' | 'up' | 'down'; bundle: string }) {
  if (backend === 'checking') {
    return <span className="live__chip" data-status="checking"><IconClock size={15} /> 連線檢查中…</span>
  }
  if (backend === 'down') {
    return (
      <span className="live__chip" data-status="down">
        <IconAlert size={15} /> 後端未連線，本頁不會顯示任何模擬答案
      </span>
    )
  }
  return (
    <span className="live__chip" data-status="up">
      <span className="live__dot" aria-hidden />
      即時連線後端｜每個答案都是真的判定{bundle ? `｜規則庫 ${bundle}` : ''}
    </span>
  )
}

/* ================================================================== *
 * 物種選擇
 * ================================================================== */

function SpeciesPicker({
  value, onChange,
}: { value: 'cat' | 'dog' | null; onChange: (v: 'cat' | 'dog' | null) => void }) {
  return (
    <div className="live__species">
      <span className="label">你要問的是</span>
      <div className="live__species-btns" role="group" aria-label="物種選擇">
        {(['cat', 'dog'] as const).map((s) => (
          <button
            key={s}
            type="button"
            className="live__species-btn"
            aria-pressed={value === s}
            onClick={() => onChange(value === s ? null : s)}
          >
            <span className="live__species-emoji" aria-hidden>{s === 'cat' ? '🐈' : '🐕'}</span>
            {SPECIES_LABEL[s]}
          </button>
        ))}
      </div>
      <span className="muted live__species-note">
        {value
          ? `已指定為${SPECIES_LABEL[value]}。貓與狗的用藥安全規則差異極大，指定物種會讓判定更準確。`
          : '可以不選，系統會嘗試從你的描述判斷物種；但貓狗用藥安全差異極大，指定後判定更準確。'}
      </span>
    </div>
  )
}

/* ================================================================== *
 * 空狀態 / 建議問題
 * ================================================================== */

function EmptyState({ onPick }: { onPick: (t: string) => void }) {
  return (
    <div className="live__empty stack gap-4">
      <div className="stack gap-2">
        <div className="live__empty-title">還沒有問題，先從這些開始？</div>
        <p className="muted">
          點一下就會填入輸入框。以下四題會走到不同的判定結果，有的會被系統擋下來轉急診，
          有的會先被追問。這正是 Evidence Gate 與一般聊天機器人的差別。
        </p>
      </div>
      <div className="live__starters">
        {STARTERS.map((s) => {
          const m = GATE_META[s.expect]
          return (
            <button
              key={s.text}
              type="button"
              className="live__starter"
              data-state={s.expect}
              onClick={() => onPick(s.text)}
            >
              <span className="live__starter-text">{s.text}</span>
              <span className="live__starter-foot">
                <span className="live__starter-tag" data-state={s.expect}>
                  <span aria-hidden>{m.glyph}</span> 預期 {m.label}
                </span>
                <span className="live__starter-note">{s.note}</span>
              </span>
            </button>
          )
        })}
      </div>
    </div>
  )
}

/* ================================================================== *
 * 對話泡泡
 * ================================================================== */

const FIELD_LABEL_ZH: Record<string, string> = {
  species: '物種', body_weight_kg: '體重', age_months: '年齡', sex: '性別',
  duration_hours: '持續時間', severity: '嚴重度', current_medications: '目前用藥',
  can_urinate: '可否排尿', vomiting: '是否嘔吐', mentation: '精神狀態',
  breathing_effort: '呼吸狀況', mucous_membrane_color: '黏膜顏色',
  temperature_c: '體溫', vomit_count_24h: '24 小時嘔吐次數', can_keep_water: '是否喝得下水',
}

/** 把送出的欄位值轉成人看得懂的中文 */
function displayValue(field: string, v: unknown): string {
  if (Array.isArray(v)) return v.length ? v.join('、') : '無'
  if (typeof v === 'boolean') {
    const spec = specFor(field)
    return v ? (spec.yes ?? '是') : (spec.no ?? '否')
  }
  if (field === 'species') return SPECIES_LABEL[v as 'cat' | 'dog'] ?? String(v)
  const spec = specFor(field)
  if (spec.kind === 'select') {
    const hit = spec.options?.find((o) => o.value === String(v))
    if (hit) return hit.label
  }
  if (spec.kind === 'number' && spec.unit) return `${v} ${spec.unit}`
  return String(v)
}

function UserBubble({ turn }: { turn: UserTurn }) {
  const entries = Object.entries(turn.fields)
  return (
    <div className="live__turn live__turn--user">
      <div className="live__who">
        <IconUser size={14} /> 你{turn.isFollowUp && ' · 補充資訊後重新送出'}
      </div>
      <div className="live__bubble">{turn.text}</div>
      {entries.length > 0 && (
        <div className="live__fields">
          {entries.map(([k, v]) => (
            <span className="live__field" key={k}>
              <b>{FIELD_LABEL_ZH[k] ?? k}</b>：{displayValue(k, v)}
            </span>
          ))}
        </div>
      )}
    </div>
  )
}

function ThinkingCard() {
  return (
    <div className="live__turn">
      <div className="live__thinking">
        <span className="live__spinner" aria-hidden />
        <span className="stack gap-1">
          <b>Evidence Gate 判定中…</b>
          <span className="muted">
            症狀結構化 → 安全資格（紅旗規則）→ 資料資格 → 角色資格 → 證據資格 → 一致性資格
          </span>
        </span>
      </div>
    </div>
  )
}

/**
 * 各失敗種類對使用者的說法。
 * 關鍵差異在 cause（到底是誰出問題）與 next（使用者該做什麼）：
 * 前端解析失敗時要求使用者去重啟後端，只會讓人白忙一場。
 */
const FAILURE_COPY: Record<
  ConsultFailureKind,
  { head: string; cause: string; next: string }
> = {
  unreachable: {
    head: '連不上後端服務',
    cause: '前端送出了請求，但後端沒有接。這一題沒有送到判定引擎。',
    next: '請確認後端服務（localhost:2222）是否正在執行，然後重新送出。',
  },
  timeout: {
    head: '後端逾時未回應',
    cause: '請求已送達，但等待超過時限仍未拿到判定結果。',
    next: '後端可能正在啟動或負載過高，請稍候再送出一次。',
  },
  http: {
    head: '後端拒絕了這次請求',
    cause: '後端有回應，但回傳的是錯誤狀態，代表請求本身沒有通過後端檢查。',
    next: '若持續發生，請檢查後端記錄；這不是重新送出就能解決的問題。',
  },
  client: {
    head: '前端無法解析後端回應',
    cause: '後端其實正常回覆了判定結果，是這個頁面在轉換顯示格式時出錯。',
    next: '後端服務不需要重啟。這是前端的缺陷，請回報這段錯誤訊息。',
  },
}

function ErrorCard({ message, failure }: { message: string; failure: ConsultFailureKind }) {
  const copy = FAILURE_COPY[failure] ?? FAILURE_COPY.client
  return (
    <div className="live__turn">
      <section className="live__error">
        <header className="live__error-head">
          <IconAlert size={20} /> 這次沒有拿到真實判定
        </header>
        <div className="live__error-body stack gap-3">
          <p>
            <b>{copy.head}</b>，所以<b>這一題沒有答案</b>。
            本頁刻意不使用任何預先準備好的內容，拿罐頭答案冒充真實判定，
            比沒有答案更危險。
          </p>
          <p>{copy.cause}</p>
          <p className="mono muted">{message}</p>
          <p className="muted">{copy.next}</p>
        </div>
      </section>
    </div>
  )
}

/* ================================================================== *
 * 回覆卡：依狀態渲染
 * ================================================================== */

function AnswerCard({ data }: { data: ConsultResponse }) {
  const [showPassport, setShowPassport] = useState(false)
  const state = data.gate_state
  const m = GATE_META[state]
  const p = data.passport
  const claims = p?.claims ?? []
  const verified = claims.filter((c) => c.verified)

  const raw = data as unknown as Record<string, unknown>
  const dangers = Array.isArray(raw.danger_signs) ? (raw.danger_signs as string[]) : []
  const messages = Array.isArray(raw.messages) ? (raw.messages as string[]) : []
  const blocked = Array.isArray(raw.blocked_output_types) ? (raw.blocked_output_types as string[]) : []
  const halted = Boolean(raw.product_retrieval_halted)

  // 後端這一次實際採用的物種（可能來自使用者指定，也可能由描述推斷）。
  // 顯示出來讓飼主能當場察覺判斷前提有沒有搞錯 —— 貓狗用藥安全差異極大。
  const scope = (p as unknown as Record<string, unknown>)?.applicable_scope as
    | Record<string, unknown> | undefined
  const usedSpecies = scope?.species === 'cat' || scope?.species === 'dog'
    ? (scope.species as 'cat' | 'dog')
    : null

  return (
    <div className="live__turn live__turn--ai">
      <div className="live__who"><IconShield size={14} /> VetLink AI</div>

      <section className="live__answer" data-state={state}>
        {/* 狀態頭：四重編碼：色彩 + 字符 + 圖示 + 中文標籤 */}
        <header className="live__answer-head">
          <span className="live__answer-icon" aria-hidden>{m.icon({ size: 24 })}</span>
          <div className="live__answer-titles">
            <span className="live__answer-code">{m.code} · {m.glyph}</span>
            <span className="live__answer-label">{m.label}</span>
          </div>
          {p?.audit_id && <span className="live__answer-audit">{p.audit_id}</span>}
        </header>

        <div className="live__answer-body stack gap-4">
          {data.headline_zh && <p className="live__headline">{data.headline_zh}</p>}

          {usedSpecies && (
            <p className="live__basis">
              本次以<b>{SPECIES_LABEL[usedSpecies]}</b>的安全規則判定。
              若判斷的動物種類不對，請在上方選擇正確物種後重新提問。
            </p>
          )}

          {/* 紅色：先講停下來這件事 */}
          {state === 'RED' && halted && (
            <div className="live__halt">
              <div className="live__halt-head">
                <IconStop size={19} /> 已停止產品檢索
                <span className="live__halt-stamp">RETRIEVAL HALTED</span>
              </div>
              <p className="live__halt-body">
                {p?.refusal_detail_zh
                  ?? '本次觸發急症規則，系統在檢索任何產品資訊前即停止流程。'}
              </p>
            </div>
          )}

          {/* 系統訊息 */}
          {messages.length > 0 && (
            <div className="live__msgs">
              {messages.map((t, i) => (
                <p className="live__msg" key={i}>{t}</p>
              ))}
            </div>
          )}

          {/* 危險徵兆 */}
          {dangers.length > 0 && (
            <section className="live__danger">
              <header className="live__danger-head"><IconAlert size={17} /> 危險徵兆，出現任一項請立即就醫</header>
              <ul className="live__danger-list">
                {dangers.map((t, i) => <li key={i}>{t}</li>)}
              </ul>
            </section>
          )}

          {/* 綠色：可點擊溯源的已驗證衛教 */}
          {verified.length > 0 && (
            <section className="stack gap-3">
              <div className="live__section-head">
                <IconCheck size={17} />
                經審核的衛教與觀察事項
                <span className="live__count">{verified.length} 項主張皆有來源</span>
              </div>
              <p className="muted">點任一項可展開支持它的原始段落、版本與有效期限。</p>
              <div className="stack gap-2">
                {verified.map((c) => (
                  <ClaimButton key={c.claim_id} claim={c} passages={p.passages} />
                ))}
              </div>
            </section>
          )}

          {/* 紅色轉介行動 */}
          {state === 'RED' && (
            <div className="live__referral">
              <b>下一步：立即前往可收治急診的動物醫院。</b>
              <span>不要在家自行給藥或等待觀察。前往時可截圖本頁，並告知獸醫症狀開始的時間。</span>
            </div>
          )}

          {/* 飼主端被擋下的輸出類型：讓拒答成為有目的的結果，而非死路 */}
          {blocked.length > 0 && (
            <details className="live__blocked">
              <summary>
                <IconBan size={15} /> 本次<b>依規定不會顯示</b>的內容（{blocked.length} 類）
              </summary>
              <p className="muted">
                以下輸出類型在飼主模式一律遮蔽。這不是系統故障，而是提案 §5.1 的角色權限邊界：
                處方藥依法須由執業獸醫師診斷後開具處方，始得販賣及使用。
              </p>
              <div className="live__blocked-tags">
                {blocked.map((b) => (
                  <span className="live__blocked-tag" key={b}>{BLOCKED_LABEL_ZH[b] ?? b}</span>
                ))}
              </div>
            </details>
          )}

          {/* 這次從文件庫看了哪些、又為什麼沒看其他的 */}
          <RetrievalTraceBlock trace={data.retrieval} />

          {/* 語言轉譯揭露：文字被 AI 改寫過就必須說，不能讓飼主以為看到的是原文 */}
          <TranslationNote status={raw.llm_translation as TranslationStatus | undefined} />

          {/* 回答護照 */}
          {p?.audit_id && (
            <div className="stack gap-3">
              <button
                type="button"
                className="btn live__passport-btn"
                aria-expanded={showPassport}
                onClick={() => setShowPassport((v) => !v)}
              >
                <IconList size={17} />
                {showPassport ? '收合回答護照' : '查看這次回答的完整證明（回答護照）'}
                <span aria-hidden>{showPassport ? '▾' : '▸'}</span>
              </button>
              {showPassport && <AnswerPassportCard passport={p} />}
            </div>
          )}
        </div>
      </section>
    </div>
  )
}

/* ================================================================== *
 * 檢索軌跡
 *
 * 回答護照回答「這句話出自哪一段」；這一區回答的是另一個問題：
 * 「文件庫裡還有什麼，系統為什麼沒講？」
 *
 * 沒有後者，「只講有來源的話」無法被反證 —— 使用者看不到被略過的部分，
 * 也就無從判斷系統是挑對了、還是根本沒看到。因此排除清單與候選清單
 * 一樣重要，兩邊都要列，而且要列出原因。
 * ================================================================== */

function RetrievalTraceBlock({ trace }: { trace?: RetrievalTrace }) {
  if (!trace) return null
  const c = trace.counts
  const funnel = [
    { n: c.library, label: '文件庫總段落' },
    { n: c.candidates, label: '本次檢索到' },
    { n: c.claims, label: '成為主張' },
    { n: c.displayed, label: '實際講出來' },
  ]
  return (
    <details className="live__trace">
      <summary>
        <IconSearch size={15} />
        這次從<b>{c.library}</b> 段文件庫裡看了 <b>{c.candidates}</b> 段，講出 <b>{c.displayed}</b> 段
      </summary>
      <div className="live__trace-body">
        <div className="live__funnel">
          {funnel.map((f, i) => (
            <span key={f.label} style={{ display: 'inline-flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
              <span className="live__funnel-step">
                <span className="live__funnel-n">{f.n}</span> {f.label}
              </span>
              {i < funnel.length - 1 && <span className="live__funnel-arrow" aria-hidden>→</span>}
            </span>
          ))}
        </div>

        <p className="muted">
          檢索方式：{trace.method_zh}。
          本次判定情境為 <b>{trace.scenarios.join('、') || '未分類'}</b>
          {trace.species && `，物種 ${SPECIES_LABEL[trace.species as 'cat' | 'dog'] ?? trace.species}`}。
          一次回答最多產生 {trace.claim_limit} 項主張。
        </p>

        <div>
          <div className="live__trace-sub">檢索到的段落（{trace.candidates.length}）</div>
          {trace.candidates.map((p) => (
            <div className="live__trace-row" key={p.passage_id}>
              <span className="live__trace-stage" data-stage={p.stage}>{p.stage_zh}</span>
              <span className="mono">{p.passage_id}</span>
              {p.claim_id && <span className="mono muted">{p.claim_id}</span>}
              <span className="live__trace-text">{p.text}</span>
            </div>
          ))}
        </div>

        {trace.excluded.length > 0 && (
          <div>
            <div className="live__trace-sub">文件庫裡沒有被取用的段落（{trace.excluded.length}）</div>
            {trace.excluded.map((e) => (
              <div className="live__trace-row" key={e.passage_id}>
                <span className="live__trace-stage" data-stage="candidate">未取用</span>
                <span className="mono">{e.passage_id}</span>
                <span className="live__trace-text">{e.reason_zh}</span>
              </div>
            ))}
          </div>
        )}

        <p className="muted">
          完整文件庫內容可在「文件庫」分頁查看，段落編號可直接對照。
        </p>
      </div>
    </details>
  )
}

/**
 * 衛教語言轉譯的揭露。
 *
 * 後端可選擇性讓 LLM 改寫已審核段落，讓句子更好讀。改寫過的文字仍然
 * 綁在同一個來源段落上（護照裡的引用不變），但飼主有權知道自己讀到的
 * 是原文還是改寫版 —— 這與本頁「不拿罐頭答案冒充真實判定」是同一個原則。
 * 轉譯未啟用時 rewritten_count 為 0，此區塊不顯示。
 */
interface TranslationStatus {
  total_passages: number
  rewritten_count: number
  fallback_count: number
}

function TranslationNote({ status }: { status?: TranslationStatus }) {
  if (!status || !status.rewritten_count) return null
  return (
    <p className="muted live__basis">
      本次有 <b>{status.rewritten_count} / {status.total_passages}</b> 段衛教文字經 AI 改寫為更好讀的說法。
      改寫後仍須通過來源涵蓋度檢查與角色政策掃描，未通過者已退回原文；
      展開回答護照可看到每一段的原始出處與版本。
    </p>
  )
}

/** blocked_output_types → 中文說法 */
const BLOCKED_LABEL_ZH: Record<string, string> = {
  dosage: '劑量',
  owner_facing_dosage: '飼主端劑量',
  prescription_dosage: '處方藥劑量',
  prescription_product: '處方藥產品',
  purchase_link: '購買連結',
  diagnosis: '疾病確診',
  home_medication: '居家自行用藥',
  medication_change_instruction: '自行停換藥指示',
  human_drug_dosing: '人用藥劑量',
  cross_species_dosing: '跨物種用藥換算',
  induce_vomiting_instruction: '自行催吐指示',
}

/* ================================================================== *
 * 黃色追問表單 — 提案 §4「黃色｜資訊不足」的真實運作
 * ================================================================== */

function FollowUpForm({
  questions, answers, onChange, complete, onSubmit,
}: {
  questions: FollowUpQuestion[]
  answers: RawAnswers
  onChange: (field: string, value: string) => void
  complete: boolean
  onSubmit: () => void
}) {
  const done = questions.filter((q) => isAnswered(q.field, answers)).length

  return (
    <section className="live__followup" aria-label="必要追問">
      <header className="live__followup-head">
        <IconQuestion size={20} />
        <div className="stack gap-1">
          <b>
            {done >= questions.length
              ? '必要資訊已補齊，可以重新判定了'
              : `還差 ${questions.length - done} 項資訊，系統才有資格回答`}
          </b>
          <span className="muted">
            這些題目由規則庫固定提供，不由生成模型即興產生，同樣的缺漏一定得到同樣的題目。
          </span>
        </div>
        <span className="live__followup-count">{done} / {questions.length}</span>
      </header>

      <div className="live__followup-body stack gap-4">
        {questions.map((q, i) => (
          <FieldControl
            key={q.field}
            index={i + 1}
            question={q}
            value={answers[q.field] ?? ''}
            onChange={(v) => onChange(q.field, v)}
          />
        ))}

        <div className="live__followup-foot">
          <button
            type="button"
            className="btn btn--primary btn--lg"
            onClick={onSubmit}
            disabled={!complete}
          >
            補齊後重新判定 <IconArrowRight size={18} />
          </button>
          <span className="muted">
            {complete
              ? '資料資格檢查可以重跑了，依補齊後的內容，狀態可能轉為綠色（可見衛教）或紅色（急症轉介）。'
              : '在必要欄位補齊之前，系統不會輸出任何衛教或產品資訊，也不會用推測值代替你的答案。'}
          </span>
        </div>
      </div>
    </section>
  )
}

function FieldControl({
  index, question, value, onChange,
}: {
  index: number
  question: FollowUpQuestion
  value: string
  onChange: (v: string) => void
}) {
  const spec = specFor(question.field)
  const id = `fu-${question.field}`

  return (
    <div className="live__q">
      <label className="live__q-label" htmlFor={id}>
        <span className="live__q-n" aria-hidden>{index}</span>
        <span>{question.question_zh}</span>
      </label>

      <div className="live__q-control">
        {spec.kind === 'number' && (
          <span className="live__num">
            <input
              id={id}
              className="live__input"
              type="number"
              inputMode="decimal"
              min={0}
              step="any"
              placeholder={spec.placeholder}
              value={value}
              onChange={(e) => onChange(e.target.value)}
            />
            {spec.unit && <span className="live__unit">{spec.unit}</span>}
          </span>
        )}

        {spec.kind === 'yesno' && (
          <div className="live__opts" role="group" aria-labelledby={id}>
            {([['yes', spec.yes ?? '是'], ['no', spec.no ?? '否']] as const).map(([v, label]) => (
              <button
                key={v}
                type="button"
                className="opt"
                aria-pressed={value === v}
                onClick={() => onChange(value === v ? '' : v)}
              >
                {label}
              </button>
            ))}
          </div>
        )}

        {spec.kind === 'select' && (
          <div className="live__opts" role="group" aria-labelledby={id}>
            {(spec.options ?? []).map((o) => (
              <button
                key={o.value}
                type="button"
                className="opt"
                aria-pressed={value === o.value}
                onClick={() => onChange(value === o.value ? '' : o.value)}
              >
                {o.label}
              </button>
            ))}
          </div>
        )}

        {spec.kind === 'text' && (
          <input
            id={id}
            className="live__input"
            type="text"
            placeholder={spec.placeholder}
            value={value}
            onChange={(e) => onChange(e.target.value)}
          />
        )}
      </div>

      {spec.hint && <p className="live__q-hint">{spec.hint}</p>}
      {isOptionalBlank(question.field) && (
        <p className="live__q-hint">
          <b>留白即代表「目前沒有在使用任何藥物或保健品」</b>，這是一個明確的答案，不會讓判定卡住。
        </p>
      )}
      <p className="live__q-meta">
        欄位代碼 <span className="mono">{question.field}</span>
        {question.field === 'current_medications' && '｜沒有在用藥請直接留空送出'}
      </p>
    </div>
  )
}
