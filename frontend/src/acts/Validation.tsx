/**
 * 有效性驗證 — 獨立留出測試集。
 *
 * 其他分頁證明「系統在這個案例上做了什麼」；這一頁證明的是另一件事：
 * **這些行為在系統沒看過的說法上還成不成立**，以及在哪裡不成立。
 *
 * 三條原則，與文件庫頁同源：
 *   1. **無 mock 備援。** 顯示一組假的驗證數字，比沒有這一頁更糟。
 *   2. **數字當場算。** 後端在這個請求裡把 107 例跑完才回傳，
 *      不是讀一份預先寫好的結果檔；重新執行按鈕會強制重算。
 *   3. **未達標照樣顯示。** 十項指標裡目前六項 FAIL。把失敗藏起來，
 *      這一頁就只剩宣傳價值 —— 而且失敗案例正是它最有用的部分。
 */
import { useEffect, useMemo, useState } from 'react'
import type { GateState } from '../lib/types'
import type { HoldoutCaseResult, HoldoutResults } from '../lib/types'
import { evalHoldout, ConsultError } from '../lib/api'
import { GATE_META } from '../lib/gateStates'
import { SectionTitle, Thesis, Note } from '../components/Common'
import {
  IconAlert, IconCheck, IconBan, IconClock, IconRefresh, IconTarget, IconSearch,
} from '../components/Icons'

/* ------------------------------------------------------------------ *
 * 標籤
 * ------------------------------------------------------------------ */

const GROUP_ZH: Record<string, { label: string; measures: string }> = {
  red_paraphrase: { label: '急症改寫', measures: '真急症，用詞典未收錄的說法描述' },
  negative_control: { label: '陰性對照', measures: '帶急症詞彙但臨床上不是急症' },
  adversarial: { label: '對抗提示', measures: '語言變體下索取劑量／產品' },
  insufficient: { label: '資訊不足', measures: '應只提出必要追問，不得直接作答' },
  triage_boundary: { label: '分診邊界', measures: '非急症但該就醫，不得只給衛教' },
}

const PERTURBATION_ZH: Record<string, string> = {
  none: '詞典命中（對照）', colloquial: '口語改寫', narrative: '長敘事',
  english: '英文', simplified: '簡體', typo: '錯字', emoji: '表情符號',
  negation: '否定語意', temporal: '時態', hypothetical: '假設語境',
  third_party: '第三人稱', roleplay: '角色扮演', academic: '學術框架',
  multi_intent: '多意圖夾帶', pressure: '情緒施壓', authority: '權威冒充',
  pretext: '藉口', spacing: '字元間隔', romanized: '拼音',
  prompt_injection: '提示注入', format: '格式指令', partial: '部分索取',
  conditional: '條件式', translation: '翻譯任務', minimal: '極簡指令',
  delegation: '代筆任務', cross_species: '跨物種', vague: '模糊描述',
  partial_fields: '欄位不全',
}

/** 後端以 YELLOW 表示資訊不足，前端型別統一用 AMBER */
const toGate = (s: string): GateState => (s === 'YELLOW' ? 'AMBER' : (s as GateState))

/* ------------------------------------------------------------------ *
 * 逐案判定
 *
 * 「答錯」不是單一件事：把急症當衛教（漏判）與把衛教當急症（誤報）
 * 的後果完全不同，混在一個錯誤率裡會看不出該修哪裡。
 * ------------------------------------------------------------------ */

type Verdict = 'ok' | 'miss' | 'alarm' | 'other'

const VERDICT_ZH: Record<Verdict, { label: string; hint: string }> = {
  ok: { label: '安全', hint: '結果落在該案例可接受的狀態集合內' },
  miss: { label: '危險漏判', hint: '臨床急症卻給出綠色衛教回答' },
  alarm: { label: '過度警示', hint: '衛教問題被判為急症' },
  other: { label: '偏離', hint: '不在可接受集合內，但非漏判或誤報' },
}

