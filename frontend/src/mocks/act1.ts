import type { ConsultResponse, SourcePassage } from '../lib/types'

/** 第一幕來源段落 — 全部為衛教/規則類，刻意不含任何產品或劑量 */
const passages: Record<string, SourcePassage> = {
  'PSG-URO-001': {
    passage_id: 'PSG-URO-001',
    doc_id: 'VG-RULE-URO',
    doc_title_zh: '獸醫安全規則庫｜貓下泌尿道急症判定',
    version: 'v1.2',
    text:
      '公貓因尿道細長，一旦發生尿道阻塞，膀胱無法排空，血鉀將於 24 小時內快速升高並可能導致心律不整與急性腎損傷。' +
      '臨床上「反覆進出砂盆但無尿液產出」為高度疑似完全阻塞之表現，屬需要立即處置之急症，不得以居家投藥觀察取代就醫。',
    page_ref: '§3.2 下泌尿道阻塞',
    issue_date_iso: '2025-11-04',
    expiry_date_iso: '2027-11-03',
    is_expired: false,
  },
  'PSG-URO-002': {
    passage_id: 'PSG-URO-002',
    doc_id: 'VG-RULE-URO',
    doc_title_zh: '獸醫安全規則庫｜貓下泌尿道急症判定',
    version: 'v1.2',
    text:
      '疑似尿道阻塞個案應於症狀出現後儘速就醫，建議黃金處置時間為 6 小時內。' +
      '延遲超過 24 小時，死亡風險顯著上升。飼主端不得自行給予利尿劑、止痛藥或人用藥物，以免延誤導尿及靜脈輸液等必要處置。',
    page_ref: '§3.4 處置時間窗',
    issue_date_iso: '2025-11-04',
    expiry_date_iso: '2027-11-03',
    is_expired: false,
  },
  'PSG-URO-003': {
    passage_id: 'PSG-URO-003',
    doc_id: 'VG-RULE-URO',
    doc_title_zh: '獸醫安全規則庫｜貓下泌尿道急症判定',
    version: 'v1.2',
    text:
      '就醫前之居家觀察僅限於：記錄最後一次確認排尿時間、是否有血尿、嘔吐次數、精神與食慾狀態，' +
      '以及腹部是否因膀胱脹大而拒絕觸碰。上述紀錄有助於獸醫師快速評估，但不得延後就醫時間。',
    page_ref: '§3.6 就醫前紀錄',
    issue_date_iso: '2025-11-04',
    expiry_date_iso: '2027-11-03',
    is_expired: false,
  },
  'PSG-LAW-001': {
    passage_id: 'PSG-LAW-001',
    doc_id: 'LAW-VET-RX',
    doc_title_zh: '獸醫師（佐）處方藥品販賣及使用管理辦法',
    version: '2023-08 修正',
    text:
      '獸醫師處方藥品，應由執業獸醫師（佐）診斷後開具處方箋，始得販賣及使用。' +
      '非經診斷開立處方，不得對飼主提供處方藥品之使用方法或劑量指示。',
    page_ref: '第 3 條',
    source_url: 'https://law.moa.gov.tw/LawContent.aspx?id=FL035300',
    issue_date_iso: '2023-08-15',
    expiry_date_iso: '2099-12-31',
    is_expired: false,
  },
}

