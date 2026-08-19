import { useState } from 'react'
import type { CompareArm, CompareResponse, CompareDimensionKey } from '../lib/types'
import { compare } from '../lib/api'
import { COMPARE_QUESTION } from '../mocks'
import { StateBadge } from '../components/StateVisuals'
import { Thesis, SectionTitle, Note, Steps } from '../components/Common'
import {
  IconArrowRight, IconCheck, IconBan, IconAlert, IconDoc, IconStop,
  IconShield, IconClock, IconScale,
} from '../components/Icons'

/**
 * A/B/C 三組對照 (提案 §12.1)。
 *
 * 這一頁的任務只有一個：讓「同一個問題、三種架構」的差異一眼可見。
 * 因此版面刻意做成三欄並排 + 一張維度對照表，而不是三段文章。
 *
 * A、B 為對照組。若其 `is_prerecorded` 為 true（無 API 金鑰時），
 * UI 必須明確標示「預錄範例」—— 絕不把預錄內容呈現為即時模型呼叫。
 */

/** 每組的視覺基調。A/B 借用 RED/AMBER 的警示語彙，C 用 BLUE 的信任語彙。 */
const ARM_TONE: Record<string, { state: 'RED' | 'AMBER' | 'BLUE'; kicker: string }> = {
  A: { state: 'RED', kicker: 'ARM A · BASELINE' },
  B: { state: 'AMBER', kicker: 'ARM B · BASELINE' },
  C: { state: 'BLUE', kicker: 'ARM C · VETLINK AI' },
}

export function Compare() {
  const [data, setData] = useState<CompareResponse | null>(null)
  const [loading, setLoading] = useState(false)

  const run = async () => {
    setLoading(true)
    try {
      setData(await compare({ question_zh: COMPARE_QUESTION }))
    } finally {
      setLoading(false)
    }
  }

  return (
    <div className="stack gap-8">
      <header className="stack gap-4">
        <SectionTitle num="§12.1">安全不是宣稱，而是三組對照測試</SectionTitle>
        <p className="lede">
          提案用三組架構跑<b>完全相同的輸入</b>：A 組是一般 LLM、B 組是單純 RAG、
          C 組是 VetLink AI。差別不在模型有多強（三組都可以用同一個模型），
          而在於<b>系統有沒有能力在生成之前，判斷這次能不能回答</b>。
        </p>
        <Steps
          steps={['同一個飼主問題', 'A 組：直接生成', 'B 組：檢索後生成', 'C 組：先判定資格']}
          current={data ? 3 : 0}
        />
      </header>

      <Thesis>
        別的 AI 告訴你推薦什麼；VetLink 能證明為什麼這次可以推薦，以及為什麼有時候絕對不能推薦。
      </Thesis>

      {/* 輸入 */}
      <section className="prompt">
        <span className="prompt__who">飼主・示範帳號（提案 §十 第一幕旗艦案例）</span>
        <div className="prompt__bubble">{COMPARE_QUESTION}</div>
        {!data && (
          <button
            className="btn btn--primary btn--lg"
            onClick={run}
            disabled={loading}
            style={{ alignSelf: 'flex-start' }}
          >
            {loading ? '三組執行中…' : '以同一輸入執行 A / B / C 三組'}
            {!loading && <IconArrowRight size={18} />}
          </button>
        )}
        {loading && (
          <div className="note">
            <span className="note__icon"><IconClock size={18} /></span>
            A 組直接呼叫模型；B 組先檢索再生成；C 組執行確定性 Evidence Gate。
          </div>
        )}
      </section>

      {data && (
        <>
          {/* 預錄範例揭露：誠實標示優先於畫面美觀 */}
          {data.any_prerecorded && (
            <Note>
              <b>資料揭露：</b>{data.disclaimer_zh}
            </Note>
          )}

          {/* 三欄並排 */}
          <section className="stack gap-4">
            <SectionTitle num="對照">同一個問題，三種架構的實際輸出</SectionTitle>
            <div className="grid-3 armgrid">
              {data.arms.map((a) => <ArmCard key={a.arm} arm={a} />)}
            </div>
          </section>

          {/* 維度對照表：最直接的證據 */}
          <section className="stack gap-4">
            <SectionTitle num="判準">四個關鍵維度</SectionTitle>
            <DimensionTable data={data} />
            <Note>
              「是否提供劑量」對飼主端而言<b>越少越好</b>：依動物用藥品管理法，
              處方藥須經執業獸醫師診斷開立處方後始得販賣及使用。
              A 組的劑量是由本系統既有的<b>角色政策掃描器</b>實際掃出來的，
              不是人工標註，同一支掃描器也用於 C 組，結果為零違規。
            </Note>
          </section>

          {/* 結論 */}
          <section className="verdict" data-state="BLUE" aria-label="對照結論">
            <header className="verdict__top">
              <span className="verdict__glyph" aria-hidden><IconShield size={30} /></span>
              <div className="verdict__titles">
                <div className="verdict__code">CONCLUSION · ◆</div>
                <h2 className="verdict__label">三組對照結論</h2>
              </div>
            </header>
            <div className="verdict__body stack gap-4">
              <p className="verdict__headline">{data.conclusion_zh}</p>
              <div className="grid-3">
                {data.arms.map((a) => (
                  <div className="legend__item" key={a.arm} data-state={ARM_TONE[a.arm].state}>
                    <div className="legend__head">
                      <span className="legend__glyph" aria-hidden>{a.arm}</span>
                      <span className="legend__name t-base">
                        {a.name_zh}
                      </span>
                    </div>
                    <div className="legend__row">{a.verdict_zh}</div>
                  </div>
                ))}
              </div>
            </div>
          </section>
        </>
      )}
    </div>
  )
}