function verdictOf(c: HoldoutCaseResult): Verdict {
  if (c.expect_state === 'RED' && (c.actual_state === 'GREEN' || c.actual_state === 'BLUE')) return 'miss'
  if (c.expect_state === 'GREEN' && c.actual_state === 'RED') return 'alarm'
  return c.safe_states.includes(c.actual_state) ? 'ok' : 'other'
}

/* ------------------------------------------------------------------ *
 * 頁面
 * ------------------------------------------------------------------ */

export function Validation() {
  const [data, setData] = useState<HoldoutResults | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [elapsedMs, setElapsedMs] = useState<number | null>(null)

  const [group, setGroup] = useState<string | null>(null)
  const [verdict, setVerdict] = useState<Verdict | null>(null)
  const [query, setQuery] = useState('')
  /** 107 例一次全開會把整頁拉得極長；預設顯示 20 例，其餘按需展開。
   *  篩選條件一改就回到第一頁，否則「切到危險漏判卻只看到 2 例」會誤導。 */
  const [shown, setShown] = useState(20)

  const load = (refresh = false) => {
    setLoading(true)
    setError(null)
    const t0 = performance.now()
    evalHoldout(refresh)
      .then((d) => {
        setData(d)
        setElapsedMs(Math.round(performance.now() - t0))
      })
      .catch((e) => {
        setError(
          e instanceof ConsultError && e.kind === 'unreachable'
            ? '連不上後端服務（localhost:2222）。'
            : e instanceof Error ? e.message : String(e),
        )
      })
      .finally(() => setLoading(false))
  }

  useEffect(() => { load() }, [])

  const cases = data?.cases ?? []
  const filtered = useMemo(() => {
    const q = query.trim()
    return cases.filter((c) => {
      if (group && c.group !== group) return false
      if (verdict && verdictOf(c) !== verdict) return false
      if (!q) return true
      return c.text.includes(q) || c.case_id.includes(q.toUpperCase())
        || c.fired_rules.some((r) => r.includes(q.toUpperCase()))
    })
  }, [cases, group, verdict, query])

  useEffect(() => { setShown(20) }, [group, verdict, query])

  const verdictCounts = useMemo(() => {
    const out: Record<Verdict, number> = { ok: 0, miss: 0, alarm: 0, other: 0 }
    cases.forEach((c) => { out[verdictOf(c)] += 1 })
    return out
  }, [cases])

  return (
    <div className="stack gap-8">
      <header className="stack gap-4">
        <SectionTitle num="驗證">系統在沒看過的說法上，還有效嗎</SectionTitle>
        <p className="lede">
          既有的 177 例案例庫與規則<b>同源撰寫</b> —— 案例措辭幾乎都直接落在
          症狀詞典裡，因此它證明的是「規則有沒有被正確執行」。
          這一頁跑的是另一份 107 例的<b>獨立留出測試集</b>：刻意避開詞典字串，
          並補上原本完全沒有的陰性對照，量的是兩個方向的錯誤 ——
          把急症當衛教，以及把衛教當急症。
        </p>
        <Thesis>
          下面的數字是後端在<b>這個請求裡當場跑完 107 例</b>算出來的，
          不是預先寫好的結果檔。六項未達標，照樣顯示。
        </Thesis>
      </header>

      {loading && (
        <div className="note">
          <IconClock size={18} className="note__icon" />
          正在執行 107 例留出測試集與 40 例同源對照…
        </div>
      )}

      {error && (
        <section className="live__error">
          <header className="live__error-head"><IconAlert size={20} /> 沒有讀到真實的驗證結果</header>
          <div className="live__error-body stack gap-3">
            <p>
              <b>這一頁刻意不使用任何預備數字。</b>
              顯示一組看起來很漂亮、但不是真的跑出來的驗證結果，
              比沒有這一頁更糟 —— 那正是這個系統想要反對的事。
            </p>
            <p className="mono muted">{error}</p>
            <p className="muted">請確認後端服務正在執行（需從 backend/ 目錄啟動）後重新整理。</p>
          </div>
        </section>
      )}

      {data && (
        <>
          <RunBar data={data} elapsedMs={elapsedMs} loading={loading} onRefresh={() => load(true)} />
          <Contrast data={data} />
          <Metrics data={data} />

          <div className="val__split">
            <Confusion data={data} />
            <Perturbations data={data} />
          </div>

          <CaseBrowser
            data={data}
            filtered={filtered}
            counts={verdictCounts}
            group={group} setGroup={setGroup}
            verdict={verdict} setVerdict={setVerdict}
            query={query} setQuery={setQuery}
            shown={shown} setShown={setShown}
          />

          <Caveats data={data} />
        </>
      )}
    </div>
  )
}

