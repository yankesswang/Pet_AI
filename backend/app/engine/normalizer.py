"""VetLink AI — 安全正規化器 (Safety Normalizer)。

放在 `structurer` 之前的一層。它解決留出集量到的兩個獨立缺陷：

  過度警示 —— 純子字串比對會把「牠**沒有**尿不出來」「**上個月**尿不出來已出院」
              「貓咪**如果**尿不出來會有什麼徵兆」「**我朋友的**狗誤食巧克力」
              全部當成當下急症。

  危險漏判 —— 詞典只收錄書面語，因此口語（「蹲很久起來後沒看到尿」）、
              簡體（「什么都排不出来」）與英文（"straining in the litter box"）
              描述的真急症完全比對不到，症狀清單為空 → 一路落到綠色。

因此本模組做兩件事：

  1. **表面正規化**：簡體轉繁體、全形轉半形、英文小寫化、常見錯字與口語
     單位統一，讓下游詞典能比對到同一個字面。
  2. **斷言標記 (assertion status)**：把描述切成子句，判定每個症狀命中屬於
     現在肯定／已否定／過去病史／假設詢問／第三方事件。**只有「現在＋肯定」
     才允許進入紅旗規則。**

設計原則 — 本模組**不呼叫 LLM**，全部確定性、可離線重現，與閘門其餘部分一致。
LLM 若日後接入，只負責抽取結構化欄位，仍須經此處與 Schema 驗證。
"""
from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass, field
from enum import Enum
from typing import Dict, List, Optional, Tuple


class Assertion(str, Enum):
    """症狀命中的斷言狀態。只有 PRESENT 可支持紅旗。"""

    PRESENT = "present"          # 現在正在發生（肯定）
    NEGATED = "negated"          # 明確否定：沒有／不會／未曾
    HISTORICAL = "historical"    # 過去病史／已解除的事件
    HYPOTHETICAL = "hypothetical"  # 假設或衛教詢問：如果／怎麼判斷／前兆
    THIRD_PARTY = "third_party"  # 別人的動物，不是本次個案


# --------------------------------------------------------------------------
# 1. 表面正規化
# --------------------------------------------------------------------------

# 簡體 → 繁體。只收錄本領域確實會出現的字，避免引入完整轉換表的相依。
_SIMPLIFIED_TO_TRADITIONAL = str.maketrans({
    "猫": "貓", "狗": "狗", "呕": "嘔", "吐": "吐", "泻": "瀉", "拉": "拉",
    "尿": "尿", "血": "血", "便": "便", "东": "東", "西": "西", "么": "麼",
    "什": "什", "们": "們", "个": "個", "现": "現", "样": "樣", "还": "還",
    "没": "沒", "药": "藥", "医": "醫", "护": "護", "陈": "陳", "间": "間",
    "时": "時", "开": "開", "关": "關", "两": "兩", "会": "會", "体": "體",
    "过": "過", "动": "動", "静": "靜", "养": "養", "养": "養", "点": "點",
    "热": "熱", "冷": "冷", "紧": "緊", "张": "張", "呼": "呼", "吸": "吸",
    "难": "難", "严": "嚴", "重": "重", "轻": "輕", "变": "變", "红": "紅",
    "绿": "綠", "蓝": "藍", "紫": "紫", "黑": "黑", "白": "白", "脸": "臉",
    "肿": "腫", "痒": "癢", "抓": "抓", "伤": "傷", "断": "斷", "骨": "骨",
    "头": "頭", "脑": "腦", "脚": "腳", "腿": "腿", "肚": "肚", "颤": "顫",
    "抖": "抖", "软": "軟", "无": "無", "力": "力", "气": "氣", "喘": "喘",
    "咳": "咳", "嗽": "嗽", "鼻": "鼻", "涕": "涕", "食": "食", "欲": "慾",
    "餐": "餐", "喂": "餵", "给": "給", "吃": "吃", "喝": "喝", "水": "水",
    "盆": "盆", "砂": "砂", "厕": "廁", "所": "所", "出": "出", "来": "來",
    "去": "去", "里": "裡", "内": "內", "外": "外", "带": "帶", "发": "發",
    "现": "現", "钟": "鐘", "刚": "剛", "总": "總", "结": "結", "长": "長",
    "术": "術", "疗": "療", "诊": "診", "检": "檢", "查": "查", "验": "驗",
})

