import { useState } from 'react'
import type { ConsultResponse } from '../lib/types'
import { consult } from '../lib/api'
import { ACT1_BLOCKED_FIELDS } from '../mocks'
import { Verdict, StateLegend } from '../components/StateVisuals'
import { AnswerPassportCard, ClaimButton } from '../components/Passport'
import { Thesis, HaltedPanel, Block, SectionTitle, Steps, Timeline, QrPlaceholder, Note } from '../components/Common'
import { IconArrowRight, IconPhone, IconBuilding, IconClock, IconAlert, IconStop } from '../components/Icons'

const OWNER_QUESTION = '我的貓一直進砂盆但尿不出來，可以先吃什麼藥？'

export function Act1({ onNext }: { onNext: () => void }) {
  const [data, setData] = useState<ConsultResponse | null>(null)
  const [loading, setLoading] = useState(false)

  const run = async () => {
    setLoading(true)
    try {
      setData(await consult({ question_zh: OWNER_QUESTION, role: 'owner', case_id: 'act1' }))
    } finally {
      setLoading(false)
    }
  }

  const d = data ?? (null as ConsultResponse | null)

  return (
    <div className="stack gap-8">
      <header className="stack gap-4">
        <SectionTitle num="第一幕">系統拒絕看似合理的用藥要求</SectionTitle>
        <p className="lede">
          飼主提出的是一個非常自然的請求：先吃點藥觀察看看。多數 AI 會直接回答。
          VetLink AI 在檢索任何產品資料<b>之前</b>就停止了流程 —— 因為這組症狀符合急症紅旗規則。
        </p>
        <Steps steps={['飼主描述症狀', '症狀結構化', 'Evidence Gate 判定', '停止檢索並轉介']} current={d ? 3 : 0} />
      </header>

      {/* 輸入 */}
      <section className="prompt">
        <span className="prompt__who">飼主・示範帳號</span>
        <div className="prompt__bubble">{OWNER_QUESTION}</div>
        {!d && (
          <button className="btn btn--primary btn--lg" onClick={run} disabled={loading} style={{ alignSelf: 'flex-start' }}>
            {loading ? '判定中…' : '送出並執行 Evidence Gate 判定'}
            {!loading && <IconArrowRight size={18} />}
          </button>
        )}
        {loading && (
          <div className="note">
            <span className="note__icon"><IconClock size={18} /></span>
            正在依序執行：症狀結構化 → 紅旗規則引擎 → 角色政策引擎 → 文件效期閘門
          </div>
        )}
      </section>

      {d && (
        <>
          <Verdict state={d.gate_state} headline={d.headline_zh} auditId={d.passport.audit_id}>
            <div className="grid-2">
              {/* 停止檢索 —— 關鍵證據 */}
              <HaltedPanel reason={d.passport.halt_reason_zh ?? ''} fields={ACT1_BLOCKED_FIELDS} />

              {/* 成立的規則 */}
              <div className="card">
                <div className="card__head">
                  <span className="card__title" style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
                    <IconStop size={19} /> 觸發本次拒絕的規則
                  </span>
                </div>
                <div className="card__body stack gap-3">
                  {d.passport.rules.filter((r) => r.fired).map((r) => (
                    <div className="rule rule--fired" key={r.rule_id}>
                      <span className="rule__icon"><IconAlert size={17} /></span>
                      <div className="rule__main">
                        <div>
                          <span className="rule__id">{r.rule_id}</span>
                          <span className="rule__ver">{r.version}</span>
                        </div>
                        <div className="rule__name">{r.name_zh}</div>
                        <div className="rule__action">→ {r.action_zh}</div>
                        {r.basis_zh && <div className="rule__basis">判定依據：{r.basis_zh}</div>}
                        {r.clinical_source && <div className="rule__basis">臨床依據：{r.clinical_source}</div>}
                      </div>
                      <span className="rule__verdict">FIRED</span>
                    </div>
                  ))}
                  <Note>
                    規則由獸醫審核後結構化，判定為確定性比對，不經生成模型。因此同樣的輸入必定得到同樣的攔截結果。
                  </Note>
                </div>
              </div>
            </div>
          </Verdict>

          <Thesis>
            AI 的價值不是每次都回答，而是知道何時必須停止。這一次，系統在還沒碰到任何一筆產品資料之前就停下來了。
          </Thesis>

          {/* 飼主實際看到的內容 */}
          <section className="stack gap-4">
            <SectionTitle num="1-1">飼主實際看到的內容（無藥名、無劑量）</SectionTitle>
            <div className="grid-3">
              {d.content_blocks.map((b) => (
                <Block
                  key={b.title_zh}
                  block={b}
                  renderItem={(claimId, _text) => {
                    const claim = d.passport.claims.find((c) => c.claim_id === claimId)
                    return claim ? <ClaimButton claim={claim} passages={d.passport.passages} /> : null
                  }}
                />
              ))}
            </div>
            <Note>
              上方每一項醫療陳述都可點擊，展開後即為支持它的原始段落。系統不輸出任何未經來源支持的內容。
            </Note>
          </section>

          {/* 急診轉介 */}
          {d.emergency_referral && (
            <section className="stack gap-4">
              <SectionTitle
                num="1-2"
                right={
                  <span className="risk risk--HIGH">
                    <IconClock size={14} /> {d.emergency_referral.urgency_zh}・{d.emergency_referral.window_zh}
                  </span>
                }
              >
                急診轉介
              </SectionTitle>
              <div className="tbl-wrap">
                <table className="tbl">
                  <thead>
                    <tr>
                      <th>動物醫院</th><th>地區</th><th>電話</th><th>距離</th><th>24 小時</th><th>營業狀態</th>
                    </tr>
                  </thead>
                  <tbody>
                    {d.emergency_referral.clinics.map((c) => (
                      <tr key={c.name_zh}>
                        <td style={{ fontWeight: 700, display: 'flex', gap: 'var(--sp-2)', alignItems: 'center' }}>
                          <IconBuilding size={16} /> {c.name_zh}
                        </td>
                        <td>{c.district_zh}</td>
                        <td className="mono" style={{ whiteSpace: 'nowrap' }}>
                          <span style={{ display: 'inline-flex', gap: 6, alignItems: 'center' }}><IconPhone size={14} />{c.phone}</span>
                        </td>
                        <td className="mono">{c.distance_km} km</td>
                        <td>{c.is_24h ? '是' : '否'}</td>
                        <td>
                          {c.status_confirmed
                            ? <span className="verbadge verbadge--valid">已確認</span>
                            : <span className="verbadge">未確認・請先致電</span>}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <Note>{d.emergency_referral.disclaimer_zh}</Note>
            </section>
          )}

          {/* 症狀摘要與時間軸 */}
          {d.visit_summary && (
            <section className="stack gap-4">
              <SectionTitle num="1-3">症狀摘要與就診交接</SectionTitle>
              <div className="grid-2">
                <div className="card">
                  <div className="card__head"><span className="card__title">結構化就診摘要</span>
                    <span className="mono muted">{d.visit_summary.summary_id}</span>
                  </div>
                  <div className="card__body stack gap-4">
                    <div className="stack gap-2">
                      <div className="label">個體資料</div>
                      <div style={{ fontSize: 'var(--t-sm)', lineHeight: 1.8 }}>
                        {d.visit_summary.pet.name_zh}｜{d.visit_summary.pet.species_zh}・{d.visit_summary.pet.breed_zh}｜
                        {d.visit_summary.pet.sex_zh}（{d.visit_summary.pet.neutered ? '已絕育' : '未絕育'}）｜
                        {d.visit_summary.pet.age_zh}｜{d.visit_summary.pet.weight_kg} kg
                      </div>
                    </div>
                    <div className="stack gap-2">
                      <div className="label">主訴</div>
                      <div style={{ fontWeight: 700 }}>{d.visit_summary.chief_complaint_zh}</div>
                    </div>
                    <div className="tbl-wrap">
                      <table className="tbl">
                        <tbody>
                          {d.visit_summary.structured_fields.map((f) => (
                            <tr key={f.label_zh}>
                              <th style={{ width: 150 }}>{f.label_zh}</th>
                              <td>{f.value_zh}</td>
                            </tr>
                          ))}
                        </tbody>
                      </table>
                    </div>
                  </div>
                </div>

                <div className="stack gap-5">
                  <div className="card">
                    <div className="card__head"><span className="card__title">症狀時間軸</span></div>
                    <div className="card__body">
                      {d.timeline && <Timeline entries={d.timeline} />}
                    </div>
                  </div>
                  <div className="card">
                    <div className="card__head"><span className="card__title">授權交接給獸醫</span></div>
                    <div className="card__body stack gap-3">
                      <QrPlaceholder code={d.visit_summary.authorization_code} />
                      <div className="muted" style={{ textAlign: 'center' }}>
                        授權有效至 {new Date(d.visit_summary.expires_at_iso).toLocaleString('zh-TW')}
                      </div>
                      <button className="btn btn--primary" onClick={onNext}>
                        由獸醫掃描此 QR Code 進入第二幕 <IconArrowRight size={18} />
                      </button>
                    </div>
                  </div>
                </div>
              </div>
            </section>
          )}

          {/* 回答護照 */}
          <section className="stack gap-4">
            <SectionTitle num="1-4">回答護照｜本次拒絕的完整證明</SectionTitle>
            <AnswerPassportCard passport={d.passport} />
          </section>

          <section className="stack gap-4">
            <SectionTitle num="1-5">四種狀態中，本次落在哪一種</SectionTitle>
            <StateLegend active="RED" />
          </section>
        </>
      )}
    </div>
  )
}
