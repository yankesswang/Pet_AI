import type { VetSearchResponse, SourcePassage, ProductRecord } from '../lib/types'

/**
 * 第二幕資料 — 全部為農業部動物用藥開放資料之真實記錄。
 * 來源：https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx
 * 資料時點：2026-08-19（共 13,738 筆許可證）
 * 中國化學製藥股份有限公司持有 284 張許可證，其中 161 張現行有效、60 張為伴侶動物用。
 */

const passages: Record<string, SourcePassage> = {
  'PSG-PRD-07502': {
    passage_id: 'PSG-PRD-07502',
    doc_id: 'MOA-AD-07502',
    doc_title_zh: '動物用藥品許可證｜立免疼口服懸液劑0.5毫克/毫升（貓用）',
    version: 'v1.db7d7728a02c',
    licence_no: '動物藥入字第07502號',
    text:
      '核准效能及適應症（原文）：\n' +
      '貓：緩解手術後輕至中度疼痛及炎症反應，如骨科、軟組織手術；緩解慢性、急性肌肉骨骼疾病之發炎及疼痛。\n\n' +
      '成分（原文）：EACH ML CONTAINS：MELOXICAM ...... 0.5 MG\n' +
      '劑型：口服液劑｜核准物種：貓｜許可證持有者：中國化學製藥股份有限公司',
    page_ref: '許可證核准效能及適應症欄',
    source_url: 'https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx',
    issue_date_iso: '2024-01-12',
    expiry_date_iso: '2028-12-31',
    is_expired: false,
  },
  'PSG-PRD-08023': {
    passage_id: 'PSG-PRD-08023',
    doc_id: 'MOA-AD-08023',
    doc_title_zh: '動物用藥品許可證｜滴爾易懸液劑',
    version: 'v1.c2abfb41944d',
    licence_no: '動物藥製字第08023號',
    text:
      '核准效能及適應症（原文）：\n貓、犬：治療因黴菌、酵母菌、革蘭氏陰、陽性細菌引起之耳炎、皮膚感染。\n\n' +
      '成分（原文）：EACH ML CONTAINS: MICONAZOLE NITRATE 23MG / PREDNISOLONE ACETATE 5MG / POLYMYXIN B SULFATE 5500IU\n' +
      '劑型：外用液劑｜核准物種：犬、貓',
    page_ref: '許可證核准效能及適應症欄',
    source_url: 'https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx',
    issue_date_iso: '2002-08-30',
    expiry_date_iso: '2029-07-31',
    is_expired: false,
  },
  'PSG-PRD-09167': {
    passage_id: 'PSG-PRD-09167',
    doc_id: 'MOA-AD-09167',
    doc_title_zh: '動物用藥品許可證｜輕鬆洗',
    version: 'v1.ef3d1c178b0f',
    licence_no: '動物藥製字第09167號',
    text:
      '核准效能及適應症（原文）：\n犬、貓：幫助治療伴隨葡萄球菌和犬皮屑芽孢菌感染之皮脂漏皮膚炎、犬小芽孢菌、樣小芽孢菌和髮癬菌引起的皮癬菌感染（特別是錢癬），縮短其臨床症狀的時間及殺死具傳染性的孢子。\n\n' +
      '成分（原文）：EACH ML CONTAINS: CHLORHEXIDINE GLUCONATE...20MG / MICONAZOLE NITRATE...20MG\n' +
      '劑型：外用液劑｜核准物種：犬、貓',
    page_ref: '許可證核准效能及適應症欄',
    source_url: 'https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx',
    issue_date_iso: '2017-08-01',
    expiry_date_iso: '2027-07-31',
    is_expired: false,
  },
  'PSG-NSAID-RISK': {
    passage_id: 'PSG-NSAID-RISK',
    doc_id: 'VG-RULE-URO',
    doc_title_zh: '獸醫安全規則庫｜非類固醇消炎藥於泌尿急症之使用限制',
    version: 'v1.2',
    text:
      '疑似尿道阻塞個案在解除阻塞、完成靜脈輸液並確認腎功能與血鉀回穩之前，' +
      '不應使用非類固醇消炎藥（NSAID）。此類個案常伴隨脫水、腎前性氮血症與潛在急性腎損傷，' +
      'NSAID 會抑制前列腺素依賴之腎血流自我調節，顯著提高腎損傷風險。' +
      '止痛需求應優先考量在監護下使用類鴉片類藥物，並由獸醫師依個體狀況決定。',
    page_ref: '§4.1 止痛藥物選擇限制',
    issue_date_iso: '2025-11-04',
    expiry_date_iso: '2027-11-03',
    is_expired: false,
  },
  'PSG-BLK-201': {
    passage_id: 'PSG-BLK-201',
    doc_id: 'VG-RULE-URO',
    doc_title_zh: '獸醫安全規則庫｜角色政策說明',
    version: 'v1.2',
    text:
      '同一案例於飼主角色下觸發 VG-RED-001 與 VG-POL-011，系統停止產品檢索。' +
      '於獸醫角色下，VG-RED-001 仍記錄為成立（案例本質仍為急症），但 VG-POL-011 因角色資格通過而解除，' +
      '產品檢索改以「診斷／適應症 → 成分 → 核准產品」路徑開放。' +
      '系統仍不計算劑量、不產生處方，最終處置決策完整保留給獸醫師。',
    page_ref: '§7.1 角色差異',
    issue_date_iso: '2025-11-04',
    expiry_date_iso: '2027-11-03',
    is_expired: false,
  },
}

