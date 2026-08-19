import { useState } from 'react'
import type { VetSearchResponse, ProductRecord } from '../lib/types'
import { vetSearch } from '../lib/api'
import { ACT1_CONSULT, ACT2_VET_SEARCH, ROLE_DIFF_ROWS, DATASET_FACTS } from '../mocks'
import { Verdict, StateBadge } from '../components/StateVisuals'
import { AnswerPassportCard, ClaimButton, PassagePanel, VersionBadge } from '../components/Passport'
import { Thesis, SectionTitle, Steps, Timeline, QrPlaceholder, Note } from '../components/Common'
import {
  IconArrowRight, IconLock, IconUnlock, IconSearch, IconStethoscope, IconUser,
  IconBan, IconCheck, IconShield, IconClock, IconQr, IconDoc,
} from '../components/Icons'

const VET_QUERY = ACT2_VET_SEARCH.query_zh
const AUTH_CODE = ACT1_CONSULT.visit_summary!.authorization_code

/** 授權階段：尚未掃描 → 已掃描驗證 → 已檢索 */
type Phase = 'locked' | 'authorized' | 'searched'

export function Act2({ onNext }: { onNext: () => void }) {
  const [phase, setPhase] = useState<Phase>('locked')
  const [data, setData] = useState<VetSearchResponse | null>(null)
  const [loading, setLoading] = useState(false)
  /** 被點擊的主張 → 顯示支持段落 */
  const [openClaim, setOpenClaim] = useState<string | null>(null)

  const runSearch = async () => {
    setLoading(true)
    try {
      const r = await vetSearch({ query_zh: VET_QUERY, auth_token: AUTH_CODE, case_id: 'act2' })
      setData(r)
      setPhase('searched')
    } finally {
      setLoading(false)
    }
  }

  const d = data
  const stepIndex = phase === 'locked' ? 0 : phase === 'authorized' ? 2 : 3

  return (
    <div className="stack gap-8">
      <header className="stack gap-4">
        <SectionTitle num="第二幕">同一案例，不同角色看到不同內容</SectionTitle>
        <p className="lede">
          第一幕的案例沒有改變，貓、疑似尿道阻塞、同一份症狀時間軸。改變的只有<b>誰在看</b>。
          獸醫掃描飼主授權 QR Code 並通過執照驗證後，系統從紅色轉入<b>藍色專業模式</b>：
          解鎖核准仿單與許可證原文檢索，但急症紅旗紀錄完整保留，劑量與處方決策仍由獸醫師保留。
        </p>
        <Steps
          steps={['飼主授權 QR Code', '獸醫執照驗證', '藍色模式解鎖', '核准仿單檢索']}
          current={stepIndex}
        />
      </header>

      {/* ---------- 授權關卡 ---------- */}
      <section className="stack gap-4">
        <SectionTitle num="2-1">授權關卡｜沒有授權就沒有藍色模式</SectionTitle>
        <div className="grid-2">
          <div className="card">
            <div className="card__head">
              <span className="card__title" style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
                <IconQr size={19} /> 飼主端授權碼
              </span>
              <span className="mono muted">{ACT1_CONSULT.visit_summary!.summary_id}</span>
            </div>
            <div className="card__body stack gap-3">
              <QrPlaceholder code={AUTH_CODE} />
              <div className="muted" style={{ textAlign: 'center' }}>
                由第一幕的就診摘要產生｜有效至{' '}
                {new Date(ACT1_CONSULT.visit_summary!.expires_at_iso).toLocaleString('zh-TW')}
              </div>
            </div>
          </div>

          <div className="card">
            <div className="card__head">
              <span className="card__title" style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
                {phase === 'locked' ? <IconLock size={19} /> : <IconUnlock size={19} />}
                獸醫端身分驗證
              </span>
              <span className="mono muted">VET-0142</span>
            </div>
            <div className="card__body stack gap-4">
              <div className="tbl-wrap">
                <table className="tbl">
                  <tbody>
                    <tr>
                      <th style={{ width: 132 }}>執業獸醫師</th>
                      <td>示範帳號｜獸醫師執照驗證{phase === 'locked' ? '（尚未驗證）' : '通過'}</td>
                    </tr>
                    <tr>
                      <th>飼主授權碼</th>
                      <td className="mono">{phase === 'locked' ? '待掃描' : `${AUTH_CODE}｜有效`}</td>
                    </tr>
                    <tr>
                      <th>授權範圍</th>
                      <td>本案例之就診摘要、症狀時間軸、攔截紀錄與核准仿單檢索</td>
                    </tr>
                    <tr>
                      <th>不含</th>
                      <td>劑量計算、處方生成、購買通路，系統一律不提供</td>
                    </tr>
                  </tbody>
                </table>
              </div>

              {phase === 'locked' ? (
                <button className="btn btn--primary btn--lg" onClick={() => setPhase('authorized')}>
                  <IconQr size={18} /> 掃描飼主 QR Code 並驗證獸醫身分
                </button>
              ) : (
                <div className="note" style={{ borderColor: 'var(--s-blue-soft)', background: 'var(--s-blue-bg)' }}>
                  <span className="note__icon" style={{ color: 'var(--s-blue)' }}><IconUnlock size={18} /></span>
                  <span>
                    <b>VG-BLUE-001 成立</b>：執照驗證通過且授權碼在有效期內 → 藍色專業模式已解鎖。
                    此解鎖動作已寫入稽核鏈，可回查是哪一位獸醫、在什麼時間、以哪一組授權取得了哪些資訊。
                  </span>
                </div>
              )}
            </div>
          </div>
        </div>

        {phase === 'locked' && (
          <Note>
            在授權成立之前，獸醫端與飼主端看到的內容完全相同。權限不是介面上的開關，而是規則引擎的判定結果。
          </Note>
        )}
      </section>

      {/* ---------- 角色對照：本幕的核心論證 ---------- */}
      {phase !== 'locked' && (
        <>
          <section className="stack gap-4">
            <SectionTitle num="2-2">同一份資料，兩種角色視野</SectionTitle>
            <p className="lede">
              左右兩欄是<b>同一個案例、同一組來源、同一套規則</b>。差別完全來自角色資格檢查的結果。
            </p>

            <div className="split">
              {/* 飼主視角 */}
              <div className="split__col" data-state="RED">
                <div className="split__head">
                  <IconUser size={20} />
                  <span className="split__role">飼主視角</span>
                  <span className="split__note">STATE / RED · 不得推薦</span>
                </div>
                <div className="split__body">
                  <div className="stack gap-2">
                    <div className="label">可見</div>
                    <div className="bullet"><span className="bullet__dot" /><span>危險徵兆與立即就醫指引</span></div>
                    <div className="bullet"><span className="bullet__dot" /><span>症狀時間軸（自己輸入的紀錄）</span></div>
                    <div className="bullet"><span className="bullet__dot" /><span>經確認之急診轉介資訊</span></div>
                  </div>
                  <hr className="divider" />
                  <div className="stack gap-2">
                    <div className="label">被規則遮蔽</div>
                    {['核准適應症原文', '有效成分與劑型', '許可證字號與效期', '產品比較與候選清單'].map((t) => (
                      <div className="blocked-row" key={t}>
                        <span className="blocked-row__x" aria-hidden><IconBan size={18} /></span>
                        <span className="blocked-row__text">{t}</span>
                        <span className="blocked-row__tag">VG-POL-011</span>
                      </div>
                    ))}
                  </div>
                  <div className="note">
                    依《獸醫師（佐）處方藥品販賣及使用管理辦法》第 3 條，
                    非經診斷開立處方，不得對飼主提供處方藥品之使用方法或劑量指示。
                  </div>
                </div>
              </div>

              {/* 獸醫視角 */}
              <div className="split__col" data-state="BLUE">
                <div className="split__head">
                  <IconStethoscope size={20} />
                  <span className="split__role">獸醫視角</span>
                  <span className="split__note">STATE / BLUE · 獸醫專業模式</span>
                </div>
                <div className="split__body">
                  <div className="stack gap-2">
                    <div className="label">額外解鎖</div>
                    {[
                      '核准適應症原文（可點擊回許可證段落）',
                      '有效成分 ingredients_clean 原文',
                      '許可證字號、版本與效期狀態',
                      '完整規則 ID、版本與判定依據',
                      '物種／效期閘門的排除紀錄',
                    ].map((t) => (
                      <div className="bullet" key={t}>
                        <span style={{ color: 'var(--s-blue)', marginTop: 2, flexShrink: 0 }}><IconCheck size={17} /></span>
                        <span>{t}</span>
                      </div>
                    ))}
                  </div>
                  <hr className="divider" />
                  <div className="stack gap-2">
                    <div className="label">仍然不提供（對任何角色皆然）</div>
                    {['劑量與投藥頻率計算', '處方箋生成', '產品購買連結'].map((t) => (
                      <div className="blocked-row" key={t}>
                        <span className="blocked-row__x" aria-hidden><IconBan size={18} /></span>
                        <span className="blocked-row__text">{t}</span>
                        <span className="blocked-row__tag">BY DESIGN</span>
                      </div>
                    ))}
                  </div>
                  <div className="note" style={{ borderColor: 'var(--s-blue-soft)', background: 'var(--s-blue-bg)' }}>
                    系統把有證據的資訊交到有資格決策的人手上，最終處置決策完整保留給獸醫師。
                  </div>
                </div>
              </div>
            </div>

            {/* 逐欄位對照表 */}
            <div className="tbl-wrap">
              <table className="tbl">
                <thead>
                  <tr>
                    <th>資訊欄位</th>
                    <th style={{ width: '30%' }}>飼主端</th>
                    <th style={{ width: '38%' }}>獸醫端（藍色模式）</th>
                    <th>差異</th>
                  </tr>
                </thead>
                <tbody>
                  {ROLE_DIFF_ROWS.map((r) => (
                    <tr key={r.field_zh}>
                      <td className="strong">{r.field_zh}</td>
                      <td>{r.owner}</td>
                      <td>{r.vet}</td>
                      <td>
                        {r.vetOnly
                          ? <span className="verbadge" style={{ borderColor: 'var(--s-blue)', color: 'var(--s-blue)', background: 'var(--s-blue-bg)' }}>角色解鎖</span>
                          : <span className="verbadge">無差異</span>}
                      </td>
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          </section>

          <Thesis>
            系統把高品質資訊交到有資格決策的人手上，而不是把決策藏在 AI 裡。
            解鎖的是「證據的可見度」，不是「代替醫師做決定」。
          </Thesis>

          {/* ---------- 症狀時間軸 + 為什麼飼主端被擋 ---------- */}
          <section className="stack gap-4">
            <SectionTitle num="2-3">獸醫接手：症狀時間軸與攔截原因</SectionTitle>
            <div className="grid-2">
              <div className="card">
                <div className="card__head">
                  <span className="card__title">症狀時間軸（結構化嚴重度標記）</span>
                  <StateBadge state="BLUE" size="sm" />
                </div>
                <div className="card__body">
                  <Timeline entries={ACT1_CONSULT.timeline ?? []} />
                </div>
              </div>

              <div className="card">
                <div className="card__head">
                  <span className="card__title" style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
                    <IconShield size={19} /> 飼主端當時為何被擋
                  </span>
                </div>
                <div className="card__body stack gap-3">
                  {ACT1_CONSULT.passport.rules.filter((r) => r.fired).map((r) => (
                    <div className="rule rule--fired" key={r.rule_id}>
                      <span className="rule__icon"><IconBan size={17} /></span>
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
                    獸醫端看到的不是「系統當時拒絕了」這句話，而是<b>完整的規則 ID、版本、判定依據與臨床出處</b>。
                    攔截是可稽核的事件，不是黑箱。
                  </Note>
                </div>
              </div>
            </div>
          </section>

          {/* ---------- 核准仿單檢索 ---------- */}
          <section className="stack gap-4">
            <SectionTitle
              num="2-4"
              right={
                <span className="muted">
                  資料時點 {DATASET_FACTS.as_of}｜全庫 {DATASET_FACTS.total_licences.toLocaleString()} 張許可證
                </span>
              }
            >
              核准仿單檢索（藍色模式）
            </SectionTitle>

            <section className="prompt">
              <span className="prompt__who">獸醫・VET-0142</span>
              <div className="prompt__bubble">{VET_QUERY}</div>
              {phase !== 'searched' && (
                <button
                  className="btn btn--primary btn--lg"
                  onClick={runSearch}
                  disabled={loading}
                  style={{ alignSelf: 'flex-start' }}
                >
                  {loading ? '檢索中…' : '執行核准仿單檢索'}
                  {!loading && <IconSearch size={18} />}
                </button>
              )}
              {loading && (
                <div className="note">
                  <span className="note__icon"><IconClock size={18} /></span>
                  正在依序執行：角色資格檢查 → 物種適用範圍閘門 → 文件效期閘門 → 主張驗證器
                </div>
              )}
            </section>

            {d && (
              <>
                <Verdict
                  state={d.passport.gate_state}
                  headline={`檢索完成：${d.total} 筆通過閘門，${d.filtered_out.length} 筆被閘門排除。所有結果均為核准適應症原文，不構成處方。`}
                  auditId={d.passport.audit_id}
                >
                  <div className="grid-4">
                    <div className="stat">
                      <div className="stat__n">{DATASET_FACTS.ccpc_total}</div>
                      <div className="stat__k">中化持有許可證總數</div>
                    </div>
                    <div className="stat stat--LOW">
                      <div className="stat__n">{DATASET_FACTS.ccpc_valid}</div>
                      <div className="stat__k">現行有效</div>
                    </div>
                    <div className="stat">
                      <div className="stat__n">{DATASET_FACTS.ccpc_companion}</div>
                      <div className="stat__k">伴侶動物用</div>
                    </div>
                    <div className="stat stat--HIGH">
                      <div className="stat__n">{d.filtered_out.length}</div>
                      <div className="stat__k">本次被閘門排除</div>
                    </div>
                  </div>
                </Verdict>

                {/* 通過閘門的產品 */}
                <div className="stack gap-4">
                  <div className="label">通過閘門的核准產品（點擊任一主張即展開許可證原文）</div>
                  <div className="stack gap-4">
                    {d.results.map((p) => (
                      <ProductCard
                        key={p.licence_no}
                        p={p}
                        claim={p.claim_id ? d.passport.claims.find((c) => c.claim_id === p.claim_id) : undefined}
                        passages={d.passport.passages}
                        open={openClaim === p.licence_no}
                        onToggle={() => setOpenClaim(openClaim === p.licence_no ? null : p.licence_no)}
                      />
                    ))}
                  </div>
                </div>

                {/* 被閘門擋下的產品：閘門確實在運作的證據 */}
                <div className="stack gap-4">
                  <div className="label">被閘門排除的記錄，閘門確實在運作</div>
                  {d.filtered_out.map((f) => (
                    <div className="halted" key={f.record.licence_no}>
                      <header className="halted__head">
                        <IconBan size={20} />
                        <span>{f.record.name_zh}</span>
                        <span className="halted__stamp">FILTERED OUT</span>
                      </header>
                      <div className="halted__body">
                        <p className="halted__reason">{f.reason_zh}</p>
                        <div style={{ display: 'flex', gap: 'var(--sp-3)', flexWrap: 'wrap', alignItems: 'center' }}>
                          <span className="verbadge">{f.record.licence_no}</span>
                          <span className="verbadge">核准物種：{f.record.species.join('、')}</span>
                          <span className="verbadge">{f.record.ingredients_clean}</span>
                          <VersionBadge
                            version={f.record.version}
                            from={f.record.issue_date_iso}
                            to={f.record.expiry_date_iso}
                            expired={f.record.is_expired}
                          />
                        </div>
                      </div>
                    </div>
                  ))}
                  <Note>
                    這兩筆不是「找不到」，而是<b>找到了、判定不適用、並記錄了排除理由</b>。
                    排除紀錄與檢索結果同樣寫入回答護照，可回查。
                  </Note>
                </div>

                {/* 主張級溯源 */}
                <section className="stack gap-4">
                  <SectionTitle num="2-5">主張級溯源｜點擊任一主張，看見支持它的原始段落</SectionTitle>
                  <div className="card">
                    <div className="card__body stack gap-3">
                      <div className="muted">
                        本次檢索共產生 {d.passport.claims.length} 項主張，全部比對到來源段落。
                        任一主張若找不到支持段落，依 VG-CLM-001 主張驗證器規則必須刪除或拒答。
                      </div>
                      {d.passport.claims.map((c) => (
                        <ClaimButton key={c.claim_id} claim={c} passages={d.passport.passages} />
                      ))}
                    </div>
                  </div>
                </section>

                {/* 回答護照 */}
                <section className="stack gap-4">
                  <SectionTitle num="2-6">回答護照｜本次藍色模式檢索的完整證明</SectionTitle>
                  <AnswerPassportCard passport={d.passport} />
                </section>

                <div style={{ display: 'flex', justifyContent: 'flex-end' }}>
                  <button className="btn btn--primary btn--lg" onClick={onNext}>
                    進入第三幕：仿單更新後追回舊回答 <IconArrowRight size={18} />
                  </button>
                </div>
              </>
            )}
          </section>
        </>
      )}
    </div>
  )
}

/** 單一核准產品卡 — 每項欄位皆為許可證原文，主張可展開溯源 */
function ProductCard({
  p, claim, passages, open, onToggle,
}: {
  p: ProductRecord
  claim?: import('../lib/types').Claim
  passages: Record<string, import('../lib/types').SourcePassage>
  open: boolean
  onToggle: () => void
}) {
  const passage = passages[`PSG-PRD-${p.licence_no.replace(/\D/g, '').slice(-5)}`]
  return (
    <div className="card">
      <div className="card__head">
        <span className="card__title" style={{ display: 'flex', alignItems: 'center', gap: 'var(--sp-2)' }}>
          <IconDoc size={19} /> {p.name_zh}
        </span>
        <div className="row row--tight">
          <span className="verbadge">{p.licence_no}</span>
          <VersionBadge version={p.version} from={p.issue_date_iso} to={p.expiry_date_iso} expired={p.is_expired} />
        </div>
      </div>
      <div className="card__body stack gap-3">
        <div className="tbl-wrap">
          <table className="tbl">
            <tbody>
              <tr><th style={{ width: 132 }}>英文品名</th><td className="mono">{p.name_en}</td></tr>
              <tr><th>持證公司</th><td>{p.company}</td></tr>
              <tr><th>劑型</th><td>{p.dosage_form}</td></tr>
              <tr><th>核准物種</th><td>{p.species.join('、')}{p.is_companion_animal ? '（伴侶動物）' : ''}</td></tr>
              <tr><th>有效成分</th><td className="mono">{p.ingredients_clean}</td></tr>
              <tr><th>核准適應症（原文）</th><td>{p.indications_raw}</td></tr>
            </tbody>
          </table>
        </div>

        {claim ? (
          <ClaimButton claim={claim} passages={passages} />
        ) : (
          passage && (
            <div className="stack gap-2">
              <button type="button" className="claim" aria-expanded={open} onClick={onToggle}>
                <span className="claim__text">查看本品許可證原文段落</span>
                <span className="claim__cite">
                  <IconDoc size={12} />{passage.passage_id}
                  <span aria-hidden>{open ? '▾' : '▸'}</span>
                </span>
              </button>
              {open && <PassagePanel p={passage} />}
            </div>
          )
        )}
      </div>
    </div>
  )
}
