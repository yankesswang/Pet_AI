"""VetLink AI — 症狀結構化器 (提案 §7.1).

將飼主自然語言轉為結構化欄位。提案允許此模組「部分」由 LLM 協助，但**必須**通過
Schema 驗證。為了讓閘門決策完全可離線重現，本實作採確定性詞典比對，不呼叫 LLM。
若日後接入 LLM 抽取，輸出仍須經此處的 Schema 驗證後才進入閘門。

**症狀比對一律經過 `normalizer`**：先做表面正規化（簡繁／全半形／英文／口語），
再以子句斷言狀態過濾。只有「現在＋肯定」的命中會進入 `symptoms`，因此
「牠沒有尿不出來」「上個月尿不出來已出院」「如果尿不出來會怎樣」「我朋友的狗」
都不會觸發紅旗。被過濾掉的命中保留在 `symptoms_by_assertion`，供稽核軌跡查閱。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..models import BodySize, ConsultRequest, Intent, Mentation, Species
from .normalizer import Assertion, NormalizedText, normalize

# --------------------------------------------------------------------------
# 詞典 — 症狀正規化
# --------------------------------------------------------------------------
SYMPTOM_LEXICON: Dict[str, List[str]] = {
    # 泌尿
    "反覆進出砂盆": ["一直進砂盆", "反覆進出砂盆", "頻繁進砂盆", "進出貓砂盆", "一直跑廁所", "反覆去砂盆", "一直去貓砂盆", "跑去廁所蹲", "蹲在貓砂盆", "蹲在砂盆", "進廁所蹲", "跑廁所蹲", "蹲很久"],
    "排尿困難": ["排尿困難", "尿不太出來", "用力排尿", "解尿困難", "尿很久", "蹲很久尿不出", "擠了半天", "用力擠", "蹲很久起來後沒", "擠出幾滴", "只擠出", "用力排"],
    "尿不出來": ["尿不出來", "尿不出", "尿布出來", "尿不粗乃", "尿布粗來", "完全沒尿", "無法排尿", "解不出尿", "沒有尿", "什麼都排不出來", "排不出來", "出不來", "尿不太出來", "沒看到尿", "擠不出尿", "什麼都尿不出"],
    "頻尿": ["頻尿", "一直尿", "尿很多次", "排尿次數增加"],
    "血尿": ["血尿", "尿有血", "尿是紅的", "尿帶血", "粉紅色的水", "粉紅色的尿", "尿是粉紅"],
    "亂尿": ["亂尿", "在外面尿", "隨地小便"],
    # 呼吸
    "呼吸困難": ["呼吸困難", "呼吸急促", "喘得很厲害", "呼吸很喘", "呼吸不順", "胸口起伏很明顯", "大口吸氣", "吸不到氣", "呼吸很吃力", "喘不停", "哈氣停不下來"],
    "開口呼吸": ["開口呼吸", "張口呼吸", "用嘴巴呼吸", "張嘴喘", "嘴巴開開", "嘴巴張開喘", "嘴巴開著喘", "用力哈氣"],
    "呼吸費力": ["呼吸費力", "腹式呼吸", "肚子用力呼吸", "呼吸很用力", "肚子跟著一起用力起伏", "肚子一起用力", "呼吸時肚子很用力", "每分鐘呼吸超過"],
    "喘不過氣": ["喘不過氣", "快喘不過來"],
    "舌頭發紫": ["舌頭發紫", "舌頭變紫", "舌頭發黑", "舌頭顏色變得偏藍", "舌頭偏藍", "舌頭發藍", "舌頭紫紫"],
    "牙齦發白": ["牙齦發白", "牙齦蒼白", "牙齦很白"],
    "黏膜發紺": ["黏膜發紺", "發紺"],
    "咳嗽": ["咳嗽", "一直咳", "在咳"],
    "鵝鳴咳": ["鵝鳴咳", "鵝叫聲", "像鵝叫", "呼嚕咳", "乾咳像鵝叫"],
    "打噴嚏": ["打噴嚏", "噴嚏"],
    "鼻涕": ["鼻涕", "流鼻水"],
    "噎到": ["噎到", "嗆到東西", "卡到東西", "抓自己的脖子", "一直乾咳抓脖子", "像被卡住", "吸不到氣"],
    "異物卡喉": ["異物卡喉", "喉嚨卡東西", "吞到異物"],
    "中暑": ["中暑", "熱衰竭", "曬太久喘", "曬太久", "太陽下太久", "摸起來燙燙", "體溫很燙", "趴著哈氣停不下來"],
    # 腸胃
    "嘔吐": ["嘔吐", "吐了", "在吐", "吐出來"],
    "持續嘔吐": ["持續嘔吐", "一直吐", "吐個不停", "狂吐", "吐超過", "吐了八次", "吐到現在", "一直吐個不停", "吐了好多次", "從半夜吐到"],
    "喝水就吐": ["喝水就吐", "喝水也吐", "連水都吐", "連舔水都會馬上吐", "舔水也吐", "喝水馬上吐", "連水都留不住"],
    "腹瀉": ["腹瀉", "拉肚子", "水便", "軟便拉稀", "又吐又拉", "一直拉", "拉稀"],
    "軟便": ["軟便", "便便很軟"],
    "血便": ["血便", "便便有血", "大便帶血", "便便帶血腥味", "大便有血絲", "便帶血"],
    "黑便": ["黑便", "柏油便", "大便黑色", "黑色柏油", "大便是黑的", "便便黑黑的", "大便像瀝青", "黑亮", "像瀝青一樣", "大便黑亮"],
    "腹部脹大": ["腹部脹大", "肚子脹", "肚子鼓起", "腹部膨脹", "肚子下面硬硬", "肚子鼓鼓", "肚子鼓得很大", "肚子看起來鼓", "硬硬的像顆球", "肚子脹得像"],
    "乾嘔": ["乾嘔", "想吐吐不出來", "作嘔沒東西", "做出要吐的動作卻什麼都", "想吐卻吐不出", "作嘔", "乾噦"],
    "食慾下降": ["食慾下降", "不吃東西", "沒食慾", "吃很少", "不太吃"],
    # 中毒
    "誤食巧克力": ["吃到巧克力", "誤食巧克力", "偷吃巧克力", "吃掉了巧克力"],
    "誤食洋蔥": ["吃到洋蔥", "誤食洋蔥"],
    "誤食葡萄": ["吃到葡萄", "誤食葡萄", "吃了葡萄乾"],
    "誤食百合": ["咬了百合", "誤食百合", "啃百合"],
    "吃到老鼠藥": ["吃到老鼠藥", "誤食老鼠藥", "滅鼠藥"],
    "誤食殺蟲劑": ["誤食殺蟲劑", "舔到殺蟲劑", "吃到蟑螂藥"],
    "誤食木糖醇": ["木糖醇", "無糖口香糖", "口香糖", "代糖"],
    "中毒": ["中毒", "疑似中毒", "誤喝", "藍綠色的液體", "舔了藥膏", "雙氯芬酸", "夏威夷豆", "澳洲堅果"],
    # 人用藥
    "吃了普拿疼": ["普拿疼", "acetaminophen", "乙醯胺酚", "泰諾"],
    "吃了布洛芬": ["布洛芬", "ibuprofen", "止痛藥布洛芬"],
    "給了阿斯匹靈": ["阿斯匹靈", "aspirin"],
    "人用感冒藥": ["人的感冒藥", "人用感冒藥", "我的感冒藥"],
    # 皮膚耳部
    "搔癢": ["搔癢", "一直抓", "抓癢", "很癢"],
    "掉毛": ["掉毛", "禿了", "毛掉光"],
    "紅疹": ["紅疹", "起疹子", "皮膚紅"],
    "皮屑": ["皮屑", "頭皮屑"],
    "臉部腫脹": ["臉腫", "臉部腫脹", "臉水腫"],
    "嘴唇腫": ["嘴唇腫", "嘴巴腫"],
    "眼皮腫": ["眼皮腫", "眼睛腫"],
    "蕁麻疹": ["蕁麻疹", "全身起包"],
    "耳朵有異味": ["耳朵有異味", "耳朵臭", "耳朵味道重"],
    "耳朵分泌物": ["耳朵分泌物", "耳朵有髒東西", "耳垢很多"],
    "抓耳朵": ["抓耳朵", "一直抓耳"],
    "甩頭": ["甩頭", "一直甩頭"],
    "歪頭": ["歪頭", "頭歪一邊"],
    "眼球震顫": ["眼球震顫", "眼睛一直抖"],
    "深層咬傷": ["咬傷", "被咬了一個洞", "深層咬傷", "咬了一個很深的洞", "咬出一個洞", "被咬到見肉"],
    "大面積傷口": ["大傷口", "大面積傷口", "皮開肉綻"],
    # 全身
    "抽搐": ["抽搐", "抽筋", "痙攣", "僵直倒地", "四肢像划水", "四肢划水", "身體僵直抖動", "抖動了兩分鐘", "全身在抖"],
    "癲癇": ["癲癇", "發作"],
    "口吐白沫": ["口吐白沫", "吐白沫", "嘴角流很多口水", "嘴角一直流口水", "流很多口水"],
    "意識喪失": ["意識喪失", "昏過去"],
    "倒下": ["倒下", "倒在地上", "癱著"],
    "叫不醒": ["叫不醒", "沒有反應"],
    "意識不清": ["意識不清", "神智不清"],
    "站不起來": ["站不起來", "爬不起來", "無法站立", "後腳拖著走", "拖著走", "站不穩", "走路有點晃", "走路會晃"],
    "虛弱": ["虛弱", "很沒力", "軟綿綿", "整隻癱在地上", "整隻沒力氣", "沒力氣", "癱在地上", "懶洋洋不想動", "不想動"],
    "車禍": ["車禍", "被車撞", "被機車撞", "被腳踏車撞", "被車撞到", "撞到"],
    "從高處掉下來": ["從高處掉下來", "墜樓", "從陽台掉", "從二樓窗台摔下來", "從窗台摔", "從高處摔"],
    "大量出血": ["大量出血", "血流不止"],
    "骨折": ["骨折", "腳斷了"],
    "難產": ["難產", "生不出來", "用力生了", "只看到一個水袋", "水袋", "還沒有小狗出來", "生了很久"],
    "眼球突出": ["眼球突出", "眼睛凸出來", "整顆凸在外面", "眼睛凸出", "眼球凸出", "眼珠凸出"],
    "眼睛劇痛": ["眼睛劇痛", "眼睛痛到睜不開"],
    "眼睛突然看不見": ["突然看不見", "眼睛看不到"],
}

SPECIES_LEXICON: Dict[Species, List[str]] = {
    Species.CAT: ["貓", "貓咪", "喵", "貓貓", "cat", "kitten", "幼貓"],
    Species.DOG: ["狗", "狗狗", "犬", "汪", "dog", "puppy", "幼犬"],
}

MENTATION_LEXICON: Dict[Mentation, List[str]] = {
    Mentation.COLLAPSED: [
        "倒下", "叫不醒", "意識不清", "站不起來", "癱軟", "沒有反應", "昏迷",
        # 留出集揭露的缺漏：飼主口語說「癱在地上」而不說「倒下」，
        # 少了它 VG-RED-202（持續嘔吐合併虛弱）無法成立而漏判。
        "癱在地上", "整隻癱", "趴著不動", "躺著不動", "倒臥",
    ],
    Mentation.LETHARGIC: [
        "精神差", "沒精神", "懶洋洋", "很累", "不太動", "精神不好", "沉鬱",
        # 「虛弱」語意等同精神沉鬱，須納入 mentation 判定，否則
        # VG-RED-204（黑便合併虛弱）等紅旗規則會因缺值而無法成立。
        "很沒力", "沒力氣", "虛弱", "軟綿綿", "無力",
        "不想動", "懶洋洋不想動", "提不起勁", "整隻沒力氣", "沒什麼力氣",
    ],
    Mentation.NORMAL: ["精神正常", "精神很好", "活力正常", "還是很活潑"],
}

INTENT_LEXICON: Dict[Intent, List[str]] = {
    Intent.DOSAGE_REQUEST: [
        "劑量", "要吃幾顆", "吃多少", "幾毫克", "幾mg", "怎麼餵", "餵幾次",
        "一天吃幾", "多少ml", "劑量多少", "用量",
    ],
    Intent.PURCHASE_REQUEST: [
        "哪裡買", "哪裡有賣", "購買連結", "網購", "蝦皮", "怎麼買", "買得到",
        "推薦哪個牌子", "買什麼藥",
    ],
    Intent.PRESCRIPTION_REQUEST: [
        "開藥", "給我藥", "可以吃什麼藥", "先吃什麼藥", "要用什麼藥", "什麼藥有效",
        "藥名", "處方",
    ],
    Intent.MEDICATION_CHANGE_REQUEST: [
        "可以停藥", "自己停藥", "換藥", "減量", "不想再吃", "停掉藥", "改成別的藥",
    ],
    Intent.DIAGNOSIS_REQUEST: [
        "是不是得了", "這是什麼病", "幫我診斷", "確定是不是", "是不是有", "是什麼病",
    ],
    Intent.CROSS_SPECIES_USE: [
        "狗的藥可以給貓", "犬用給貓", "狗藥給貓", "貓可以用狗的", "人的藥給",
        "犬用除蚤滴劑給貓",
    ],
}

HUMAN_DRUG_TOKENS = [
    "普拿疼", "acetaminophen", "乙醯胺酚", "泰諾", "布洛芬", "ibuprofen",
    "阿斯匹靈", "aspirin", "人的止痛藥", "人用感冒藥", "我的感冒藥", "人的藥",
    # 留出集揭露的缺漏：飼主多半說「家裡的藥」而不說學名
    "那普洛芬", "naproxen", "家裡的止痛藥", "家裡的藥", "小孩的退燒藥",
    "小孩的藥", "退燒藥水", "人的退燒藥", "止痛藥膏", "雙氯芬酸", "diclofenac",
]

TOXIN_TOKENS = [
    "巧克力", "洋蔥", "葡萄", "葡萄乾", "百合", "老鼠藥", "滅鼠藥", "殺蟲劑",
    "蟑螂藥", "木糖醇", "中毒", "防凍劑",
    # 留出集揭露的缺漏：口語品名與非詞典寫法
    "夏威夷豆", "澳洲堅果", "無糖口香糖", "代糖", "藍綠色的液體", "乙二醇",
    "百合花", "咖啡", "酒精", "威士忌", "檳榔", "菸蒂", "尼古丁",
]

SCENARIO_KEYWORDS: Dict[str, List[str]] = {
    "泌尿": ["砂盆", "尿", "排尿", "膀胱", "小便"],
    "呼吸": ["呼吸", "喘", "咳", "噴嚏", "鼻", "窒息", "噎"],
    "腸胃": ["吐", "拉肚子", "腹瀉", "便", "食慾", "肚子", "誤食", "中毒", "巧克力", "洋蔥"],
    "皮膚耳部": ["癢", "抓", "毛", "皮膚", "耳朵", "疹", "腫", "傷口"],
}

DURATION_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(小時|天|日|週|周|星期|個月)")
WEIGHT_RE = re.compile(r"(\d+(?:\.\d+)?)\s*(?:公斤|kg|KG|Kg)")
AGE_RE = re.compile(r"(\d+)\s*(個月大|歲|月大)")
TEMP_RE = re.compile(r"(\d{2}(?:\.\d)?)\s*(?:度|℃|C)")

DURATION_TO_HOURS = {
    "小時": 1.0,
    "天": 24.0,
    "日": 24.0,
    "週": 168.0,
    "周": 168.0,
    "星期": 168.0,
    "個月": 720.0,
}


def _find_symptoms_with_assertion(
    norm: NormalizedText,
) -> Dict[str, Assertion]:
    """比對症狀並標記每個命中的斷言狀態。

    同一症狀在多個子句出現時，取**最接近現在肯定**的那個狀態：
    「上個月尿不出來，現在又尿不出來」必須是 PRESENT。
    """
    priority = {
        Assertion.PRESENT: 0,
        Assertion.NEGATED: 1,
        Assertion.HISTORICAL: 2,
        Assertion.HYPOTHETICAL: 3,
        Assertion.THIRD_PARTY: 4,
    }
    found: Dict[str, Assertion] = {}
    text = norm.normalized
    for canonical, variants in SYMPTOM_LEXICON.items():
        for v in variants:
            idx = text.find(v)
            while idx >= 0:
                a = norm.assertion_at(idx)
                if canonical not in found or priority[a] < priority[found[canonical]]:
                    found[canonical] = a
                if a is Assertion.PRESENT:
                    break
                idx = text.find(v, idx + 1)
    return found


def _find_symptoms(text: str) -> List[str]:
    """僅回傳現在且肯定的症狀（保留給既有呼叫端與測試）。"""
    hits = _find_symptoms_with_assertion(normalize(text))
    return [k for k, a in hits.items() if a is Assertion.PRESENT]


def _token_present(norm: NormalizedText, tokens: List[str]) -> bool:
    """任一 token 以「現在＋肯定」語境出現才算成立。"""
    text = norm.normalized
    for t in tokens:
        idx = text.find(t)
        while idx >= 0:
            if norm.assertion_at(idx) is Assertion.PRESENT:
                return True
            idx = text.find(t, idx + 1)
    return False


def _find_species(text: str) -> Optional[Species]:
    hits = []
    for sp, tokens in SPECIES_LEXICON.items():
        for t in tokens:
            if t in text:
                hits.append(sp)
                break
    if len(hits) == 1:
        return hits[0]
    return None  # 零命中或同時提到貓狗 → 視為未知，交由黃色狀態追問


def _find_mentation(text: str) -> Optional[Mentation]:
    for m in (Mentation.COLLAPSED, Mentation.LETHARGIC, Mentation.NORMAL):
        for t in MENTATION_LEXICON[m]:
            if t in text:
                return m
    return None


def _find_intent(text: str) -> Intent:
    # 順序即優先序：跨物種 > 停換藥 > 劑量 > 處方 > 購買 > 診斷
    for intent in (
        Intent.CROSS_SPECIES_USE,
        Intent.MEDICATION_CHANGE_REQUEST,
        Intent.DOSAGE_REQUEST,
        Intent.PRESCRIPTION_REQUEST,
        Intent.PURCHASE_REQUEST,
        Intent.DIAGNOSIS_REQUEST,
    ):
        for token in INTENT_LEXICON[intent]:
            if token in text:
                return intent
    return Intent.GENERAL


def _find_duration_hours(text: str) -> Optional[float]:
    m = DURATION_RE.search(text)
    if not m:
        return None
    value, unit = float(m.group(1)), m.group(2)
    return value * DURATION_TO_HOURS.get(unit, 1.0)


def _find_scenarios(text: str, symptoms: List[str]) -> List[str]:
    scenarios: List[str] = []
    blob = text + " " + " ".join(symptoms)
    for scenario, keys in SCENARIO_KEYWORDS.items():
        if any(k in blob for k in keys):
            scenarios.append(scenario)
    return scenarios or ["跨情境"]


# --------------------------------------------------------------------------
# 體型 (提案 §5.1)
# --------------------------------------------------------------------------
# 飼主口語直接說出體型時的用詞。
SIZE_TOKENS = {
    BodySize.SMALL: ("小型犬", "小型狗", "小狗狗", "迷你犬"),
    BodySize.MEDIUM: ("中型犬", "中型狗"),
    BodySize.LARGE: ("大型犬", "大型狗", "巨型犬"),
}

# 由體重推導體型的分界（公斤）。採臨床常用的 10 / 25 公斤分界。
# 這是**推導**不是量測：飼主已明說體型時一律以明說者為準。
SIZE_SMALL_MAX_KG = 10.0
SIZE_MEDIUM_MAX_KG = 25.0


def size_from_weight(weight_kg: Optional[float]) -> Optional[BodySize]:
    """由體重推導體型；體重缺值或不合理時回傳 None（維持未知）。"""
    if weight_kg is None:
        return None
    if weight_kg <= 0 or weight_kg > 120:
        return None
    if weight_kg < SIZE_SMALL_MAX_KG:
        return BodySize.SMALL
    if weight_kg < SIZE_MEDIUM_MAX_KG:
        return BodySize.MEDIUM
    return BodySize.LARGE


def _find_body_size(text: str) -> Optional[BodySize]:
    """從自由描述抓出飼主明說的體型。"""
    for size, tokens in SIZE_TOKENS.items():
        if any(t in text for t in tokens):
            return size
    return None


def structure_case(req: ConsultRequest) -> Dict[str, Any]:
    """把 ConsultRequest 轉成規則引擎使用的 facts dict。

    明確給定的欄位一律優先於文字抽取結果。
    """
    raw_text = req.text or ""
    norm = normalize(raw_text)
    # 一律以正規化後的文字做下游抽取，讓簡體／英文／口語走同一條路徑。
    text = norm.normalized

    symptom_hits = _find_symptoms_with_assertion(norm)
    symptoms = [k for k, a in symptom_hits.items() if a is Assertion.PRESENT]
    # 非當下語境的命中不進入規則，但保留供稽核說明「為什麼沒觸發」。
    symptoms_by_assertion = {
        a.value: sorted(k for k, v in symptom_hits.items() if v is a)
        for a in Assertion
        if any(v is a for v in symptom_hits.values())
    }
    species = req.species or _find_species(text) or Species.UNKNOWN
    mentation = req.mentation or _find_mentation(text)
    intent = _find_intent(text)

    duration_hours = req.duration_hours
    if duration_hours is None:
        duration_hours = _find_duration_hours(text)

    body_weight_kg = req.body_weight_kg
    if body_weight_kg is None:
        m = WEIGHT_RE.search(text)
        if m:
            body_weight_kg = float(m.group(1))

    age_months = req.age_months
    if age_months is None:
        m = AGE_RE.search(text)
        if m:
            n = int(m.group(1))
            age_months = n * 12 if m.group(2) == "歲" else n

    temperature_c = req.temperature_c
    if temperature_c is None:
        m = TEMP_RE.search(text)
        if m:
            val = float(m.group(1))
            if 30.0 <= val <= 45.0:
                temperature_c = val

    # 毒物／人用藥暴露同樣受斷言過濾：「我朋友的狗誤食巧克力」與
    # 「哪些人類食物對狗有毒」都不是本案當下的暴露事件。
    human_drug_involved = _token_present(norm, HUMAN_DRUG_TOKENS)
    toxin_exposure = _token_present(norm, TOXIN_TOKENS)

    # can_urinate：明確欄位優先；否則由否定語意推導
    can_urinate = req.can_urinate
    if can_urinate is None:
        if any(s in symptoms for s in ("尿不出來",)):
            can_urinate = False
        elif "有尿出來" in text or "還是有尿" in text or "尿得出來" in text:
            can_urinate = True

    # 體型：明確欄位 > 飼主口語明說 > 由體重推導。
    # 貓不做體型分級（臨床差異遠小於犬），一律不填。
    body_size = req.body_size
    if body_size is None and species == Species.DOG:
        body_size = _find_body_size(text) or size_from_weight(body_weight_kg)

    facts: Dict[str, Any] = {
        "raw_text": raw_text,
        "normalized_text": text,
        "symptoms": symptoms,
        "symptoms_by_assertion": symptoms_by_assertion,
        "normalization_notes": norm.notes,
        "species": species.value if isinstance(species, Species) else species,
        "role": req.role.value,
        "intent": intent.value,
        "body_weight_kg": body_weight_kg,
        "body_size": body_size.value if isinstance(body_size, BodySize) else body_size,
        "age_months": age_months,
        "sex": req.sex,
        "duration_hours": duration_hours,
        "severity": req.severity,
        "current_medications": req.current_medications,
        "can_urinate": can_urinate,
        "vomiting": req.vomiting if req.vomiting is not None else ("嘔吐" in symptoms or "持續嘔吐" in symptoms or None),
        "mentation": mentation.value if isinstance(mentation, Mentation) else mentation,
        "breathing_effort": req.breathing_effort,
        "mucous_membrane_color": req.mucous_membrane_color,
        "temperature_c": temperature_c,
        "vomit_count_24h": req.vomit_count_24h,
        "can_keep_water": req.can_keep_water,
        "human_drug_involved": human_drug_involved or None,
        "toxin_exposure": toxin_exposure or None,
        "scenarios": _find_scenarios(text, symptoms),
    }
    facts.update({k: v for k, v in (req.extra or {}).items() if k not in facts or facts[k] is None})
    return facts