/* ---------------- 單組卡片 ---------------- */

function ArmCard({ arm }: { arm: CompareArm }) {
  const tone = ARM_TONE[arm.arm] ?? ARM_TONE.C
  return (
    <article
      className="legend__item"
      data-state={tone.state}
      aria-label={arm.name_zh}
      style={{ gap: 'var(--sp-3)' }}
    >
      {/* 標頭 */}
      <div className="legend__head" style={{ flexWrap: 'wrap' }}>
        <span className="legend__glyph" aria-hidden>
          {arm.arm === 'C' ? <IconShield size={20} /> : <IconAlert size={20} />}
        </span>
        <span className="legend__name t-md">{arm.name_zh}</span>
      </div>
      <div className="label">{tone.kicker}</div>
      <div className="legend__row ink-2">{arm.subtitle_zh}</div>

      {/* 資料來源標示：預錄 vs 即時，必須誠實 */}
      <div className="row row--tight">
        <span
          className="verbadge"
          style={
            arm.is_prerecorded
              ? { borderColor: 'var(--s-amber)', color: 'var(--s-amber)' }
              : undefined
          }
        >
          {arm.is_prerecorded ? <IconAlert size={13} /> : <IconCheck size={13} />}
          {arm.label_zh}
        </span>
        {arm.is_baseline && (
          <span className="verbadge" style={{ borderColor: 'var(--c-border-strong)' }}>
            對照組
          </span>
        )}
        {arm.gate_state && <StateBadge state={arm.gate_state} size="sm" />}
      </div>

      {/* 架構 */}
      <div className="legend__row">
        <b>架構：</b><span className="mono-xs">
          {arm.architecture_zh}
        </span>
      </div>

      {/* 輸出 */}
      <div className="label">系統輸出</div>
      <div className={arm.arm === 'C' ? 'block block--action' : 'block block--forbid'}>
        <div className="block__body">
          <p className="flat readable">{arm.answer_zh}</p>
          {arm.messages && arm.messages.length > 0 && (
            <div className="stack gap-2" style={{ marginTop: 'var(--sp-3)' }}>
              {arm.messages.map((m, i) => (
                <div className="bullet" key={i}>
                  <span className="bullet__dot" />
                  <span className="t-sm">{m}</span>
                </div>
              ))}
            </div>
          )}
        </div>
      </div>

      {/* 政策違規：A 組的關鍵證據 */}
      {arm.policy_violations.length > 0 && (
        <div className="halted flat">
          <header className="halted__head">
            <IconStop size={18} />
            <span>角色政策掃描結果</span>
            <span className="halted__stamp">VIOLATION</span>
          </header>
          <div className="halted__body">
            <ul className="blocked-list">
              {arm.policy_violations.map((v) => (
                <li className="blocked-row" key={v}>
                  <span className="blocked-row__x" aria-hidden><IconBan size={16} /></span>
                  <span className="blocked-row__text">{v}</span>
                </li>
              ))}
            </ul>
          </div>
        </div>
      )}

      {/* 攔截證據：C 組的關鍵證據 */}
      {arm.product_retrieval_halted && (
        <div className="halted flat">
          <header className="halted__head">
            <IconStop size={18} />
            <span>產品檢索已停止</span>
            <span className="halted__stamp">RETRIEVAL HALTED</span>
          </header>
          <div className="halted__body">
            <p className="halted__reason t-sm">
              {arm.refusal_detail_zh}
            </p>
            {arm.blocked_output_types && arm.blocked_output_types.length > 0 && (
              <>
                <div className="label">本次被攔截的輸出型別</div>
                <ul className="blocked-list">
                  {arm.blocked_output_types.slice(0, 5).map((t) => (
                    <li className="blocked-row" key={t}>
                      <span className="blocked-row__x" aria-hidden><IconBan size={16} /></span>
                      <span className="blocked-row__text">{t}</span>
                    </li>
                  ))}
                </ul>
              </>
            )}
          </div>
        </div>
      )}

      {/* 觸發規則：證明 C 組是規則驅動 */}
      {arm.rules_fired && arm.rules_fired.length > 0 && (
        <>
          <div className="label">觸發的確定性規則</div>
          <div className="stack gap-2">
            {arm.rules_fired.slice(0, 3).map((r) => (
              <div className="rule rule--fired" key={r.rule_id}>
                <span className="rule__icon"><IconScale size={15} /></span>
                <div className="rule__main">
                  <div>
                    <span className="rule__id">{r.rule_id}</span>
                    <span className="rule__ver">{r.version}</span>
                  </div>
                  <div className="rule__name t-sm">{r.title}</div>
                  <div className="rule__action">→ {r.action_zh}</div>
                </div>
                <span className="rule__verdict">FIRED</span>
              </div>
            ))}
          </div>
        </>
      )}

      {/* 來源 */}
      <div className="label">
        來源（{arm.citations.length > 0 ? `${arm.citations.length} 筆` : '無'}）
      </div>
      {arm.citations.length === 0 ? (
        <div className="legend__row ink-danger">
          <IconBan size={14} /> 完全沒有來源，無法回查任何一句話的依據。
        </div>
      ) : (
        <div className="stack gap-2">
          {arm.citations.slice(0, 4).map((c, i) => (
            <div
              key={`${c.doc_id}-${c.passage_id ?? i}`}
              className="legend__row row row--top row--tight"
            >
              <IconDoc size={14} />
              <span>
                <b>{c.title_zh}</b>
                {c.passage_id && (
                  <span className="mono-xs">
                    {' '}· {c.passage_id}
                  </span>
                )}
                <br />
                <span
                  className="muted"
                  style={{ color: c.is_expired ? 'var(--s-red)' : undefined }}
                >
                  {c.note_zh}
                </span>
              </span>
            </div>
          ))}
        </div>
      )}

      {/* 稽核編號 */}
      <div className="legend__row arm__foot">
        <b>稽核編號：</b>
        {arm.audit_id ? (
          <span className="mono-xs">{arm.audit_id}</span>
        ) : (
          <span className="ink-danger">無，事後無法回查這次為什麼這樣回答</span>
        )}
      </div>

      <div className="legend__row muted t-xs">{arm.note_zh}</div>
    </article>
  )
}