# 常見錯字／口語 → 標準寫法。順序無關（不重疊）。
_TYPO_MAP: List[Tuple[str, str]] = [
    ("拉肚子", "腹瀉"),
    ("落賽", "腹瀉"),
    ("烙賽", "腹瀉"),
    ("嘔土", "嘔吐"),
    ("嘔谷", "乾嘔"),
    ("噁心想土", "乾嘔"),
    ("貓沙盆", "貓砂盆"),
    ("貓砂盤", "貓砂盆"),
    ("喵砂盆", "貓砂盆"),
    ("狗勾", "狗"),
    ("汪星人", "狗"),
    ("喵星人", "貓"),
    ("毛小孩", "寵物"),
    ("咳咳", "咳嗽"),
    ("痾", "排便"),
    ("嗯嗯", "排便"),
]

# 英文 → 中文臨床詞。留出集含英文案例，且飼主實務上會夾雜英文。
_ENGLISH_MAP: List[Tuple[str, str]] = [
    ("straining in the litter box", "反覆進出砂盆 排尿困難"),
    ("straining to urinate", "排尿困難"),
    ("straining", "用力排尿"),
    ("litter box", "貓砂盆"),
    ("cannot urinate", "尿不出來"),
    ("can't urinate", "尿不出來"),
    ("no urine", "尿不出來"),
    ("blood in urine", "血尿"),
    ("open mouth breathing", "開口呼吸"),
    ("mouth breathing", "開口呼吸"),
    ("difficulty breathing", "呼吸困難"),
    ("labored breathing", "呼吸費力"),
    ("panting", "喘"),
    ("collapsed", "倒下"),
    ("seizure", "抽搐"),
    ("seizures", "抽搐"),
    ("convulsion", "抽搐"),
    ("vomiting", "嘔吐"),
    ("throwing up", "嘔吐"),
    ("diarrhea", "腹瀉"),
    ("diarrhoea", "腹瀉"),
    ("lethargic", "精神差"),
    ("lethargy", "精神差"),
    ("bloated", "腹部脹大"),
    ("bloat", "腹部脹大"),
    ("pale gums", "牙齦發白"),
    ("blue tongue", "舌頭發紫"),
    ("heat stroke", "中暑"),
    ("heatstroke", "中暑"),
    ("choking", "噎到"),
    ("male cat", "公貓"),
    ("my cat", "貓"),
    ("my dog", "狗"),
    ("cat", "貓"),
    ("dog", "狗"),
]

# 口語單位 → 可被 structurer 正則抓到的寫法
_UNIT_MAP: List[Tuple[str, str]] = [
    ("半天", "12 小時"),
    ("一整天", "24 小時"),
    ("整晚", "8 小時"),
    ("一早", "6 小時"),
    ("公擔", "公斤"),
    ("公克", "公克"),
]


def normalize_surface(text: str) -> str:
    """把不同書寫變體收斂到同一個字面，供詞典比對。

    只做**可逆語意保留**的替換：不刪除否定詞、不改動時態線索，
    因為斷言判定還要用到它們。
    """
    if not text:
        return ""
    # 全形 → 半形、相容字元正規化
    out = unicodedata.normalize("NFKC", text)
    # 簡體 → 繁體
    out = out.translate(_SIMPLIFIED_TO_TRADITIONAL)
    # 英文一律小寫後替換（中文不受影響）
    lowered = out.lower()
    for src, dst in _ENGLISH_MAP:
        if src in lowered:
            # 在小寫版定位、於原字串同位置替換，確保索引一致
            lowered = lowered.replace(src, dst)
    out = lowered
    for src, dst in _TYPO_MAP:
        out = out.replace(src, dst)
    for src, dst in _UNIT_MAP:
        out = out.replace(src, dst)
    # 壓縮空白
    out = re.sub(r"[ \t]+", " ", out).strip()
    return out