/** 真實 中化 伴侶動物許可證 — 現行有效 */
const results: ProductRecord[] = [
  {
    licence_no: '動物藥入字第07502號',
    name_zh: '立免疼口服懸液劑0.5毫克/毫升（貓用）',
    name_en: 'RHEUMOCAM 0.5 MG/ML ORAL SUSPENSION FOR CATS',
    company: '中國化學製藥股份有限公司',
    dosage_form: '口服液劑',
    ingredients_clean: 'MELOXICAM 0.5 MG / ML',
    indications_raw: '貓：緩解手術後輕至中度疼痛及炎症反應，如骨科、軟組織手術；緩解慢性、急性肌肉骨骼疾病之發炎及疼痛。',
    species: ['貓'],
    is_companion_animal: true,
    issue_date_iso: '2024-01-12',
    expiry_date_iso: '2028-12-31',
    is_expired: false,
    doc_id: 'MOA-AD-07502',
    version: 'v1.db7d7728a02c',
    source_url: 'https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx',
    claim_id: 'CLM-A2-01',
  },
  {
    licence_no: '動物藥製字第08023號',
    name_zh: '滴爾易懸液劑',
    name_en: 'EARZI SUSPENSION',
    company: '中國化學製藥股份有限公司台南官田工廠',
    dosage_form: '外用液劑',
    ingredients_clean: 'MICONAZOLE NITRATE 23MG / PREDNISOLONE ACETATE 5MG / POLYMYXIN B SULFATE 5500IU',
    indications_raw: '貓、犬：治療因黴菌、酵母菌、革蘭氏陰、陽性細菌引起之耳炎、皮膚感染。',
    species: ['犬', '貓'],
    is_companion_animal: true,
    issue_date_iso: '2002-08-30',
    expiry_date_iso: '2029-07-31',
    is_expired: false,
    doc_id: 'MOA-AD-08023',
    version: 'v1.c2abfb41944d',
    source_url: 'https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx',
    claim_id: 'CLM-A2-03',
  },
  {
    licence_no: '動物藥製字第09167號',
    name_zh: '輕鬆洗',
    name_en: 'EASY WASH',
    company: '中國化學製藥股份有限公司台南官田工廠',
    dosage_form: '外用液劑',
    ingredients_clean: 'CHLORHEXIDINE GLUCONATE 20MG / MICONAZOLE NITRATE 20MG',
    indications_raw:
      '犬、貓：幫助治療伴隨葡萄球菌和犬皮屑芽孢菌感染之皮脂漏皮膚炎、犬小芽孢菌、樣小芽孢菌和髮癬菌引起的皮癬菌感染（特別是錢癬），縮短其臨床症狀的時間及殺死具傳染性的孢子。',
    species: ['犬', '貓'],
    is_companion_animal: true,
    issue_date_iso: '2017-08-01',
    expiry_date_iso: '2027-07-31',
    is_expired: false,
    doc_id: 'MOA-AD-09167',
    version: 'v1.ef3d1c178b0f',
    source_url: 'https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx',
  },
]

