import type { ConsultResponse, SourcePassage } from '../lib/types'

const passages: Record<string, SourcePassage> = {
  'PSG-AMB-001': {
    passage_id: 'PSG-AMB-001',
    doc_id: 'VG-RULE-INTAKE',
    doc_title_zh: '獸醫安全規則庫｜必要追問欄位定義',
    version: 'v1.1',
    text:
      '在提供任何衛教或產品類別資訊前，必須取得下列最小必要欄位：物種、年齡、體重、症狀起始時間、' +
      '症狀嚴重度及既有用藥。缺少任一欄位時，系統僅得就缺漏欄位提出固定追問，不得以推測值填補，' +
      '亦不得在欄位補齊前輸出衛教或產品資訊。',
    page_ref: '§1.3 最小必要欄位',
    issue_date_iso: '2025-11-04',
    expiry_date_iso: '2027-11-03',
    is_expired: false,
  },
  'PSG-AMB-002': {
    passage_id: 'PSG-AMB-002',
    doc_id: 'VG-RULE-INTAKE',
    doc_title_zh: '獸醫安全規則庫｜追問期間安全提醒',
    version: 'v1.1',
    text:
      '追問期間應同步提供不依賴診斷即成立之通用安全提醒，例如：出現呼吸費力、無法排尿、抽搐、' +
      '牙齦或舌頭發白發紫等情形時，應中止線上流程並立即就醫。此類提醒不構成診斷，亦不涉及產品資訊。',
    page_ref: '§1.5 追問期間提醒',
    issue_date_iso: '2025-11-04',
    expiry_date_iso: '2027-11-03',
    is_expired: false,
  },
}

/** 黃色狀態範例：飼主敘述過於模糊，系統只問固定必要問題 */
export const AMBER_CONSULT: ConsultResponse = {
  gate_state: 'AMBER',
  headline_zh:
    '目前資訊不足以判定風險等級。系統不會以推測值填補缺漏欄位，因此暫不提供任何衛教或產品類別資訊。請先回答下列必要問題。',
  content_blocks: [
    {
      kind: 'note',
      title_zh: '為什麼先追問而不直接回答',
      items: [
        { text_zh: '在取得最小必要欄位前，系統不得輸出衛教或產品資訊，也不得以推測值填補。', claim_id: 'CLM-AM-01' },
      ],
    },
    {
      kind: 'danger_signs',
      title_zh: '追問期間的通用安全提醒（不構成診斷）',
      items: [
        { text_zh: '出現呼吸費力、無法排尿、抽搐，或牙齦舌頭發白發紫時，請立即中止線上流程並就醫。', claim_id: 'CLM-AM-02' },
      ],
    },
  ],
  follow_up_questions: [
    { field: 'species', question_zh: '請問是犬還是貓？', options: ['犬', '貓'], required: true },
    { field: 'age', question_zh: '年齡大約是？', options: ['未滿 1 歲', '1–7 歲', '7 歲以上'], required: true },
    { field: 'weight', question_zh: '目前體重大約是？', options: ['未滿 5 公斤', '5–15 公斤', '15 公斤以上'], required: true },
    { field: 'onset', question_zh: '症狀從什麼時候開始？', options: ['未滿 24 小時', '1–3 天', '超過 3 天'], required: true },
    { field: 'severity', question_zh: '精神與食慾狀況如何？', options: ['與平常相同', '略微變差', '明顯變差或不進食'], required: true },
    { field: 'medication', question_zh: '目前有正在使用的藥物嗎？', options: ['沒有', '有（稍後填寫）', '不確定'], required: true },
  ],
  passport: {
    audit_id: 'AX-2026-0819-0003',
    gate_state: 'AMBER',
    applicable_roles: ['owner'],
    product_retrieval_halted: true,
    halt_reason_zh: '必要欄位未補齊，資料資格未通過，產品檢索尚未啟動。',
    refusal_reason: 'INSUFFICIENT_INFO',
    refusal_detail_zh: '缺少物種、年齡、體重、症狀起始時間、嚴重度及既有用藥等 6 項必要欄位。',
    scope_zh: ['尚未確定物種，適用範圍待補齊後判定'],
    created_at_iso: '2026-08-19T14:20:03+08:00',
    rules: [
      {
        rule_id: 'VG-AMB-004', version: 'v1.1',
        name_zh: '必要欄位完整度檢查',
        fired: true,
        action_zh: '轉為黃色狀態，僅輸出固定必要追問，不生成衛教或產品內容',
        basis_zh: '輸入「我家寶貝最近怪怪的，要吃什麼比較好？」未包含任何必要欄位',
      },
      {
        rule_id: 'VG-POL-021', version: 'v1.0',
        name_zh: '追問題目固定化',
        fired: true,
        action_zh: '追問題目由規則庫提供，不由生成模型自由產生',
        basis_zh: '6 題皆取自 VG-RULE-INTAKE §1.3 定義之欄位清單',
      },
      {
        rule_id: 'VG-RED-001', version: 'v1.2',
        name_zh: '疑似排尿阻塞急症',
        fired: false,
        action_zh: '若成立則停止產品檢索並轉介',
        basis_zh: '輸入未包含排尿相關描述 → 本規則未觸發',
      },
      {
        rule_id: 'VG-EXP-002', version: 'v1.0',
        name_zh: '文件效期閘門',
        fired: false,
        action_zh: '排除已過期或未審核文件',
        basis_zh: '引用之規則文件在有效期內 → 本規則未觸發',
      },
    ],
    claims: [
      { claim_id: 'CLM-AM-01', text_zh: '取得最小必要欄位前不得輸出衛教或產品資訊。', supported_by: ['PSG-AMB-001'], verified: true },
      { claim_id: 'CLM-AM-02', text_zh: '呼吸費力、無法排尿、抽搐、黏膜發白發紫應立即就醫。', supported_by: ['PSG-AMB-002'], verified: true },
    ],
    passages,
    documents: [
      { doc_id: 'VG-RULE-INTAKE', title_zh: '獸醫安全規則庫｜必要追問欄位定義', version: 'v1.1', issue_date_iso: '2025-11-04', expiry_date_iso: '2027-11-03', last_reviewed_iso: '2026-04-02', is_expired: false, source_org: '合作獸醫顧問審核' },
    ],
  },
}

export const AMBER_QUESTION = '我家寶貝最近怪怪的，要吃什麼比較好？'