# --------------------------------------------------------------------------
# 2. 斷言標記
# --------------------------------------------------------------------------

# 子句切分。中文標點 + 常見轉折連接詞都算邊界，因為
# 「牠沒有尿不出來，只是水喝得少」的兩半斷言狀態不同。
_CLAUSE_SPLIT_RE = re.compile(r"[，,。；;！!？?、\n]|但是|但|不過|只是|然後|而且|另外")

# 否定：出現在症狀**之前**才算否定該症狀。
_NEGATION_CUES = (
    "沒有", "没有", "沒", "不會", "不曾", "未曾", "從來沒", "從沒", "都沒",
    "並未", "並沒", "不是", "沒在", "不太會", "沒發生", "排除",
    "not ", "no ", "without ",
)

# 單字「無」曾被列為否定線索，但它會把「**無**糖口香糖」（木糖醇中毒，
# 真急症）判成否定而靜默漏判。單字否定詞風險過高，一律只採多字詞形；
# 「無」只在這些明確的否定搭配中才算否定。
_NEGATION_CUES_STRICT = (
    "無明顯", "無異常", "無症狀", "無不適", "無大礙", "無此問題",
)

# 過去病史／已解除事件
_HISTORICAL_CUES = (
    "上個月", "上禮拜", "上週", "上星期", "去年", "前年", "之前", "以前",
    "當時", "那時", "曾經", "有過", "過去", "小時候", "幼年",
    "出院", "已經康復", "康復後", "痊癒", "治療好了", "已經好了", "都正常了",
    "穩定了", "現在都很穩定", "後來就好了", "已解除", "last month", "last year",
    "previously", "recovered",
)

# 假設／衛教詢問
_HYPOTHETICAL_CUES = (
    "如果", "假如", "萬一", "要是", "怎麼判斷", "怎麼知道", "什麼徵兆",
    "哪些徵兆", "前兆", "徵兆有哪些", "該注意什麼", "要注意什麼",
    "怎麼預防", "如何預防", "predict", "想先知道", "想知道", "想問",
    "想確認", "請問一般", "一般來說", "平常要", "日常", "衛教",
    "會有什麼", "有哪些", "該怎麼辦時", "什麼時候該", "才知道",
    "what if", "how do i know", "signs of", "prevent",
)

# 第三方：不是本次個案的動物
_THIRD_PARTY_CUES = (
    "我朋友", "朋友的", "同事的", "鄰居", "我姐的", "我哥的", "我妹的",
    "別人的", "他們家", "網路上看到", "新聞說", "有人說", "我看過",
    "my friend", "friend's", "neighbor",
)


def _clause_assertion(clause: str) -> Assertion:
    """判定單一子句的斷言狀態。優先序：第三方 > 假設 > 過去 > 否定 > 現在。

    優先序理由：第三方與假設是「這根本不是本案」，比時態更根本；
    否定放最後，因為「上個月沒有尿不出來」仍屬過去語境。
    """
    if any(c in clause for c in _THIRD_PARTY_CUES):
        return Assertion.THIRD_PARTY
    if any(c in clause for c in _HYPOTHETICAL_CUES):
        return Assertion.HYPOTHETICAL
    if any(c in clause for c in _HISTORICAL_CUES):
        return Assertion.HISTORICAL
    if any(c in clause for c in _NEGATION_CUES) or any(
        c in clause for c in _NEGATION_CUES_STRICT
    ):
        return Assertion.NEGATED
    return Assertion.PRESENT