/** 被閘門擋下的真實記錄 */
const filtered_out: VetSearchResponse['filtered_out'] = [
  {
    reason_zh:
      '核准物種為「犬」，與本案物種「貓」不符 → 依物種適用範圍排除。（本品為 CARPROFEN 錠劑，貓對 NSAID 代謝能力有限，跨物種套用具高風險。）',
    record: {
      licence_no: '動物藥製字第09057號',
      name_zh: '力停疼75毫克',
      name_en: 'PAINOFF CAPLETS 75MG',
      company: '中國化學製藥股份有限公司台南官田工廠',
      dosage_form: '錠劑',
      ingredients_clean: 'CARPROFEN 75MG',
      indications_raw: '犬：減輕犬隻的疼痛及發炎情況，並舒緩犬骨關節炎引起之相關症狀的臨床效果。',
      species: ['犬'],
      is_companion_animal: true,
      issue_date_iso: '2015-11-23',
      expiry_date_iso: '2030-11-30',
      is_expired: false,
      doc_id: 'MOA-AD-09057',
      version: 'v1.a0b4f2505bca',
      source_url: 'https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx',
    },
  },
  {
    reason_zh:
      '許可證有效期間至 2026-06-30（民國115年06月30日），已於 50 日前屆期 → 依 VG-EXP-002 排除。注意：來源資料此欄位「未標示（已失效）」，僅能由民國日期換算後比對今日才判定得出。',
    record: {
      licence_no: '動物藥入字第07363號',
      name_zh: '一錠除犬用滴劑（巨型犬）',
      name_en: 'BRAVECTO FLURALANER TOPICAL SOLUTION FOR DOGS (1400 MG)',
      company: '台灣英特威動物藥品股份有限公司',
      dosage_form: '外用液劑',
      ingredients_clean: 'FLURALANER 280 MG / ML',
      indications_raw: '犬：治療犬隻的壁蝨與跳蚤感染。 (詳見標籤仿單)',
      species: ['犬'],
      is_companion_animal: true,
      issue_date_iso: '2021-07-05',
      expiry_date_iso: '2026-06-30',
      is_expired: true,
      doc_id: 'MOA-AD-07363',
      version: 'v1.0f12615f8add',
      source_url: 'https://data.moa.gov.tw/Service/OpenData/FromM/ADProData.aspx',
    },
  },
]

