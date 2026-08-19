"""VetLink AI — 症狀結構化器 (提案 §7.1).

將飼主自然語言轉為結構化欄位。提案允許此模組「部分」由 LLM 協助，但**必須**通過
Schema 驗證。為了讓閘門決策完全可離線重現，本實作採確定性詞典比對，不呼叫 LLM。
若日後接入 LLM 抽取，輸出仍須經此處的 Schema 驗證後才進入閘門。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from ..models import ConsultRequest, Intent, Mentation, Species

# --------------------------------------------------------------------------
# 詞典 — 症狀正規化
# --------------------------------------------------------------------------
SYMPTOM_LEXICON: Dict[str, List[str]] = {
    # 泌尿
    "反覆進出砂盆": ["一直進砂盆", "反覆進出砂盆", "頻繁進砂盆", "進出貓砂盆", "一直跑廁所", "反覆去砂盆", "一直去貓砂盆"],
    "排尿困難": ["排尿困難", "尿不太出來", "用力排尿", "解尿困難", "尿很久", "蹲很久尿不出"],
    "尿不出來": ["尿不出來", "尿不出", "完全沒尿", "無法排尿", "解不出尿", "沒有尿"],
    "頻尿": ["頻尿", "一直尿", "尿很多次", "排尿次數增加"],
    "血尿": ["血尿", "尿有血", "尿是紅的", "尿帶血"],
    "亂尿": ["亂尿", "在外面尿", "隨地小便"],
    # 呼吸
    "呼吸困難": ["呼吸困難", "呼吸急促", "喘得很厲害", "呼吸很喘", "呼吸不順"],
    "開口呼吸": ["開口呼吸", "張口呼吸", "用嘴巴呼吸", "張嘴喘"],
    "呼吸費力": ["呼吸費力", "腹式呼吸", "肚子用力呼吸", "呼吸很用力"],
    "喘不過氣": ["喘不過氣", "快喘不過來"],
    "舌頭發紫": ["舌頭發紫", "舌頭變紫", "舌頭發黑"],
    "牙齦發白": ["牙齦發白", "牙齦蒼白", "牙齦很白"],
    "黏膜發紺": ["黏膜發紺", "發紺"],
    "咳嗽": ["咳嗽", "一直咳", "在咳"],
    "打噴嚏": ["打噴嚏", "噴嚏"],
    "鼻涕": ["鼻涕", "流鼻水"],
    "噎到": ["噎到", "嗆到東西", "卡到東西"],
    "異物卡喉": ["異物卡喉", "喉嚨卡東西", "吞到異物"],
    "中暑": ["中暑", "熱衰竭", "曬太久喘"],
    # 腸胃
    "嘔吐": ["嘔吐", "吐了", "在吐", "吐出來"],
    "持續嘔吐": ["持續嘔吐", "一直吐", "吐個不停", "狂吐"],
    "喝水就吐": ["喝水就吐", "喝水也吐", "連水都吐"],
    "腹瀉": ["腹瀉", "拉肚子", "水便", "軟便拉稀"],
    "軟便": ["軟便", "便便很軟"],
    "血便": ["血便", "便便有血", "大便帶血"],
    "黑便": ["黑便", "柏油便", "大便黑色", "黑色柏油", "大便是黑的", "便便黑黑的"],
    "腹部脹大": ["腹部脹大", "肚子脹", "肚子鼓起", "腹部膨脹"],
    "乾嘔": ["乾嘔", "想吐吐不出來", "作嘔沒東西"],
    "食慾下降": ["食慾下降", "不吃東西", "沒食慾", "吃很少", "不太吃"],
    # 中毒
    "誤食巧克力": ["吃到巧克力", "誤食巧克力", "偷吃巧克力"],
    "誤食洋蔥": ["吃到洋蔥", "誤食洋蔥"],
    "誤食葡萄": ["吃到葡萄", "誤食葡萄", "吃了葡萄乾"],
    "誤食百合": ["咬了百合", "誤食百合", "啃百合"],
    "吃到老鼠藥": ["吃到老鼠藥", "誤食老鼠藥", "滅鼠藥"],
    "誤食殺蟲劑": ["誤食殺蟲劑", "舔到殺蟲劑", "吃到蟑螂藥"],
    "誤食木糖醇": ["木糖醇", "無糖口香糖"],
    "中毒": ["中毒", "疑似中毒"],
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
    "抽搐": ["抽搐", "抽筋", "痙攣"],
    "癲癇": ["癲癇", "發作"],
    "口吐白沫": ["口吐白沫", "吐白沫"],
    "意識喪失": ["意識喪失", "昏過去"],
    "倒下": ["倒下", "倒在地上", "癱著"],
    "叫不醒": ["叫不醒", "沒有反應"],
    "意識不清": ["意識不清", "神智不清"],
    "站不起來": ["站不起來", "爬不起來", "無法站立"],
    "虛弱": ["虛弱", "很沒力", "軟綿綿"],
    "車禍": ["車禍", "被車撞", "被機車撞"],
    "從高處掉下來": ["從高處掉下來", "墜樓", "從陽台掉"],
    "大量出血": ["大量出血", "血流不止"],
    "骨折": ["骨折", "腳斷了"],
    "難產": ["難產", "生不出來"],
    "眼球突出": ["眼球突出", "眼睛凸出來"],
    "眼睛劇痛": ["眼睛劇痛", "眼睛痛到睜不開"],
    "眼睛突然看不見": ["突然看不見", "眼睛看不到"],
}

SPECIES_LEXICON: Dict[Species, List[str]] = {
    Species.CAT: ["貓", "貓咪", "喵", "貓貓", "cat", "kitten", "幼貓"],
    Species.DOG: ["狗", "狗狗", "犬", "汪", "dog", "puppy", "幼犬"],
}

MENTATION_LEXICON: Dict[Mentation, List[str]] = {
    Mentation.COLLAPSED: ["倒下", "叫不醒", "意識不清", "站不起來", "癱軟", "沒有反應", "昏迷"],
    Mentation.LETHARGIC: [
        "精神差", "沒精神", "懶洋洋", "很累", "不太動", "精神不好", "沉鬱",
        # 「虛弱」語意等同精神沉鬱，須納入 mentation 判定，否則
        # VG-RED-204（黑便合併虛弱）等紅旗規則會因缺值而無法成立。
        "很沒力", "沒力氣", "虛弱", "軟綿綿", "無力",
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
]

TOXIN_TOKENS = [
    "巧克力", "洋蔥", "葡萄", "葡萄乾", "百合", "老鼠藥", "滅鼠藥", "殺蟲劑",
    "蟑螂藥", "木糖醇", "中毒", "防凍劑",
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


def _find_symptoms(text: str) -> List[str]:
    found: List[str] = []
    for canonical, variants in SYMPTOM_LEXICON.items():
        for v in variants:
            if v in text:
                if canonical not in found:
                    found.append(canonical)
                break
    return found


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


def structure_case(req: ConsultRequest) -> Dict[str, Any]:
    """把 ConsultRequest 轉成規則引擎使用的 facts dict。

    明確給定的欄位一律優先於文字抽取結果。
    """
    text = req.text or ""

    symptoms = _find_symptoms(text)
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

    human_drug_involved = any(t in text for t in HUMAN_DRUG_TOKENS)
    toxin_exposure = any(t in text for t in TOXIN_TOKENS)

    # can_urinate：明確欄位優先；否則由否定語意推導
    can_urinate = req.can_urinate
    if can_urinate is None:
        if any(s in symptoms for s in ("尿不出來",)):
            can_urinate = False
        elif "有尿出來" in text or "還是有尿" in text or "尿得出來" in text:
            can_urinate = True

    facts: Dict[str, Any] = {
        "raw_text": text,
        "symptoms": symptoms,
        "species": species.value if isinstance(species, Species) else species,
        "role": req.role.value,
        "intent": intent.value,
        "body_weight_kg": body_weight_kg,
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
