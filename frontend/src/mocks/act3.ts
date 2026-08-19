import type { ImpactReplayResponse } from '../lib/types'

/**
 * 第三幕：效期變更後的影響回溯。
 *
 * 本幕使用農業部開放資料中最具說服力的真實現象：
 * 13,738 筆許可證中有 9,120 筆已過期，其中 1,503 筆在來源資料的
 * 「有效期間」欄位裡完全沒有「(已失效)」標記 —— 只能把民國日期換算成
 * 西元日期並與今日比對，才判定得出。任何直接信任來源狀態欄位的系統，
 * 都會把這些許可證當作現行有效並提供給使用者。
 */

export const ACT3_IMPACT_REPLAY: ImpactReplayResponse = {
  doc_id: 'MOA-AD-07363',
  doc_title_zh: '動物用藥品許可證｜一錠除犬用滴劑（巨型犬）',
  old_version: 'v1.0f12615f8add',
  new_version: 'v2.expiry-recheck-20260819',
  effective_date_iso: '2026-08-19',
  stats: { scanned_answers: 1284, affected_answers: 5, high: 2, medium: 2, low: 1 },
  diffs: [
    {
      passage_id: 'PSG-EXP-07363',
      section_zh: '許可證效期欄位｜來源原文 vs 系統判定',
      old_version: '來源原始欄位（未經換算）',
      new_version: '系統效期閘門判定（2026-08-19 執行）',
      change_summary_zh:
        '來源資料的「有效期間」欄位僅寫「至115年06月30日止」，未附加任何 (已失效) 標記。經民國→西元換算為 2026-06-30，與今日 2026-08-19 比對後，判定已屆期 50 天。此類「來源未標示、僅能由日期判定」的許可證全庫共 1,503 筆。',
      segments: [
        { kind: 'unchanged', text: '許可證字號：動物藥入字第07363號｜品名：一錠除犬用滴劑（巨型犬）\n' },
        { kind: 'unchanged', text: '有效期間（來源原文）：「至115年06月30日止」' },
        { kind: 'removed', text: '　← 此欄位未出現 (已失效) 標記，來源狀態視同有效' },
        { kind: 'added', text: '\n民國115年06月30日 → 西元 2026-06-30' },
        { kind: 'added', text: '\n比對基準日 2026-08-19 → 已屆期 50 天' },
        { kind: 'added', text: '\n系統判定：is_expired = true（expired_by_date，非 expired_by_marker）' },
        { kind: 'added', text: '\n處置：自檢索結果排除，並啟動歷史回答影響回溯' },
      ],
    },
    {
      passage_id: 'PSG-EXP-FAMILY',
      section_zh: '同批次連帶影響｜同系列其他許可證',
      old_version: '單筆處理',
      new_version: '系列連帶回溯',
      change_summary_zh:
        '同一產品系列共 8 張許可證於 2026-06-30 及 2026-07-31 相繼屆期，來源皆未標示失效。系統以持證公司＋品名前綴比對後一併納入回溯範圍。',
      segments: [
        { kind: 'unchanged', text: '持證公司：台灣英特威動物藥品股份有限公司\n' },
        { kind: 'removed', text: '舊行為：逐筆等待人工發現，過期品項可能持續被引用。' },
        { kind: 'added', text: '\n新行為：偵測到 07359–07363（犬用，2026-06-30 屆期）' },
        { kind: 'added', text: '\n　　　　及 07368–07370（貓用，2026-07-31 屆期）共 8 張同系列許可證' },
        { kind: 'added', text: '\n　　　　全數標記為已過期，並一併掃描其歷史引用紀錄。' },
      ],
    },
  ],
  affected: [
    {
      audit_id: 'AX-2026-0715-0231',
      asked_at_iso: '2026-07-15T10:14:00+08:00',
      role: 'vet',
      question_zh: '巨型犬的壁蝨跳蚤預防，有哪些核准的外用滴劑可選？',
      cited_passage_id: 'PSG-EXP-07363',
      cited_claim_zh: '一錠除犬用滴劑（巨型犬）為現行有效之核准產品，適應症為治療犬隻壁蝨與跳蚤感染。',
      risk: 'HIGH',
      risk_reason_zh:
        '回答產生時（2026-07-15）該許可證已於 2026-06-30 屆期，但來源資料未標示失效，當時的效期換算基準日尚未涵蓋此筆。系統將其誤認為有效並納入推薦清單。',
      action_zh: '立即失效並通知曾查看之獸醫端使用者',
      new_status_zh: '已失效',
    },
    {
      audit_id: 'AX-2026-0802-0644',
      asked_at_iso: '2026-08-02T16:02:00+08:00',
      role: 'vet',
      question_zh: '大型貓適用的體外寄生蟲滴劑有哪些？',
      cited_passage_id: 'PSG-EXP-FAMILY',
      cited_claim_zh: '一錠除-全效貓用滴劑大型貓（美國廠）為現行有效之核准產品。',
      risk: 'HIGH',
      risk_reason_zh:
        '動物藥入字第07370號 於 2026-07-31 屆期，來源同樣未標示失效。此筆與上筆屬同一持證公司之同系列產品。',
      action_zh: '立即失效並通知曾查看之獸醫端使用者',
      new_status_zh: '已失效',
    },
    {
      audit_id: 'AX-2026-0620-0118',
      asked_at_iso: '2026-06-20T09:31:00+08:00',
      role: 'vet',
      question_zh: '中型犬與小型犬的滴劑劑量規格差異為何？',
      cited_passage_id: 'PSG-EXP-FAMILY',
      cited_claim_zh: '一錠除犬用滴劑依體重分為迷你、小型、中型、大型、巨型五種規格。',
      risk: 'MEDIUM',
      risk_reason_zh:
        '所述之規格分級為產品事實敘述，本身未因效期改變而錯誤；但引用之許可證已全數屆期，回答需補註「該系列許可證現況」方為完整。',
      action_zh: '進入人工重審，由獸醫顧問確認補註方式',
      new_status_zh: '待重審',
    },
    {
      audit_id: 'AX-2026-0708-0409',
      asked_at_iso: '2026-07-08T13:47:00+08:00',
      role: 'vet',
      question_zh: 'FLURALANER 這個成分的核准產品有哪些？',
      cited_passage_id: 'PSG-EXP-07363',
      cited_claim_zh: 'FLURALANER 於國內核准之外用滴劑劑型產品清單。',
      risk: 'MEDIUM',
      risk_reason_zh: '成分層級之陳述仍成立，但清單內容需依最新效期重新產生。',
      action_zh: '進入人工重審，重新執行檢索並比對清單',
      new_status_zh: '待重審',
    },
    {
      audit_id: 'AX-2026-0805-0912',
      asked_at_iso: '2026-08-05T11:05:00+08:00',
      role: 'admin',
      question_zh: '（後台）動物藥入字第07363號目前的版本與效期為何？',
      cited_passage_id: 'PSG-EXP-07363',
      cited_claim_zh: '版本 v1.0f12615f8add，有效期間至民國115年06月30日。',
      risk: 'LOW',
      risk_reason_zh: '僅為後設資料查詢，陳述之原始欄位值正確，僅需更新判定狀態標示。',
      action_zh: '自動更新效期狀態標示為「已過期（由日期判定）」',
      new_status_zh: '已更新標示',
    },
  ],
  tasks: [
    { task_id: 'RT-2026-0819-01', audit_id: 'AX-2026-0715-0231', assignee_zh: '獸醫顧問 A', due_date_iso: '2026-08-21', priority: 'HIGH', status_zh: '待處理' },
    { task_id: 'RT-2026-0819-02', audit_id: 'AX-2026-0802-0644', assignee_zh: '獸醫顧問 A', due_date_iso: '2026-08-21', priority: 'HIGH', status_zh: '待處理' },
    { task_id: 'RT-2026-0819-03', audit_id: 'AX-2026-0620-0118', assignee_zh: '內容治理窗口', due_date_iso: '2026-08-26', priority: 'MEDIUM', status_zh: '待處理' },
    { task_id: 'RT-2026-0819-04', audit_id: 'AX-2026-0708-0409', assignee_zh: '內容治理窗口', due_date_iso: '2026-08-26', priority: 'MEDIUM', status_zh: '待處理' },
  ],
  audit_log: [
    { ts_iso: '2026-08-19T15:02:11+08:00', actor_zh: '中化管理者（示範帳號 ADM-003）', event_zh: '執行每日效期重新判定', detail_zh: '批次載入農業部開放資料 13,738 筆許可證，基準日 2026-08-19' },
    { ts_iso: '2026-08-19T15:02:13+08:00', actor_zh: '系統｜效期正規化引擎', event_zh: '民國日期換算', detail_zh: '將「有效期間」欄位之民國紀年全數換算為西元 ISO 日期' },
    { ts_iso: '2026-08-19T15:02:15+08:00', actor_zh: '系統｜效期閘門', event_zh: '完成效期判定', detail_zh: '判定 9,120 筆已過期；其中 7,617 筆來源已標示 (已失效)，1,503 筆來源未標示、僅由日期比對判定' },
    { ts_iso: '2026-08-19T15:02:16+08:00', actor_zh: '系統｜效期閘門', event_zh: '偵測新增屆期品項', detail_zh: '動物藥入字第07363號 等同系列 8 張許可證於本期由「有效」轉為「已過期」，來源皆未標示失效' },
    { ts_iso: '2026-08-19T15:02:19+08:00', actor_zh: '系統｜影響查找引擎', event_zh: '掃描歷史回答', detail_zh: '掃描 1,284 筆具回答護照之歷史回答，命中引用已屆期許可證者 5 筆' },
    { ts_iso: '2026-08-19T15:02:23+08:00', actor_zh: '系統｜風險分級引擎', event_zh: '完成風險分級', detail_zh: '高風險 2 筆、中風險 2 筆、低風險 1 筆' },
    { ts_iso: '2026-08-19T15:02:25+08:00', actor_zh: '系統｜稽核引擎', event_zh: '執行處置', detail_zh: '2 筆立即失效、2 筆建立人工重審任務、1 筆自動更新版本標示' },
    { ts_iso: '2026-08-19T15:02:27+08:00', actor_zh: '系統｜通知服務', event_zh: '發出通知', detail_zh: '通知 2 名曾查看失效回答之獸醫端使用者，及 1 名內容治理窗口' },
    { ts_iso: '2026-08-19T15:02:27+08:00', actor_zh: '系統｜稽核引擎', event_zh: '寫入稽核紀錄', detail_zh: '本次回溯批次編號 IR-2026-0819-A，紀錄不可竄改且可回查' },
  ],
}

