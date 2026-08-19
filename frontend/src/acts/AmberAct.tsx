import { useState } from 'react'
import type { ConsultResponse } from '../lib/types'
import { consult } from '../lib/api'
import { AMBER_QUESTION } from '../mocks'
import { Verdict, StateLegend } from '../components/StateVisuals'
import { AnswerPassportCard, ClaimButton } from '../components/Passport'
import { Thesis, SectionTitle, Steps, Note, Block } from '../components/Common'
import { IconArrowRight, IconQuestion, IconClock, IconBan, IconCheck, IconList } from '../components/Icons'

export function AmberAct() {
  const [data, setData] = useState<ConsultResponse | null>(null)
  const [loading, setLoading] = useState(false)
  /** 使用者對每一題選了什麼 —— 僅供展示追問互動，不改變閘門判定 */
  const [answers, setAnswers] = useState<Record<string, string>>({})

  const run = async () => {
    setLoading(true)
    try {
      setData(await consult({ question_zh: AMBER_QUESTION, role: 'owner', case_id: 'amber' }))
    } finally {
      setLoading(false)
    }
  }

  const d = data
  const questions = d?.follow_up_questions ?? []
  const answered = questions.filter((q) => answers[q.field]).length
  const complete = questions.length > 0 && answered === questions.length

  return (
    <div className="stack gap-8">
      <header className="stack gap-4">
        <SectionTitle num="狀態 · 黃">資訊不足時，系統只問固定的必要問題</SectionTitle>
        <p className="lede">
          紅色是「不能回答」，黃色是「<b>還不能回答</b>」。
          這是最容易被一般 AI 跳過的一種狀態，面對模糊的敘述，多數系統會用推測值補齊缺漏欄位，
          然後給出一個看似完整的答案。VetLink AI 在必要欄位補齊之前，不輸出任何衛教或產品資訊，
          而且<b>追問題目由規則庫提供，不由生成模型自由產生</b>。
        </p>
        <Steps
          steps={['飼主模糊敘述', '必要欄位完整度檢查', '固定必要追問', '補齊後重新判定']}
          current={!d ? 0 : complete ? 3 : 2}
        />
      </header>

      <section className="prompt">
        <span className="prompt__who">飼主・示範帳號</span>
        <div className="prompt__bubble">{AMBER_QUESTION}</div>
        {!d && (
          <button className="btn btn--primary btn--lg" onClick={run} disabled={loading} style={{ alignSelf: 'flex-start' }}>
            {loading ? '判定中…' : '送出並執行 Evidence Gate 判定'}
            {!loading && <IconArrowRight size={18} />}
          </button>
        )}
        {loading && (
          <div className="note">
            <span className="note__icon"><IconClock size={18} /></span>
            正在依序執行：症狀結構化 → 必要欄位完整度檢查 → 紅旗規則引擎
          </div>
        )}
      </section>

      {d && (
        <>
          <Verdict state={d.gate_state} headline={d.headline_zh} auditId={d.passport.audit_id}>
            <div className="grid-2">
              {/* 缺漏欄位 */}
              <div className="halted">
                <header className="halted__head">
                  <IconQuestion size={20} />
                  <span>必要欄位未補齊</span>
                  <span className="halted__stamp">INSUFFICIENT INFO</span>
                </header>
                <div className="halted__body">
                  <p className="halted__reason">{d.passport.halt_reason_zh}</p>
                  <div className="label">缺漏中、因此不予輸出的欄位</div>
                  <ul className="blocked-list">
                    {questions.map((q) => (
                      <li className="blocked-row" key={q.field}>
                        <span className="blocked-row__x" aria-hidden>
                          {answers[q.field] ? <IconCheck size={18} /> : <IconBan size={18} />}
                        </span>
                        <span
                          className="blocked-row__text"
                          style={answers[q.field] ? { textDecoration: 'none', color: 'var(--c-ink)' } : undefined}
                        >
                          {q.question_zh}
                        </span>
                        <span className="blocked-row__tag">
                          {answers[q.field] ? '已補齊' : 'MISSING'}
                        </span>
                      </li>
                    ))}
                  </ul>
                </div>
              </div>

              {/* 為什麼不直接回答 */}
              <div className="card">
                <div className="card__head">
                  <span className="card__title" style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
                    <IconList size={19} /> 觸發本次追問的規則
                  </span>
                </div>
                <div className="card__body stack gap-3">
                  {d.passport.rules.filter((r) => r.fired).map((r) => (
                    <div className="rule rule--fired" key={r.rule_id}>
                      <span className="rule__icon"><IconQuestion size={17} /></span>
                      <div className="rule__main">
                        <div>
                          <span className="rule__id">{r.rule_id}</span>
                          <span className="rule__ver">{r.version}</span>
                        </div>
                        <div className="rule__name">{r.name_zh}</div>
                        <div className="rule__action">→ {r.action_zh}</div>
                        {r.basis_zh && <div className="rule__basis">判定依據：{r.basis_zh}</div>}
                      </div>
                      <span className="rule__verdict">FIRED</span>
                    </div>
                  ))}
                  <Note>
                    VG-POL-021 是關鍵：追問題目取自規則庫 §1.3 定義的欄位清單，
                    不由生成模型即興產生。同樣的缺漏必定得到同樣的六道題目。
                  </Note>
                </div>
              </div>
            </div>
          </Verdict>

          <Thesis>
            系統不用推測值填補缺漏。在必要欄位補齊之前，它寧願問問題，也不給一個看起來完整的答案。
          </Thesis>

          {/* 固定必要追問 */}
          <section className="stack gap-4">
            <SectionTitle
              num="黃-1"
              right={
                <span className="risk" style={{ color: 'var(--s-amber)', background: 'var(--s-amber-bg)' }}>
                  已補齊 {answered} / {questions.length}
                </span>
              }
            >
              固定必要追問（{questions.length} 題，全部為必填）
            </SectionTitle>

            <div className="stack gap-3" data-state="AMBER">
              {questions.map((q, i) => (
                <div className="followup" key={q.field}>
                  <div className="followup__q">
                    <span className="followup__n">{i + 1}</span>
                    <span>
                      {q.question_zh}
                      {q.required && <span className="muted" style={{ marginLeft: 'var(--sp-2)' }}>必填</span>}
                    </span>
                  </div>
                  <div className="followup__opts">
                    {(q.options ?? []).map((o) => (
                      <button
                        key={o}
                        type="button"
                        className="opt"
                        aria-pressed={answers[q.field] === o}
                        onClick={() => setAnswers((a) => ({ ...a, [q.field]: a[q.field] === o ? '' : o }))}
                      >
                        {o}
                      </button>
                    ))}
                  </div>
                  <div className="muted" style={{ marginTop: 'var(--sp-3)', paddingLeft: 38 }}>
                    欄位代碼 <span className="mono">{q.field}</span>｜來源：獸醫安全規則庫 VG-RULE-INTAKE §1.3
                  </div>
                </div>
              ))}
            </div>

            {complete ? (
              <div className="note" style={{ borderColor: 'var(--s-green-soft)', background: 'var(--s-green-bg)' }}>
                <span className="note__icon" style={{ color: 'var(--s-green)' }}><IconCheck size={18} /></span>
                <span>
                  <b>六項必要欄位皆已補齊</b> → 資料資格檢查通過，系統可重新執行閘門判定。
                  依補齊後的內容，本次案例將轉入綠色（飼主可見衛教）或紅色（急症轉介）。
                  黃色不是終點，而是一個明確標示「尚未取得回答資格」的等待狀態。
                </span>
              </div>
            ) : (
              <Note>
                上方選項可直接點選試用。在六題全部補齊之前，系統不會輸出任何衛教或產品類別資訊。
              </Note>
            )}
          </section>

          {/* 追問期間仍提供的安全提醒 */}
          <section className="stack gap-4">
            <SectionTitle num="黃-2">追問期間仍然提供的內容</SectionTitle>
            <div className="grid-2">
              {d.content_blocks.map((b) => (
                <Block
                  key={b.title_zh}
                  block={b}
                  renderItem={(claimId) => {
                    const claim = d.passport.claims.find((c) => c.claim_id === claimId)
                    return claim ? <ClaimButton claim={claim} passages={d.passport.passages} /> : null
                  }}
                />
              ))}
            </div>
            <Note>
              追問期間僅提供「不依賴診斷即成立」的通用安全提醒，且同樣綁定來源段落、可點擊溯源。
              這類提醒不構成診斷，亦不涉及任何產品資訊。
            </Note>
          </section>

          <section className="stack gap-4">
            <SectionTitle num="黃-3">回答護照｜本次拒答的完整證明</SectionTitle>
            <AnswerPassportCard passport={d.passport} />
          </section>

          <section className="stack gap-4">
            <SectionTitle num="黃-4">四種狀態中，本次落在哪一種</SectionTitle>
            <StateLegend active="AMBER" />
          </section>
        </>
      )}
    </div>
  )
}