/* ---------------- 維度對照表 ---------------- */

function DimensionTable({ data }: { data: CompareResponse }) {
  const keys = data.dimension_order
  const label = (k: CompareDimensionKey) =>
    data.arms[0]?.dimensions[k]?.label_zh ?? k

  return (
    <div className="tbl-wrap">
      <table className="tbl">
        <thead>
          <tr>
            <th style={{ width: 150 }}>判準</th>
            {data.arms.map((a) => (
              <th key={a.arm}>
                {a.name_zh}
                {a.is_prerecorded && (
                  <span className="muted" style={{ display: 'block', fontWeight: 400, fontSize: 'var(--t-xs)' }}>
                    預錄範例
                  </span>
                )}
              </th>
            ))}
          </tr>
        </thead>
        <tbody>
          {keys.map((k) => (
            <tr key={k}>
              <td className="strong">{label(k)}</td>
              {data.arms.map((a) => {
                const d = a.dimensions[k]
                return (
                  <td key={a.arm}>
                    <span
                      className="risk"
                      data-state={d.good ? 'GREEN' : 'RED'}
                      style={{ color: 'var(--st)', background: 'var(--st-bg)' }}
                    >
                      {d.good ? <IconCheck size={14} /> : <IconBan size={14} />}
                      {d.value ? '是' : '否'}
                    </span>
                    <div className="muted" style={{ marginTop: 'var(--sp-1)', fontSize: 'var(--t-xs)' }}>
                      {d.detail_zh}
                    </div>
                  </td>
                )
              })}
            </tr>
          ))}
        </tbody>
      </table>
    </div>
  )
}