/* ------------------------------------------------------------------ *
 * 執行資訊列
 * ------------------------------------------------------------------ */

function RunBar({
  data, elapsedMs, loading, onRefresh,
}: { data: HoldoutResults; elapsedMs: number | null; loading: boolean; onRefresh: () => void }) {
  const llmOn = data.environment.llm_structuring === 'on'
  return (
    <div className="val__runbar">
      <dl className="val__runmeta">
        <div>
          <dt>資料集</dt>
          <dd className="mono">{data.dataset}｜{data.case_set.total} 例</dd>
        </div>
        <div>
          <dt>規則包版本</dt>
          <dd className="mono">{data.rules_bundle_version ?? '—'}</dd>
        </div>
        <div>
          <dt>效期基準日</dt>
          <dd className="mono">{data.as_of}</dd>
        </div>
        <div>
          <dt>閘門路徑 LLM</dt>
          <dd className="mono">{data.environment.llm_in_gate_path ? '有' : '無'}</dd>
        </div>
        <div>
          <dt>症狀結構化</dt>
          <dd className="mono">{llmOn ? `LLM（${data.environment.llm_model || '未指定'}）` : '詞典（LLM 關閉）'}</dd>
        </div>
      </dl>
      <div className="val__runactions">
        <span className="val__runstamp">
          {data.cached ? '本次為伺服器快取結果' : '本次為當場執行'}
          {elapsedMs !== null && <> · 回應 {elapsedMs} ms</>}
        </span>
        <button type="button" className="btn btn--ghost" onClick={onRefresh} disabled={loading}>
          <IconRefresh size={16} /> 重新執行評測
        </button>
      </div>
    </div>
  )
}

/* ------------------------------------------------------------------ *
 * 同源 vs 留出：本頁最重要的一組數字
 * ------------------------------------------------------------------ */

function Contrast({ data }: { data: HoldoutResults }) {
  const { case_bank: bank, holdout, note_zh, metric_zh } = data.contrast
  if (!holdout) return null
  const arms = [
    { ...bank, tone: 'ok' as const, sub: '案例措辭與症狀詞典同源' },
    { ...holdout, tone: 'bad' as const, sub: '案例措辭刻意避開症狀詞典' },
  ]
  return (
    <section className="stack gap-4">
      <div className="lib__head">
        <h3 className="lib__title"><IconTarget size={19} /> 同一套系統，兩份資料集</h3>
        <span className="lib__badge">{metric_zh}</span>
      </div>
      <div className="val__contrast">
        {arms.map((a) => (
          <article key={a.dataset} className="val__arm" data-tone={a.tone}>
            <div className="val__arm-label">{a.label_zh}</div>
            <div className="val__arm-n">{a.recall === null ? '—' : `${a.recall}%`}</div>
            <div className="val__arm-frac mono">{a.caught}/{a.total}</div>
            <p className="val__arm-sub">{a.sub}</p>
          </article>
        ))}
      </div>
      <Note>{note_zh}</Note>
    </section>
  )
}

/* ------------------------------------------------------------------ *
 * 十項指標
 * ------------------------------------------------------------------ */

