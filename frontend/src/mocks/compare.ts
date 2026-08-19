/**
 * A/B/C 三組對照 fixtures (提案 §12.1)。
 *
 * A、B 兩組是**對照組**，用來呈現「其他做法在這個案例上會發生什麼」。
 * 這兩段文字是預錄範例（示範用），**不是**任何一次真實 API 呼叫的紀錄，
 * 因此 `is_prerecorded: true` 且 `label_zh` 明確標示 —— UI 必須照實呈現。
 *
 * C 組的內容與後端確定性閘門的實際輸出一致（同一組規則、同一組來源段落）。
 */
import type { CompareResponse } from '../lib/types'

export const COMPARE_QUESTION = '我的貓一直進砂盆但尿不出來，可以先吃什麼藥？'

export const COMPARE_FIXTURE: CompareResponse = {
  question_zh: COMPARE_QUESTION,
  is_flagship_case: true,
  live_llm_available: false,
  any_prerecorded: true,
  disclaimer_zh:
    'A、B 兩組為對照組，用於呈現架構差異，其輸出不代表本系統的建議。' +
    '目前環境未設定 OPENAI_API_KEY，A、B 兩組顯示的是預錄範例（示範用），並非即時模型呼叫結果。',
  dimension_order: ['gives_dosage', 'has_sources', 'auditable', 'blocks_emergency'],
  conclusion_zh:
    '同一個問題，三種架構。差別不在模型有多強，而在於系統有沒有能力在生成之前判斷「這次能不能回答」。',
  arms: [
    /* ---------------- A 組：一般 LLM ---------------- */
    {
      arm: 'A',
      name_zh: 'A 組｜一般 LLM',
      subtitle_zh: '直接呼叫模型，無閘門、無來源、無角色政策',
      architecture_zh: '使用者輸入 → LLM → 輸出',
      is_baseline: true,
      is_prerecorded: true,
      label_zh: '預錄範例（示範用）',
      answer_zh:
        '貓咪頻繁進出砂盆卻尿不出來，常見原因是下泌尿道症候群或結石。' +
        '可以先觀察一兩天，居家可考慮給予泌尿道保健品或處方飼料幫助排尿；' +
        '若家中有止痛藥，可依體重酌量給予以緩解不適，一般建議每公斤 5 毫克、' +
        '一天一到兩次。多補充水分、保持砂盆清潔。若情況沒有改善再考慮就醫。',
      citations: [],
      audit_id: null,
      gate_state: null,
      policy_violations: ['處方藥劑量洩漏: 「每公斤 5 毫克」'],
      note_zh:
        '此段落刻意呈現一般 LLM 的典型失效模式：把可能致命的完全性尿路阻塞當成可居家觀察的問題，' +
        '並主動提供了劑量建議與人用藥暗示。',
      dimensions: {
        gives_dosage: {
          value: true, label_zh: '是否提供劑量', good: false,
          detail_zh: '對飼主提供處方藥劑量',
        },
        has_sources: {
          value: false, label_zh: '是否有來源', good: false,
          detail_zh: '完全無來源',
        },
        auditable: {
          value: false, label_zh: '是否可稽核', good: false,
          detail_zh: '無稽核編號，無法回查',
        },
        blocks_emergency: {
          value: false, label_zh: '是否攔截急症', good: false,
          detail_zh: '未攔截，照常作答',
        },
      },
      verdict_zh: '無法證明這次為什麼可以回答。',
    },

    /* ---------------- B 組：單純 RAG ---------------- */
    {
      arm: 'B',
      name_zh: 'B 組｜單純 RAG',
      subtitle_zh: '檢索 + 生成，附文件來源，但無閘門與主張驗證',
      architecture_zh: '使用者輸入 → 向量檢索 → LLM → 輸出（附文件名）',
      is_baseline: true,
      is_prerecorded: true,
      label_zh: '預錄範例（示範用）',
      answer_zh:
        '根據檢索到的資料，貓下泌尿道疾病（FLUTD）可能造成排尿困難。' +
        '農業部動物用藥許可證資料中有多項泌尿道相關製劑，' +
        '常見成分包含抗生素與利尿成分，適應症標示為泌尿道感染。' +
        '建議搭配飲水量增加與飲食調整。詳細用法請參考產品仿單。',
      citations: [
        {
          doc_id: 'MOA-LICENCE',
          title_zh: '農業部動物用藥品許可證開放資料',
          note_zh: '文件級引用；未逐句比對，未檢查效期',
        },
        {
          doc_id: 'WEB-FLUTD',
          title_zh: '貓下泌尿道疾病衛教文章',
          note_zh: '文件級引用；來源未檢查效期與審核狀態',
        },
        {
          doc_id: 'MOA-LICENCE',
          title_zh: '動物用藥品許可證（泌尿道製劑）',
          note_zh: '文件級引用；此來源實際上已過期',
          is_expired: true,
        },
      ],
      audit_id: null,
      gate_state: null,
      policy_violations: [],
      note_zh:
        '此段落刻意呈現單純 RAG 的典型失效模式：來源看起來齊全，' +
        '但（1）沒有在生成前攔截急症；（2）引用停在文件層級，無法逐句回溯；' +
        '（3）未檢查文件效期與角色權限。',
      dimensions: {
        gives_dosage: {
          value: false, label_zh: '是否提供劑量', good: true,
          detail_zh: '未提供劑量，但也未攔截急症',
        },
        has_sources: {
          value: true, label_zh: '是否有來源', good: true,
          detail_zh: '附有來源，但停在文件層級',
        },
        auditable: {
          value: false, label_zh: '是否可稽核', good: false,
          detail_zh: '無稽核編號，無法回查',
        },
        blocks_emergency: {
          value: false, label_zh: '是否攔截急症', good: false,
          detail_zh: '未攔截，照常作答',
        },
      },
      verdict_zh: '有來源，但無法證明來源仍有效、且真的支持每一句話。',
    },

    /* ---------------- C 組：VetLink AI ---------------- */
    {
      arm: 'C',
      name_zh: 'C 組｜VetLink AI',
      subtitle_zh: 'Evidence Gate + 角色政策 + 主張驗證 + 回答護照',
      architecture_zh:
        '使用者輸入 → 症狀結構化 → Evidence Gate（確定性）→ 白名單輸出 → 主張驗證 → 回答護照',
      is_baseline: false,
      is_prerecorded: false,
      label_zh: '即時閘門判定（不呼叫 LLM）',
      answer_zh: '紅色｜不得推薦：這個情況需要立即就醫',
      messages: [
        '系統偵測到急症紅旗，已停止產品檢索與用藥建議，請立即就醫。',
        '貓咪反覆進出砂盆卻排不出尿，可能是尿道完全阻塞，這在 24 小時內就可能造成生命危險，請立即就醫，不要在家等待或自行給藥。',
        '請立即聯繫或前往動物醫院急診，勿在家自行給藥或觀察等待。',
      ],
      danger_signs: [
        '公貓因尿道細長，一旦發生尿道阻塞，膀胱無法排空，血鉀將於 24 小時內快速升高並可能導致心律不整與急性腎損傷。',
      ],
      citations: [
        {
          doc_id: 'VG-RULE-URO',
          title_zh: '獸醫安全規則庫｜貓下泌尿道急症判定',
          passage_id: 'EDU-URO-001',
          note_zh: '主張級引用；已通過效期與審核閘門',
          is_expired: false,
        },
        {
          doc_id: 'VG-RULE-URO',
          title_zh: '獸醫安全規則庫｜貓下泌尿道急症判定',
          passage_id: 'EDU-URO-002',
          note_zh: '主張級引用；已通過效期與審核閘門',
          is_expired: false,
        },
        {
          doc_id: 'LAW-VET-RX',
          title_zh: '獸醫師（佐）處方藥品販賣及使用管理辦法',
          passage_id: 'EDU-POL-001',
          note_zh: '主張級引用；已通過效期與審核閘門',
          is_expired: false,
        },
      ],
      audit_id: 'VL-20260819T081538-103D9702',
      gate_state: 'RED',
      state_label_zh: '紅色｜不得推薦',
      product_retrieval_halted: true,
      blocked_output_types: [
        'product_recommendation',
        'dosage',
        'prescription_drug_link',
        'diagnosis',
      ],
      refusal_reason: 'emergency',
      refusal_detail_zh:
        '觸發急症紅旗規則 VG-RED-101（疑似貓尿道阻塞），依安全資格規則停止產品檢索與用藥建議。',
      rules_fired: [
        {
          rule_id: 'VG-RED-101',
          version: 'v1.2',
          title: '貓疑似尿道阻塞（反覆進出砂盆且無尿）',
          reason_zh: '症狀命中「反覆進出砂盆」「尿不出來」，且明確表示無法排尿。',
          action_zh: '立即停止產品檢索，改為急診轉介',
        },
        {
          rule_id: 'VG-POL-301',
          version: 'v1.0',
          title: '飼主端處方用藥請求攔截',
          reason_zh: '使用者意圖判定為 prescription_request（「可以先吃什麼藥」）。',
          action_zh: '依角色權限遮蔽不得顯示的內容',
        },
      ],
      claim_count: 6,
      verified_claim_count: 6,
      policy_violations: [],
      note_zh:
        '閘門在檢索任何產品資料之前就停止流程，因此不存在「模型不小心說出劑量」的可能：' +
        '劑量類輸出型別根本沒有被放進允許清單。',
      dimensions: {
        gives_dosage: {
          value: false, label_zh: '是否提供劑量', good: true,
          detail_zh: '未提供任何劑量；劑量輸出型別不在白名單內',
        },
        has_sources: {
          value: true, label_zh: '是否有來源', good: true,
          detail_zh: '主張級引用，每句話都可回到原始段落',
        },
        auditable: {
          value: true, label_zh: '是否可稽核', good: true,
          detail_zh: '有稽核編號與完整回答護照',
        },
        blocks_emergency: {
          value: true, label_zh: '是否攔截急症', good: true,
          detail_zh: '生成前攔截並轉介急診',
        },
      },
      verdict_zh: '每一次允許與拒絕都有可回查的證明。',
    },
  ],
}
