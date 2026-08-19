/**
 * 文件庫 — 系統能講的話的全集。
 *
 * 回答護照證明「這句話出自哪一段」；這一頁證明的是它的前提：
 * **這個庫裡總共只有這些東西**。兩者合起來才構成完整的檢查鏈 ——
 * 使用者可以拿回答裡的 passage_id 到這裡對，也可以反過來看系統有什麼卻沒講。
 *
 * 三條原則：
 *   1. **無 mock 備援。** 顯示一個不存在的文件庫，會讓所有核對結論失效，
 *      比沒有這一頁更糟。後端不通就明講。
 *   2. **角色政策同樣適用。** 衛教段落是飼主可見內容（綠色狀態本來就會輸出）；
 *      產品許可證屬藍色專業模式，未驗證身分只給統計數字。
 *      瀏覽器不是政策的後門。
 *   3. **效期由系統重算後標示。** 不採信來源自帶的失效標記。
 */
import { useEffect, useMemo, useState } from 'react'
import type { KnowledgeLibrary, LibraryPassage, LibraryProduct } from '../lib/types'
import { knowledgeLibrary, ConsultError } from '../lib/api'
import { SectionTitle, Thesis, Note } from '../components/Common'
import {
  IconDoc, IconSearch, IconLock, IconUnlock, IconAlert, IconClock,
  IconShield, IconCheck, IconBan, IconLink,
} from '../components/Icons'

/** Demo 用獸醫 token（正式版接獸醫師執照 API） */
const DEMO_VET_TOKEN = 'demo-vet-token'

/** 後端 species_slugs 的全集（農業部資料含畜禽，不是只有犬貓） */
const SPECIES_ZH: Record<string, string> = {
  cat: '貓', dog: '狗', pig: '豬', cattle: '牛', horse: '馬', sheep_goat: '羊',
  chicken: '雞', turkey: '火雞', duck: '鴨', goose: '鵝', pigeon: '鴿',
  rabbit: '兔', fish: '魚',
}
const speciesLabel = (s: string[]) =>
  s.length === 0 ? '不限物種' : s.map((x) => SPECIES_ZH[x] ?? x).join('、')