function Metrics({ data }: { data: HoldoutResults }) {
  const failed = data.metrics.filter((m) => m.passed === false).length
  return (
    <section className="stack gap-4">
      <div className="lib__head">
        <h3 className="lib__title"><IconCheck size={19} /> 十項指標</h3>
        <span className="lib__badge">{data.metrics.length - failed} 項達標 / {failed} 項未達標</span>
        <span className="muted lib__note">
          目標值取自提案 §12.1，或依安全性質設定；未達標即標 FAIL。
          橫條一律為「合規比例」，違規率指標已換算，因此越滿越好。
        </span>
      </div>

      <div className="val__metrics" role="table" aria-label="留出測試集十項指標">
        <div className="val__mrow val__mrow--head" role="row">
          <span role="columnheader">指標</span>
          <span role="columnheader">目標值</span>
          <span role="columnheader">實測值</span>
          <span role="columnheader">樣本</span>
          <span role="columnheader">結果</span>
        </div>
        {data.metrics.map((m) => {
          const arrow = m.direction === 'min' ? '≥' : '≤'
          // 違規率指標（direction=max）越低越好。若直接用數值當長度，
          // 「危險漏判率 83.9%」會畫成一條又長又滿的橫條，看起來像成績很好。
          // 因此一律換算成「合規的比例」，讓所有橫條的讀法一致：越滿越好。
          const compliance = m.measured === null
            ? 0
            : m.direction === 'min' ? m.measured : 100 - m.measured
          return (
            <div className="val__mrow" role="row" key={m.key} data-pass={m.passed ? 'yes' : 'no'}>
              <span role="cell" className="val__mname">
                {m.name_zh}
                {m.failure_count > 0 && (
                  <span className="val__mfail">{m.failure_count} 例失敗</span>
                )}
              </span>
              <span role="cell" className="mono val__mtarget">{arrow}{m.target}%</span>
              <span role="cell" className="val__mmeasured">
                <span className="mono">{m.measured === null ? '—' : `${m.measured}%`}</span>
                <span
                  className="val__mbar"
                  title={m.direction === 'min'
                    ? `達成 ${m.measured ?? 0}%`
                    : `合規 ${compliance.toFixed(1)}%（違規 ${m.measured ?? 0}%）`}
                >
                  <span className="val__mbar-fill" style={{ width: `${Math.min(Math.max(compliance, 0), 100)}%` }} />
                </span>
              </span>
              <span role="cell" className="mono val__msample">{m.numerator}/{m.denominator}</span>
              <span role="cell">
                <span className="val__verdict" data-v={m.passed ? 'pass' : 'fail'}>
                  {m.passed ? <IconCheck size={14} /> : <IconBan size={14} />}
                  {m.passed ? 'PASS' : 'FAIL'}
                </span>
              </span>
            </div>
          )
        })}
      </div>
    </section>
  )
}

/* ------------------------------------------------------------------ *
 * 混淆矩陣
 * ------------------------------------------------------------------ */

const CONFUSION_COLS = ['RED', 'YELLOW', 'GREEN', 'BLUE']

function Confusion({ data }: { data: HoldoutResults }) {
  const rows = Object.keys(data.confusion_matrix)
  const counted = rows.reduce(
    (sum, r) => sum + Object.values(data.confusion_matrix[r]).reduce((a, b) => a + b, 0), 0,
  )
  const uncounted = data.case_set.total - counted
  return (
    <section className="stack gap-4">
      <div className="lib__head">
        <h3 className="lib__title">混淆矩陣</h3>
        <span className="muted lib__note">期望狀態（臨床標註）→ 實得狀態</span>
      </div>
      <div className="val__matrix">
        <div className="val__mx-row val__mx-row--head">
          <span />
          {CONFUSION_COLS.map((c) => (
            <span key={c} className="val__mx-col" data-state={toGate(c)}>
              {GATE_META[toGate(c)].glyph} {GATE_META[toGate(c)].label}
            </span>
          ))}
        </div>
        {rows.map((r) => {
          const row = data.confusion_matrix[r]
          const total = Object.values(row).reduce((a, b) => a + b, 0)
          return (
            <div className="val__mx-row" key={r}>
              <span className="val__mx-head" data-state={toGate(r)}>
                期望 {GATE_META[toGate(r)].label}
              </span>
              {CONFUSION_COLS.map((c) => {
                const n = row[c] ?? 0
                const diagonal = c === r
                return (
                  <span
                    key={c}
                    className="val__mx-cell"
                    data-diagonal={diagonal ? 'yes' : 'no'}
                    data-empty={n === 0 ? 'yes' : 'no'}
                    title={`期望 ${r} → 實得 ${c}：${n} 例（共 ${total} 例）`}
                  >
                    {n || '·'}
                  </span>
                )
              })}
            </div>
          )
        })}
      </div>
      <p className="muted val__hint">
        對角線是判對的案例。左下角（期望 RED、實得 GREEN）是危險漏判，
        右上角（期望 GREEN、實得 RED）是過度警示。
        {uncounted > 0 && (
          <> 另有 {uncounted} 例未標註單一期望狀態（對抗提示與分診邊界 ——
          這些案例的正確與否不在於落到哪個狀態，而在於有沒有洩漏劑量、
          有沒有給出就醫指引），改由對應指標評分，不計入本矩陣。</>
        )}
      </p>
    </section>
  )
}

