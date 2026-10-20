"""从岗位标题等文本中提取校招字段。规则保守：拿不准就返回 None（CLAUDE.md：不要猜）。"""

import re
from functools import cache
from pathlib import Path

import yaml

_GRAD = re.compile(
    r"(?<![\dA-Za-z])(?:20)?(2[4-9]|3[0-2])\s*年?\s*(?:届|(?:秋季|春季)?(?:校招|校园招聘|秋招|春招|暑期实习|实习))"
)
# 宽松：校招/实习标题里独立出现的四位年份即届别（排除"2027年以上经验"之类）
_GRAD_LOOSE = re.compile(r"(?<![\dA-Za-z])20(2[4-9]|3[0-2])(?!\d)(?!\s*年(?:以上|及以上|经验|工作))")
# 标题开头的【2027】/[27] 这类只写年份的括号
_GRAD_BRACKET = re.compile(r"^\s*[【\[](?:20)?(2[4-9]|3[0-2])[】\]]")
# 顺序即优先级：更具体的批次在前
_BATCHES = (
    ("提前批", ("提前批",)),
    ("补录", ("补录", "补招")),
    ("正式批", ("正式批",)),
    ("春招", ("春招", "春季校园招聘", "春季招聘")),
    ("秋招", ("秋招", "秋季校园招聘", "秋季招聘")),
)


def grad_year_from_text(text: str | None, *, loose: bool = False) -> int | None:
    """loose=True 只应用于校招/实习岗位的标题。"""
    if not text:
        return None
    m = _GRAD.search(text) or _GRAD_BRACKET.search(text) or (_GRAD_LOOSE.search(text) if loose else None)
    return 2000 + int(m.group(1)) if m else None


def batch_from_text(text: str | None) -> str | None:
    if not text:
        return None
    for batch, words in _BATCHES:
        if any(w in text for w in words):
            return batch
    return None


TAXONOMY = Path(__file__).resolve().parents[2] / "taxonomy" / "categories.yaml"


@cache
def _rules() -> list[tuple[str, str, re.Pattern]]:
    if not TAXONOMY.exists():  # 以库的形式安装时没有规则表；归类只在采集端进行
        return []
    doc = yaml.safe_load(TAXONOMY.read_text(encoding="utf-8"))
    return [(r["category"], r["subcategory"], re.compile("|".join(r["any"]), re.I)) for r in doc["rules"]]


def categorize(title: str | None) -> tuple[str | None, str | None]:
    """按 taxonomy/categories.yaml 归类岗位标题；没有命中返回 (None, None)。"""
    if title:
        for category, subcategory, pattern in _rules():
            if pattern.search(title):
                return category, subcategory
    return None, None


_CITY_SPLIT = re.compile(r"[,，、;；/|]")
_CITY_LEVELS = re.compile(r"[-·—]")


def cities_from_text(text: str | None) -> list[str]:
    """"江苏省-连云港市,北京市-海淀区" -> ["连云港", "北京"]：有"市"一级取市，否则取最末一级；
    去掉"市"后缀，去重保序。"""
    if not text:
        return []
    out: list[str] = []
    for part in _CITY_SPLIT.split(text):
        levels = [x.strip() for x in _CITY_LEVELS.split(part.strip()) if x.strip()]
        if not levels:
            continue
        name = next((x for x in levels if x.endswith("市") and len(x) > 2), levels[-1])
        if len(name) > 2 and name.endswith("市"):
            name = name[:-1]
        if name and name not in out:
            out.append(name)
    return out


# 标题中被分隔符明确隔开的城市名才算（"验证工程师-深圳-2027"、"临床医师（武汉）"）；不做模糊匹配
KNOWN_CITIES = frozenset("""
北京 上海 天津 重庆 深圳 广州 杭州 南京 苏州 成都 武汉 西安 合肥 长沙 郑州 济南 青岛 厦门 福州 宁波
无锡 常州 南通 嘉兴 绍兴 温州 金华 台州 湖州 舟山 东莞 佛山 珠海 中山 惠州 汕头 江门 肇庆 昆明 贵阳
南宁 南昌 太原 石家庄 沈阳 大连 长春 哈尔滨 呼和浩特 兰州 西宁 银川 乌鲁木齐 拉萨 海口 三亚 烟台
潍坊 淄博 威海 临沂 徐州 扬州 镇江 盐城 泰州 连云港 芜湖 蚌埠 马鞍山 洛阳 唐山 保定 廊坊 绵阳 宜宾
柳州 桂林 赣州 九江 襄阳 宜昌 株洲 湘潭 岳阳 泉州 漳州 香港 澳门
""".split())
_TITLE_DELIMS = re.compile(r"[-－—_（）()【】\[\]/／,，、\s·:：]|base", re.I)
_PROVINCE_PREFIX = re.compile(r"^(?:北京|上海|天津|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|"
                              r"广东|海南|四川|贵州|云南|陕西|甘肃|青海|内蒙古|广西|西藏|宁夏|新疆)(?:省|市|自治区)?")


def cities_from_title(title: str | None) -> list[str]:
    if not title:
        return []
    out: list[str] = []
    for tok in _TITLE_DELIMS.split(title):
        tok = tok.strip()
        if tok.endswith("市") and len(tok) > 2:
            tok = tok[:-1]
        if tok not in KNOWN_CITIES:
            stripped = _PROVINCE_PREFIX.sub("", tok)
            tok = stripped[:-1] if stripped.endswith("市") and len(stripped) > 2 else stripped
        if tok in KNOWN_CITIES and tok not in out:
            out.append(tok)
    return out


_LOCATION_PART = re.compile(r".+(?:省|市|区|县|州|盟|自治区|特别行政区)$")


def looks_like_location(text: str | None) -> bool:
    """单元格内容是否为地名（每一段都以省/市/区/县等结尾，或为已知城市/全国/海外）。"""
    if not text or not text.strip():
        return False
    for part in _CITY_SPLIT.split(text):
        for level in _CITY_LEVELS.split(part.strip()):
            level = level.strip()
            if level and not (level in KNOWN_CITIES or level in ("全国", "海外", "不限")
                              or _LOCATION_PART.match(level)):
                return False
    return True


DEGREES = ("大专", "本科", "硕士", "博士")  # 由低到高


def degree_min_from_text(text: str | None) -> str | None:
    """学历字段（如"硕士、博士""本科及以上"）中出现的最低学历；没有明写学历时返回 None。"""
    if not text:
        return None
    return next((d for d in DEGREES if d in text), None)