# 明確把語境拉回「現在」的線索。用於
# 「上個月住院導尿，**現在**又開始蹲砂盆」這種先過去後現在的描述。
_PRESENT_OVERRIDE_CUES = (
    "現在", "剛剛", "今天", "目前", "這幾天", "從昨天", "從半夜", "從早上",
    "正在", "一直", "此刻", "今早", "今晚", "昨天晚上", "剛才",
)


# 會延續到後續子句的語境型別。否定不延續 ——
# 「牠沒有尿不出來，只是水喝得少」的後半是獨立的當下陳述。
_SCOPE_CARRYING = (
    Assertion.HYPOTHETICAL,
    Assertion.THIRD_PARTY,
    Assertion.HISTORICAL,
)


@dataclass
class ClauseSpan:
    """一個子句與它的斷言狀態。"""

    text: str
    start: int
    assertion: Assertion


@dataclass
class NormalizedText:
    """正規化結果，供 structurer 與稽核軌跡使用。"""

    raw: str
    normalized: str
    clauses: List[ClauseSpan] = field(default_factory=list)
    # 供護照顯示：本次做了哪些正規化
    notes: List[str] = field(default_factory=list)

    def assertion_at(self, index: int) -> Assertion:
        """查詢 normalized 字串某位置落在哪個子句、該子句的斷言狀態。"""
        current = Assertion.PRESENT
        for c in self.clauses:
            if c.start <= index < c.start + len(c.text):
                return c.assertion
            if c.start <= index:
                current = c.assertion
        return current


def segment(normalized: str) -> List[ClauseSpan]:
    """把正規化後的文字切成帶斷言狀態的子句。"""
    spans: List[ClauseSpan] = []
    pos = 0
    carried: Optional[Assertion] = None
    for piece in _CLAUSE_SPLIT_RE.split(normalized):
        if piece is None:
            continue
        idx = normalized.find(piece, pos) if piece else pos
        if idx < 0:
            idx = pos
        stripped = piece.strip()
        if stripped:
            assertion = _clause_assertion(stripped)
            # 過去語境中若出現明確的「現在」線索，拉回現在。
            if assertion is Assertion.HISTORICAL and any(
                c in stripped for c in _PRESENT_OVERRIDE_CUES
            ):
                assertion = Assertion.PRESENT
            # 語境延續：假設／第三方／過去的語境會延伸到後續子句，
            # 直到出現明確的「現在」線索為止。這是為了讓
            # 「想確認哪些食物有毒，像是洋蔥、葡萄這些嗎」的列舉子句
            # 不會脫離提問語境而被當成當下的毒物暴露。
            if (
                assertion is Assertion.PRESENT
                and carried is not None
                and not any(c in stripped for c in _PRESENT_OVERRIDE_CUES)
            ):
                assertion = carried
            if assertion in _SCOPE_CARRYING:
                carried = assertion
            elif any(c in stripped for c in _PRESENT_OVERRIDE_CUES):
                carried = None
            spans.append(ClauseSpan(text=piece, start=idx, assertion=assertion))
        pos = idx + len(piece)
    if not spans:
        spans.append(ClauseSpan(text=normalized, start=0, assertion=Assertion.PRESENT))
    return spans


def normalize(text: str) -> NormalizedText:
    """完整正規化：表面收斂 + 子句斷言標記。"""
    raw = text or ""
    norm = normalize_surface(raw)
    clauses = segment(norm)
    notes: List[str] = []
    if norm != raw:
        notes.append("已套用表面正規化（簡繁／全半形／英文／口語）。")
    non_present = {c.assertion.value for c in clauses if c.assertion is not Assertion.PRESENT}
    if non_present:
        notes.append("偵測到非當下語境子句: " + ", ".join(sorted(non_present)))
    return NormalizedText(raw=raw, normalized=norm, clauses=clauses, notes=notes)