export const ACT2_VET_SEARCH: VetSearchResponse = {
  query_zh: '貓／下泌尿道阻塞解除後之疼痛與後續管理／核准伴侶動物產品',
  total: results.length,
  results,
  filtered_out,
  passport: {
    audit_id: 'AX-2026-0819-0002',
    gate_state: 'BLUE',
    applicable_roles: ['vet'],
    product_retrieval_halted: false,
    scope_zh: [
      '物種：貓（跨物種產品已由閘門排除）',
      '情境：阻塞解除後之疼痛控制與後續管理',
      '本結果為核准適應症原文檢索，不構成處方',
      '劑量與投藥決策由獸醫師保留',
    ],
    created_at_iso: '2026-08-19T14:52:40+08:00',
    rules: [
      {
        rule_id: 'VG-BLUE-001',
        version: 'v1.0',
        name_zh: '獸醫身分與授權驗證',
        fired: true,
        action_zh: '解鎖藍色專業模式，開放核准仿單與許可證原文檢索',
        basis_zh: '獸醫執照驗證通過（示範帳號 VET-0142）＋ 飼主授權碼 VLK-8F3D-27A1 於有效期內',
        reviewed_by: '系統自動驗證',
        reviewed_at: '2026-08-19',
      },
      {
        rule_id: 'VG-RED-001',
        version: 'v1.2',
        name_zh: '疑似排尿阻塞急症',
        fired: true,
        action_zh: '案例仍標記為急症；產品資訊僅供獸醫師參考，不得回傳飼主端',
        basis_zh: '同一案例特徵不因角色改變；紅旗紀錄完整保留於稽核鏈',
      },
      {
        rule_id: 'VG-SPC-003',
        version: 'v1.0',
        name_zh: '物種適用範圍閘門',
        fired: true,
        action_zh: '排除核准物種不含「貓」之許可證',
        basis_zh: '動物藥製字第09057號（力停疼75毫克）核准物種僅「犬」→ 已排除',
      },
      {
        rule_id: 'VG-EXP-002',
        version: 'v1.0',
        name_zh: '文件效期閘門',
        fired: true,
        action_zh: '排除已逾有效期間之許可證，不進入檢索結果',
        basis_zh:
          '動物藥入字第07363號 有效期間至 2026-06-30，已屆期。來源資料未標示（已失效），由民國日期換算比對後判定。',
      },
      {
        rule_id: 'VG-POL-011',
        version: 'v1.0',
        name_zh: '飼主端處方資訊禁令',
        fired: false,
        action_zh: '（本角色不適用）目前角色為獸醫，處方資訊禁令解除',
        basis_zh: '角色資格檢查通過 → 本規則對本次請求未觸發',
      },
      {
        rule_id: 'VG-CLM-001',
        version: 'v1.1',
        name_zh: '主張驗證器',
        fired: false,
        action_zh: '任一主張若無來源段落支持即刪除或拒答',
        basis_zh: '本次 4 項主張全數比對到許可證原文段落 → 未觸發刪除',
      },
    ],
    claims: [
      {
        claim_id: 'CLM-A2-01',
        text_zh:
          '立免疼口服懸液劑（動物藥入字第07502號，中國化學製藥）核准用於貓，適應症含緩解慢性及急性肌肉骨骼疾病之發炎及疼痛。',
        supported_by: ['PSG-PRD-07502'],
        verified: true,
      },
      {
        claim_id: 'CLM-A2-02',
        text_zh:
          '本案在阻塞解除、輸液完成並確認腎功能與血鉀回穩前，不應使用 NSAID；此為規則層限制，非產品本身適應症問題。',
        supported_by: ['PSG-NSAID-RISK'],
        verified: true,
      },
      {
        claim_id: 'CLM-A2-03',
        text_zh: '滴爾易懸液劑（動物藥製字第08023號）核准用於犬貓耳炎與皮膚感染，屬外用液劑。',
        supported_by: ['PSG-PRD-08023'],
        verified: true,
      },
      {
        claim_id: 'CLM-A2-04',
        text_zh: '同一案例在飼主角色下被 VG-POL-011 阻擋，在獸醫角色下該規則解除，但急症紅旗紀錄仍保留。',
        supported_by: ['PSG-BLK-201'],
        verified: true,
      },
    ],
    passages,
    documents: [
      {
        doc_id: 'MOA-AD-07502',
        title_zh: '動物用藥品許可證｜立免疼口服懸液劑（貓用）',
        version: 'v1.db7d7728a02c',
        issue_date_iso: '2024-01-12',
        expiry_date_iso: '2028-12-31',
        last_reviewed_iso: '2026-08-19',
        is_expired: false,
        source_org: '農業部動植物防疫檢疫署',
      },
      {
        doc_id: 'MOA-AD-08023',
        title_zh: '動物用藥品許可證｜滴爾易懸液劑',
        version: 'v1.c2abfb41944d',
        issue_date_iso: '2002-08-30',
        expiry_date_iso: '2029-07-31',
        last_reviewed_iso: '2026-08-19',
        is_expired: false,
        source_org: '農業部動植物防疫檢疫署',
      },
      {
        doc_id: 'MOA-AD-09167',
        title_zh: '動物用藥品許可證｜輕鬆洗',
        version: 'v1.ef3d1c178b0f',
        issue_date_iso: '2017-08-01',
        expiry_date_iso: '2027-07-31',
        last_reviewed_iso: '2026-08-19',
        is_expired: false,
        source_org: '農業部動植物防疫檢疫署',
      },
      {
        doc_id: 'VG-RULE-URO',
        title_zh: '獸醫安全規則庫',
        version: 'v1.2',
        issue_date_iso: '2025-11-04',
        expiry_date_iso: '2027-11-03',
        is_expired: false,
        source_org: '合作獸醫顧問審核',
      },
    ],
  },
}

/** 飼主端 vs 獸醫端可見欄位對照 */
export const ROLE_DIFF_ROWS = [
  { field_zh: '症狀時間軸', owner: '可見（自己輸入的紀錄）', vet: '可見，含結構化嚴重度標記', vetOnly: false },
  { field_zh: '紅旗規則成立原因', owner: '僅顯示「急症、請立即就醫」', vet: '完整規則 ID、版本、判定依據與臨床出處', vetOnly: true },
  { field_zh: '核准適應症原文', owner: '不可見', vet: '可見，可點擊回許可證原文段落', vetOnly: true },
  { field_zh: '有效成分', owner: '不可見', vet: '可見（ingredients_clean 原文）', vetOnly: true },
  { field_zh: '劑型與物種限制', owner: '不可見', vet: '可見，含跨物種排除紀錄', vetOnly: true },
  { field_zh: '許可證字號與效期', owner: '不可見', vet: '可見，含效期閘門排除紀錄', vetOnly: true },
  { field_zh: '劑量與投藥頻率', owner: '不可見', vet: '由獸醫師依處方決定，系統不代為計算', vetOnly: false },
  { field_zh: '產品購買連結', owner: '不提供', vet: '不提供（本系統不做處方藥電商）', vetOnly: false },
]

/** 資料集事實 — 用於畫面上的可信度標註 */
export const DATASET_FACTS = {
  total_licences: 13738,
  expired: 9120,
  ccpc_total: 284,
  ccpc_valid: 161,
  ccpc_companion: 60,
  silent_expired: 1503,
  as_of: '2026-08-19',
}