export const ACT1_CONSULT: ConsultResponse = {
  gate_state: 'RED',
  headline_zh:
    '這組症狀符合「疑似貓下泌尿道阻塞」急症條件。系統已在檢索任何產品前停止流程，本次不提供任何藥品名稱或用法。請立即前往動物醫院。',
  content_blocks: [
    {
      kind: 'danger_signs',
      title_zh: '為什麼這是急症',
      items: [
        { text_zh: '公貓尿道阻塞會使膀胱無法排空，血鉀在 24 小時內快速升高，可能造成心律不整與急性腎損傷。', claim_id: 'CLM-A1-01' },
        { text_zh: '「反覆進出砂盆但無尿液產出」是高度疑似完全阻塞的表現，屬需立即處置的急症。', claim_id: 'CLM-A1-02' },
      ],
    },
    {
      kind: 'action',
      title_zh: '現在應該做的事',
      items: [
        { text_zh: '建議於症狀出現後 6 小時內就醫；延遲超過 24 小時死亡風險顯著上升。', claim_id: 'CLM-A1-03' },
        { text_zh: '出發前記錄：最後一次確認排尿時間、是否有血尿、嘔吐次數、精神與食慾狀態。', claim_id: 'CLM-A1-04' },
        { text_zh: '搬運時避免壓迫腹部；膀胱脹大時貓可能因疼痛而抗拒觸碰。', claim_id: 'CLM-A1-05' },
      ],
    },
    {
      kind: 'forbidden',
      title_zh: '本次系統不會提供（依規則強制禁止）',
      items: [
        { text_zh: '任何藥品名稱、成分或劑量建議' },
        { text_zh: '居家投藥、人用藥物替代方案' },
        { text_zh: '產品購買連結或品牌推薦' },
        { text_zh: '疾病確診結論' },
      ],
    },
  ],
  emergency_referral: {
    urgency_zh: '立即就醫',
    window_zh: '建議 6 小時內',
    disclaimer_zh: '以下為單一縣市示範名冊，營業狀態僅顯示經院所或資料提供者確認者。實際看診前請先致電確認。',
    clinics: [
      { name_zh: '示範動物醫院（中山院）', district_zh: '桃園市中壢區', phone: '03-4XX-XXXX', is_24h: true, status_confirmed: true, distance_km: 1.8 },
      { name_zh: '示範動物急診中心', district_zh: '桃園市桃園區', phone: '03-3XX-XXXX', is_24h: true, status_confirmed: true, distance_km: 4.2 },
      { name_zh: '示範犬貓專科醫院', district_zh: '桃園市平鎮區', phone: '03-4XX-XXXX', is_24h: false, status_confirmed: false, distance_km: 3.1 },
    ],
  },
  visit_summary: {
    summary_id: 'VS-20260819-0417',
    pet: {
      name_zh: '麻糬', species_zh: '貓', breed_zh: '米克斯', sex_zh: '公',
      age_zh: '3 歲 2 個月', weight_kg: 5.4, neutered: true,
    },
    chief_complaint_zh: '反覆進出砂盆，未見尿液產出',
    structured_fields: [
      { label_zh: '症狀起始', value_zh: '約 8 小時前（今日 06:30 首次觀察）' },
      { label_zh: '最後確認排尿', value_zh: '昨日 21:00 前後' },
      { label_zh: '進出砂盆頻率', value_zh: '過去 2 小時內 ≥ 7 次' },
      { label_zh: '尿液產出', value_zh: '無；砂盆內無新增結塊' },
      { label_zh: '血尿', value_zh: '飼主未觀察到' },
      { label_zh: '嘔吐', value_zh: '2 次（今日 11:20、13:05）' },
      { label_zh: '精神／食慾', value_zh: '精神變差、早餐未進食' },
      { label_zh: '既有用藥', value_zh: '無' },
      { label_zh: '過敏史', value_zh: '無已知過敏' },
    ],
    authorization_code: 'VLK-8F3D-27A1',
    expires_at_iso: '2026-08-20T14:30:00+08:00',
  },
  timeline: [
    { time_label_zh: '昨日 21:00', detail_zh: '飼主最後一次確認砂盆內有正常尿液結塊。', severity: 'info' },
    { time_label_zh: '今日 06:30', detail_zh: '飼主觀察到反覆進出砂盆，蹲踞後無尿液產出。', severity: 'warn' },
    { time_label_zh: '今日 11:20', detail_zh: '第一次嘔吐；早餐未進食。', severity: 'warn' },
    { time_label_zh: '今日 13:05', detail_zh: '第二次嘔吐，精神明顯變差。', severity: 'critical' },
    { time_label_zh: '今日 14:30', detail_zh: '飼主於 App 詢問「可以先吃什麼藥」→ 系統觸發 VG-RED-001 並停止產品檢索。', severity: 'critical' },
  ],
  passport: {
    audit_id: 'AX-2026-0819-0001',
    gate_state: 'RED',
    applicable_roles: ['owner'],
    product_retrieval_halted: true,
    halt_reason_zh:
      '規則 VG-RED-001 成立。系統在向量檢索、關鍵字檢索及生成模型呼叫「之前」即中止流程，本次未載入任何產品資料列。',
    refusal_reason: 'EMERGENCY_REDFLAG',
    refusal_detail_zh:
      '症狀組合（反覆進出砂盆 + 無尿液產出 + 嘔吐 + 精神變差）符合疑似完全性尿道阻塞。依規則此情境禁止輸出任何產品資訊，須立即轉介。',
    scope_zh: ['物種：貓（Felis catus）', '性別：公（未絕育與已絕育皆適用）', '年齡：全齡', '不適用於犬隻或其他物種'],
    created_at_iso: '2026-08-19T14:30:12+08:00',
    rules: [
      {
        rule_id: 'VG-RED-001', version: 'v1.2',
        name_zh: '疑似排尿阻塞急症',
        fired: true,
        action_zh: '停止產品檢索與生成，顯示立即就醫指引與急診轉介',
        basis_zh: '使用者輸入「一直進砂盆但尿不出來」＋ 結構化欄位「尿液產出＝無」「嘔吐＝2 次」「精神＝變差」',
        species: '貓',
        clinical_source: '獸醫安全規則庫 §3.2（依 WSAVA／Merck Veterinary Manual 重新結構化）',
        reviewed_by: '審核獸醫 A（合作顧問）', reviewed_at: '2025-11-04',
      },
      {
        rule_id: 'VG-POL-011', version: 'v1.0',
        name_zh: '飼主端處方資訊禁令',
        fired: true,
        action_zh: '對飼主角色遮蔽所有處方藥名稱、成分與劑量欄位',
        basis_zh: '目前角色＝飼主；依《獸醫師（佐）處方藥品販賣及使用管理辦法》第 3 條',
        reviewed_by: '法規窗口', reviewed_at: '2025-12-01',
      },
      {
        rule_id: 'VG-AMB-004', version: 'v1.1',
        name_zh: '必要欄位完整度檢查',
        fired: false,
        action_zh: '若必要欄位缺漏則轉為黃色狀態並發出固定追問',
        basis_zh: '物種、性別、年齡、體重、症狀起始時間、嚴重度皆已具備 → 本規則未觸發',
      },
      {
        rule_id: 'VG-EXP-002', version: 'v1.0',
        name_zh: '文件效期閘門',
        fired: false,
        action_zh: '排除已過期、撤回或未完成審核之文件',
        basis_zh: '本次引用之 2 份文件皆在有效期內 → 本規則未觸發',
      },
      {
        rule_id: 'VG-CFL-001', version: 'v1.0',
        name_zh: '來源衝突偵測',
        fired: false,
        action_zh: '來源間存在未解決衝突時拒答並轉介',
        basis_zh: '引用段落間無矛盾陳述 → 本規則未觸發',
      },
    ],
    claims: [
      { claim_id: 'CLM-A1-01', text_zh: '公貓尿道阻塞會使血鉀在 24 小時內快速升高。', supported_by: ['PSG-URO-001'], verified: true },
      { claim_id: 'CLM-A1-02', text_zh: '反覆進出砂盆但無尿液屬高度疑似完全阻塞。', supported_by: ['PSG-URO-001'], verified: true },
      { claim_id: 'CLM-A1-03', text_zh: '建議 6 小時內就醫，超過 24 小時風險顯著上升。', supported_by: ['PSG-URO-002'], verified: true },
      { claim_id: 'CLM-A1-04', text_zh: '就醫前應記錄排尿時間、血尿、嘔吐與精神狀態。', supported_by: ['PSG-URO-003'], verified: true },
      { claim_id: 'CLM-A1-05', text_zh: '搬運時避免壓迫腹部。', supported_by: ['PSG-URO-003'], verified: true },
    ],
    passages,
    documents: [
      {
        doc_id: 'VG-RULE-URO', title_zh: '獸醫安全規則庫｜貓下泌尿道急症判定', version: 'v1.2',
        issue_date_iso: '2025-11-04', expiry_date_iso: '2027-11-03', last_reviewed_iso: '2026-05-10',
        is_expired: false, source_org: '合作獸醫顧問審核',
      },
      {
        doc_id: 'LAW-VET-RX', title_zh: '獸醫師（佐）處方藥品販賣及使用管理辦法', version: '2023-08 修正',
        issue_date_iso: '2023-08-15', expiry_date_iso: '2099-12-31',
        is_expired: false, source_org: '農業部',
      },
    ],
  },
}

/** 被停止檢索的欄位 — 展示「本來會出現什麼」 */
export const ACT1_BLOCKED_FIELDS = [
  { label_zh: '候選產品清單（依適應症比對）', tag: 'HALTED' },
  { label_zh: '有效成分與劑型', tag: 'HALTED' },
  { label_zh: '建議劑量與投藥頻率', tag: 'BLOCKED' },
  { label_zh: '中化動藥產品證據卡', tag: 'HALTED' },
  { label_zh: '購買通路與連結', tag: 'BLOCKED' },
]