/** 「來源未標示 / 系統判定」對照 — 第三幕的核心證據 */
export const SILENT_EXPIRY_CASE = {
  licence_no: '動物藥入字第07363號',
  name_zh: '一錠除犬用滴劑（巨型犬）',
  company: '台灣英特威動物藥品股份有限公司',
  source_field_label: '來源資料「有效期間」欄位原文',
  source_field_value: '至115年06月30日止',
  source_marker: '無 (已失效) 標記',
  source_verdict: '狀態欄位視同有效',
  system_steps: [
    '讀取民國紀年字串「至115年06月30日止」',
    '正規化：民國 115 年 → 西元 2026 年',
    '解析為 ISO 日期 2026-06-30',
    '與判定基準日 2026-08-19 比對',
    '結論：已屆期 50 天 → is_expired = true',
  ],
  system_verdict: '已過期（expired_by_date）',
  scale_note:
    '全庫 13,738 筆許可證中，9,120 筆已過期；其中 1,503 筆與本例相同 —— 來源資料未附任何失效標記，只能靠日期換算與比對才判定得出。',
}

export const DATASET_EXPIRY_STATS = {
  total: 13738,
  expired_total: 9120,
  expired_marked: 7617,
  expired_silent: 1503,
  as_of: '2026-08-19',
}