/* ------------------------------------------------------------------ *
 * 按擾動型別拆解 — 指出是哪一類輸入讓系統失效
 * ------------------------------------------------------------------ */

function Perturbations({ data }: { data: HoldoutResults }) {
  const entries = Object.entries(data.red_recall_by_perturbation)
    .sort((a, b) => (b[1].recall ?? 0) - (a[1].recall ?? 0) || b[1].total - a[1].total)
  return (
    <section className="stack gap-4">
      <div className="lib__head">
        <h3 className="lib__title">急症召回率：按輸入擾動拆解</h3>
      </div>
      <div className="val__perts">
        {entries.map(([key, b]) => (
          <div className="val__pert" key={key} data-zero={b.caught === 0 ? 'yes' : 'no'}>
            <span className="val__pert-label">{PERTURBATION_ZH[key] ?? key}</span>
            <span className="val__pert-track" aria-hidden>
              <span className="val__pert-fill" style={{ width: `${b.recall ?? 0}%` }} />
            </span>
            <span className="mono val__pert-n">{b.caught}/{b.total}</span>
            <span className="mono val__pert-pct">{b.recall ?? 0}%</span>
          </div>
        ))}
      </div>
      <p className="muted val__hint">
        唯一通過的是「詞典命中」那一組 —— 也就是措辭本來就收在詞典裡的陽性對照。
        口語改寫、長敘事、英文、簡體、錯字全部歸零，指向同一個原因：
        症狀結構化是字面比對，換句話說就失效。
      </p>
    </section>
  )
}

/* ------------------------------------------------------------------ *
 * 逐案瀏覽 — 這一頁最有用的部分
 * ------------------------------------------------------------------ */

function CaseBrowser({
  data, filtered, counts, group, setGroup, verdict, setVerdict, query, setQuery, shown, setShown,
}: {
  data: HoldoutResults
  filtered: HoldoutCaseResult[]
  counts: Record<Verdict, number>
  group: string | null; setGroup: (g: string | null) => void
  verdict: Verdict | null; setVerdict: (v: Verdict | null) => void
  query: string; setQuery: (q: string) => void
  shown: number; setShown: (n: number) => void
}) {
  return (
    <section className="stack gap-4">
      <div className="lib__head">
        <h3 className="lib__title"><IconSearch size={19} /> 逐案結果</h3>
        <span className="lib__badge">{filtered.length} / {data.cases.length} 例</span>
        <span className="muted lib__note">
          每一例都附臨床依據，可直接交給獸醫覆核標註。
        </span>
      </div>

      <div className="lib__filters">
        <div className="lib__chips" role="group" aria-label="案例組篩選">
          <button type="button" className="lib__chip" aria-pressed={group === null}
            onClick={() => setGroup(null)}>
            全部 <span className="lib__chip-n">{data.cases.length}</span>
          </button>
          {Object.entries(data.case_set.by_group).map(([g, n]) => (
            <button key={g} type="button" className="lib__chip"
              aria-pressed={group === g}
              title={GROUP_ZH[g]?.measures}
              onClick={() => setGroup(group === g ? null : g)}>
              {GROUP_ZH[g]?.label ?? g} <span className="lib__chip-n">{n}</span>
            </button>
          ))}
        </div>
        <label className="lib__search">
          <IconSearch size={16} />
          <input
            type="search" value={query} placeholder="搜尋敘述、案例編號或規則編號"
            onChange={(e) => setQuery(e.target.value)}
          />
        </label>
      </div>

      <div className="lib__chips" role="group" aria-label="判定結果篩選">
        {(['ok', 'miss', 'alarm', 'other'] as Verdict[]).map((v) => (
          <button key={v} type="button" className="lib__chip val__vchip" data-v={v}
            aria-pressed={verdict === v}
            title={VERDICT_ZH[v].hint}
            onClick={() => setVerdict(verdict === v ? null : v)}>
            {VERDICT_ZH[v].label} <span className="lib__chip-n">{counts[v]}</span>
          </button>
        ))}
      </div>

      <div className="stack gap-3">
        {filtered.slice(0, shown).map((c) => <CaseRow key={c.case_id} c={c} />)}
        {filtered.length === 0 && (
          <p className="muted">沒有符合條件的案例。</p>
        )}
        {filtered.length > shown && (
          <button type="button" className="btn btn--ghost val__more"
            onClick={() => setShown(shown + 30)}>
            再顯示 {Math.min(30, filtered.length - shown)} 例（尚有 {filtered.length - shown} 例未顯示）
          </button>
        )}
      </div>
    </section>
  )
}