export function Library() {
  const [data, setData] = useState<KnowledgeLibrary | null>(null)
  const [error, setError] = useState<string | null>(null)
  const [loading, setLoading] = useState(true)
  const [vetToken, setVetToken] = useState('')

  const [scenario, setScenario] = useState<string | null>(null)
  const [query, setQuery] = useState('')
  /** 產品清單的物種篩選 —— 200 筆母體以畜禽為主，犬貓要篩過才看得到 */
  const [productSpecies, setProductSpecies] = useState<'cat' | 'dog' | null>(null)

  const load = (token?: string, species?: 'cat' | 'dog' | null) => {
    setLoading(true)
    setError(null)
    knowledgeLibrary(token || undefined, species ?? undefined)
      .then((d) => setData(d))
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

  const passages = data?.education.passages ?? []
  const scenarios = useMemo(() => {
    const order = ['泌尿', '腸胃', '皮膚耳部', '呼吸', '跨情境']
    const present = Object.keys(data?.education.by_scenario ?? {})
    return order.filter((s) => present.includes(s)).concat(
      present.filter((s) => !order.includes(s)),
    )
  }, [data])

  const filtered = useMemo(() => {
    const q = query.trim()
    return passages.filter((p) => {
      if (scenario && !p.scenario_scope.includes(scenario)) return false
      if (!q) return true
      return p.text.includes(q) || p.passage_id.includes(q.toUpperCase()) || p.doc_id.includes(q)
    })
  }, [passages, scenario, query])

  return (
    <div className="stack gap-8">
      <header className="stack gap-4">
        <SectionTitle num="文件庫">系統能講的話，全部在這裡</SectionTitle>
        <p className="lede">
          綠色狀態能對飼主輸出的內容，<b>只能</b>是這個庫裡的段落原文 ——
          系統不改寫醫療內容，只決定要輸出其中哪幾段。
          你可以拿任何一則回答裡的段落編號回來這裡核對，
          也可以反過來看：系統手上有什麼、但這次沒有講。
        </p>
        <Thesis>
          文件庫瀏覽器<b>不是政策的後門</b>：產品許可證內容一樣需要獸醫身分驗證，
          未驗證時只給得到統計數字。
        </Thesis>
      </header>

      {loading && <div className="note"><IconClock size={18} className="note__icon" />讀取文件庫…</div>}

      {error && (
        <section className="live__error">
          <header className="live__error-head"><IconAlert size={20} /> 沒有讀到真實的文件庫</header>
          <div className="live__error-body stack gap-3">
            <p>
              <b>這一頁刻意不使用任何預備資料。</b>
              顯示一個不存在的文件庫，會讓所有「回答有沒有依據」的核對結論全部失效，
              比沒有這一頁更糟。
            </p>
            <p className="mono muted">{error}</p>
            <p className="muted">請確認後端服務正在執行後重新整理。</p>
          </div>
        </section>
      )}

      {data && (
        <>
          <FunnelStats data={data} />

          {/* ---- 衛教段落 ---- */}
          <section className="stack gap-4">
            <div className="lib__head">
              <h3 className="lib__title"><IconDoc size={19} /> 獸醫審核衛教段落</h3>
              <span className="lib__badge">{data.education.total} 段</span>
              <span className="muted lib__note">{data.education.note_zh}</span>
            </div>

            <div className="lib__filters">
              <div className="lib__chips" role="group" aria-label="情境篩選">
                <button
                  type="button" className="lib__chip"
                  aria-pressed={scenario === null}
                  onClick={() => setScenario(null)}
                >
                  全部 <span className="lib__chip-n">{passages.length}</span>
                </button>
                {scenarios.map((s) => (
                  <button
                    key={s} type="button" className="lib__chip"
                    aria-pressed={scenario === s}
                    onClick={() => setScenario(scenario === s ? null : s)}
                  >
                    {s} <span className="lib__chip-n">{data.education.by_scenario[s]}</span>
                  </button>
                ))}
              </div>
              <label className="lib__search">
                <IconSearch size={16} />
                <input
                  type="search"
                  placeholder="搜尋段落內容或編號（例如 EDU-GI-001）"
                  value={query}
                  onChange={(e) => setQuery(e.target.value)}
                  aria-label="搜尋衛教段落"
                />
              </label>
            </div>

            {filtered.length === 0 ? (
              <Note>目前條件下沒有符合的段落。</Note>
            ) : (
              <div className="stack gap-3">
                {filtered.map((p) => <PassageCard key={p.passage_id} p={p} />)}
              </div>
            )}
          </section>

          {/* ---- 產品許可證 ---- */}
          <ProductSection
            data={data}
            vetToken={vetToken}
            onTokenChange={setVetToken}
            onUnlock={() => load(vetToken || DEMO_VET_TOKEN, productSpecies)}
            onLock={() => { setVetToken(''); setProductSpecies(null); load() }}
            species={productSpecies}
            onSpeciesChange={(sp) => {
              setProductSpecies(sp)
              load(vetToken || DEMO_VET_TOKEN, sp)
            }}
          />

          {/* ---- 效期閘門證據 ---- */}
          <ExpiryEvidence data={data} />
        </>
      )}
    </div>
  )
}

/* ================================================================== *
 * 漏斗統計
 * ================================================================== */

function FunnelStats({ data }: { data: KnowledgeLibrary }) {
  const cells = [
    { n: data.education.total, label: '衛教段落', sub: '飼主可見內容全集' },
    { n: data.education.online_total, label: '真實線上來源', sub: `${Object.keys(data.education.online_by_source_org).length} 個外部來源單位` },
    { n: data.products.total, label: '產品許可證', sub: '農業部開放資料' },
    { n: data.products.valid, label: '通過效期閘門', sub: `基準日 ${data.as_of}` },
    { n: data.expiry_gate.date_only_expired_count, label: '僅靠日期才抓到的過期', sub: '來源未標失效', danger: true },
  ]
  return (
    <div className="lib__stats">
      {cells.map((c) => (
        <div className="lib__stat" key={c.label} data-danger={c.danger || undefined}>
          <div className="lib__stat-n">{c.n}</div>
          <div className="lib__stat-label">{c.label}</div>
          <div className="lib__stat-sub">{c.sub}</div>
        </div>
      ))}
    </div>
  )
}

/* ================================================================== *
 * 衛教段落卡
 * ================================================================== */

function PassageCard({ p }: { p: LibraryPassage }) {
  return (
    <article className="lib__passage" data-expired={p.is_expired || undefined}>
      <header className="lib__passage-head">
        <span className="lib__pid">{p.passage_id}</span>
        <span className="lib__doc">{p.doc_id} · v{p.version}</span>
        <div className="lib__tags">
          {p.scenario_scope.map((s) => (
            <span className="lib__tag" key={s}>{s}</span>
          ))}
          <span className="lib__tag lib__tag--species">{speciesLabel(p.species_scope)}</span>
        </div>
      </header>
      <p className="lib__passage-text">{p.text}</p>
      <footer className="lib__passage-foot">
        <span className={p.is_expired ? 'lib__gate lib__gate--bad' : 'lib__gate lib__gate--ok'}>
          {p.is_expired ? <IconBan size={13} /> : <IconCheck size={13} />}
          {p.is_expired ? '已逾效期，不得引用' : '通過效期閘門'}
        </span>
        {p.issue_date_iso && <span>生效 {p.issue_date_iso}</span>}
        {p.expiry_date_iso && <span>失效 {p.expiry_date_iso}</span>}
        <span>審核狀態 {p.review_status === 'approved' ? '已核准' : p.review_status}</span>
        {p.source_org && <span>來源 {p.source_org}</span>}
        {p.fetched_at && <span>擷取 {p.fetched_at.slice(0, 10)}</span>}
        {p.source_url?.startsWith('http') && (
          <a href={p.source_url} target="_blank" rel="noreferrer" className="lib__link">
            <IconLink size={12} /> 來源
          </a>
        )}
      </footer>
    </article>
  )
}

/* ================================================================== *
 * 產品許可證 — 角色閘門
 * ================================================================== */

function ProductSection({
  data, vetToken, onTokenChange, onUnlock, onLock, species, onSpeciesChange,
}: {
  data: KnowledgeLibrary
  vetToken: string
  onTokenChange: (v: string) => void
  onUnlock: () => void
  onLock: () => void
  species: 'cat' | 'dog' | null
  onSpeciesChange: (s: 'cat' | 'dog' | null) => void
}) {
  const p = data.products
  const expiredShown = p.records.filter((r) => r.is_expired).length
  return (
    <section className="stack gap-4">
      <div className="lib__head">
        <h3 className="lib__title">
          {p.unlocked ? <IconUnlock size={19} /> : <IconLock size={19} />} 產品許可證
        </h3>
        <span className="lib__badge">{p.total} 筆</span>
        <span className="muted lib__note">{p.source_zh}</span>
      </div>

      {!p.unlocked ? (
        <div className="lib__locked">
          <div className="lib__locked-head">
            <IconShield size={19} /> 藍色專業模式內容
          </div>
          <p className="lib__locked-body">{p.note_zh}</p>
          <dl className="lib__counts">
            <div><dt>總筆數</dt><dd>{p.total}</dd></div>
            <div><dt>通過效期閘門</dt><dd>{p.valid}</dd></div>
            <div><dt>已逾效期</dt><dd>{p.expired}</dd></div>
            <div><dt>犬貓用</dt><dd>{p.companion_animal}</dd></div>
          </dl>
          <div className="lib__unlock">
            <input
              type="text"
              className="lib__token"
              placeholder={`獸醫 token（demo：${DEMO_VET_TOKEN}）`}
              value={vetToken}
              onChange={(e) => onTokenChange(e.target.value)}
              aria-label="獸醫身分驗證 token"
            />
            <button type="button" className="btn btn--primary" onClick={onUnlock}>
              <IconUnlock size={16} /> 驗證身分並解鎖
            </button>
          </div>
          <p className="muted">
            Demo 使用靜態 token；正式版接獸醫師執照 API。留白直接送出會以 demo token 驗證。
          </p>
        </div>
      ) : (
        <div className="stack gap-3">
          <div className="lib__unlocked-bar">
            <span className="lib__gate lib__gate--ok"><IconUnlock size={13} /> {data.role_zh}身分已驗證</span>
            <span className="muted">{p.note_zh}</span>
            <button type="button" className="btn" onClick={onLock}>回到飼主視角</button>
          </div>
          <div className="lib__chips" role="group" aria-label="產品物種篩選">
            {([null, 'cat', 'dog'] as const).map((sp) => (
              <button
                key={sp ?? 'all'} type="button" className="lib__chip"
                aria-pressed={species === sp}
                onClick={() => onSpeciesChange(sp)}
              >
                {sp === null ? '全部物種' : SPECIES_ZH[sp]}
              </button>
            ))}
          </div>
          <p className="muted">
            本次列出 {p.records.length} 筆（其中 {expiredShown} 筆已逾效期）。
            逾效期者仍列出並標示，但不得被引用進回答。
            母體 {p.total} 筆以畜禽為主，犬貓用藥請用上方物種篩選。
          </p>
          <div className="lib__products">
            {p.records.map((r) => <ProductCard key={r.licence_no} r={r} />)}
          </div>
        </div>
      )}
    </section>
  )
}

function ProductCard({ r }: { r: LibraryProduct }) {
  return (
    <article className="lib__product" data-expired={r.is_expired || undefined}>
      <header className="lib__product-head">
        <span className="lib__product-name">{r.name_zh}</span>
        <span className="lib__pid">{r.licence_no}</span>
      </header>
      <dl className="lib__product-fields">
        {r.company && <div><dt>廠商</dt><dd>{r.company}</dd></div>}
        {r.dosage_form && <div><dt>劑型</dt><dd>{r.dosage_form}</dd></div>}
        {r.ingredients_clean && <div><dt>成分</dt><dd>{r.ingredients_clean}</dd></div>}
        {r.indications_raw && <div><dt>核准適應症</dt><dd>{r.indications_raw}</dd></div>}
        <div><dt>適用物種</dt><dd>{speciesLabel(r.species)}</dd></div>
      </dl>
      <footer className="lib__passage-foot">
        <span className={r.is_expired ? 'lib__gate lib__gate--bad' : 'lib__gate lib__gate--ok'}>
          {r.is_expired ? <IconBan size={13} /> : <IconCheck size={13} />} {r.gate_zh}
        </span>
        {r.expiry_date_raw && <span>有效期間原文「{r.expiry_date_raw}」</span>}
        {r.expiry_date_iso && <span>換算 {r.expiry_date_iso}</span>}
        {r.is_expired && !r.expired_by_marker && (
          <span className="lib__flag">來源未標失效</span>
        )}
      </footer>
    </article>
  )
}

/* ================================================================== *
 * 效期閘門證據
 * ================================================================== */

function ExpiryEvidence({ data }: { data: KnowledgeLibrary }) {
  const g = data.expiry_gate
  if (!g.examples.length) return null
  return (
    <section className="stack gap-4">
      <div className="lib__head">
        <h3 className="lib__title"><IconClock size={19} /> 效期閘門實例</h3>
        <span className="lib__badge">{g.date_only_expired_count} 筆</span>
      </div>
      <p className="muted">{g.note_zh}</p>
      <div className="tbl-wrap">
        <table className="tbl">
          <thead>
            <tr>
              <th>許可證字號</th><th>品名</th><th>有效期間原文</th><th>換算後</th><th>系統判定</th>
            </tr>
          </thead>
          <tbody>
            {g.examples.map((e) => (
              <tr key={e.licence_no}>
                <td className="mono">{e.licence_no}</td>
                <td>{e.name_zh}</td>
                <td>{e.expiry_date_raw ?? '—'}</td>
                <td className="mono">{e.expiry_date_iso ?? '—'}</td>
                <td><span className="risk" data-state="RED">已過期</span></td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>
      <Note>
        這些文件的來源<b>沒有</b>標示「(已失效)」。系統只看日期、不看標記，
        因此它們不會被引用進任何回答。
      </Note>
    </section>
  )
}