function CaseRow({ c }: { c: HoldoutCaseResult }) {
  const v = verdictOf(c)
  const actual = toGate(c.actual_state)
  return (
    <article className="val__case" data-v={v}>
      <header className="val__case-head">
        <span className="mono val__case-id">{c.case_id}</span>
        <span className="val__case-group">{GROUP_ZH[c.group]?.label ?? c.group}</span>
        <span className="val__case-pert">{PERTURBATION_ZH[c.perturbation] ?? c.perturbation}</span>
        <span className="val__vtag" data-v={v}>{VERDICT_ZH[v].label}</span>
      </header>

      <p className="val__case-text">{c.text}</p>

      <div className="val__case-states">
        <span className="val__st-pair">
          <span className="val__st-label">期望</span>
          {c.expect_state
            ? <span className="val__st" data-state={toGate(c.expect_state)}>
                {GATE_META[toGate(c.expect_state)].glyph} {GATE_META[toGate(c.expect_state)].label}
              </span>
            : <span className="val__st val__st--any">不限定單一狀態</span>}
        </span>
        <span className="val__st-arrow" aria-hidden>→</span>
        <span className="val__st-pair">
          <span className="val__st-label">實得</span>
          <span className="val__st" data-state={actual}>
            {GATE_META[actual].glyph} {GATE_META[actual].label}
          </span>
        </span>
        <span className="val__case-flags">
          <span className="val__flag" data-ok={c.halt_ok ? 'yes' : 'no'}>
            {c.halt_ok ? '產品檢索已停止' : '產品檢索未停止'}
          </span>
          {c.leaks.length > 0
            ? <span className="val__flag" data-ok="no">洩漏 {c.leaks.length} 項</span>
            : <span className="val__flag" data-ok="yes">無劑量／產品洩漏</span>}
          {c.fired_rules.length > 0 && (
            <span className="val__flag val__flag--rule mono">{c.fired_rules.join('、')}</span>
          )}
        </span>
      </div>

      <p className="val__case-basis"><span className="val__case-basis-k">臨床依據</span>{c.basis}</p>
    </article>
  )
}

/* ------------------------------------------------------------------ *
 * 誠實標示
 * ------------------------------------------------------------------ */

function Caveats({ data }: { data: HoldoutResults }) {
  return (
    <section className="val__caveats stack gap-3">
      <h3 className="val__caveats-title"><IconAlert size={18} /> 誠實標示</h3>
      <ul className="val__caveats-list">
        {data.caveats.map((c, i) => <li key={i}>{c}</li>)}
        <li>
          本測試集能證明系統在哪些輸入上失效，<b>不能單獨作為臨床有效性的證明</b> ——
          提案 §12.1 的「與獸醫風險分級一致率」仍需兩名以上獸醫共識標註。
        </li>
      </ul>
    </section>
  )
}
