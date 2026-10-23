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


# JD 原文里的届别：只认"20XX届"这种明确写法
_GRAD_JD = re.compile(r"20(2[4-9]|3[0-2])\s*届")


def grad_year_from_jd(description: str | None, requirements: str | None) -> int | None:
    """标题没写届别时的兜底：JD 原文里明写的「20XX届」。

    同一份 JD 出现多个不同届别（"2026届、2027届均可投递"）时无法判断是哪一届，返回 None。
    只认"届"，不认"2027年毕业"——后者容易和入职年份混淆。
    """
    years = set(_GRAD_JD.findall(" ".join(x or "" for x in (description, requirements))))
    return 2000 + int(years.pop()) if len(years) == 1 else None


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
# `&`/`＆`/`+`/`＋`/`｜`/`丨`/`;`/`；` 也都是城市分隔符：北森标题形如
# 「…（直营电商/济南&青岛）(J14673)」「…（软件交付部/苏州｜郑州）(J14673)」。
# 不加这些字符的话整段「济南&青岛」不在 KNOWN_CITIES 里，一个城市都提取不到
# （2026-10-22 实测：北森缺失城市的标题提取率为 0%）。
_TITLE_DELIMS = re.compile(r"[-－—_（）()【】\[\]/／|｜丨¦,，、;；&＆+＋\s·・:：]|base", re.I)
_PROVINCE_PREFIX = re.compile(r"^(?:北京|上海|天津|重庆|河北|山西|辽宁|吉林|黑龙江|江苏|浙江|安徽|福建|江西|山东|河南|湖北|湖南|"
                              r"广东|海南|四川|贵州|云南|陕西|甘肃|青海|内蒙古|广西|西藏|宁夏|新疆)(?:省|市|自治区)?")

# 标题里的城市常常是"城市 + 机构后缀"或"英文字母 + 城市"（北森/事务所类门户很常见）：
# 「北京分所」「武汉总所」「上海自贸区分所」「深圳基地负责人」「CBG北京」。
# 这些都是明写，不是推测；后缀必须是机构/地点类词，避免「北京烤鸭」这类误判。
_CITY_SUFFIXES = ("分所", "总所", "分公司", "子公司", "分厂", "工厂", "基地", "园区", "办公区", "战区",
                  "大区", "区域", "研究所", "研究院", "研发中心", "总部", "办事处", "代表处", "分行", "支行", "校区", "公司")
_CITY_AFTER_LATIN = re.compile(r"^[A-Za-z0-9]+(?P<city>" + "|".join(sorted(KNOWN_CITIES, key=len, reverse=True)) + r")$")


def _city_of_token(tok: str) -> str | None:
    """一个标题片段里的城市：整段等于城市、城市+机构描述、英文字母+城市。

    支持的真实写法（2026-10-22 从北森标题里统计）：
    「北京分所」「上海自贸区分所」「深圳基地负责人」「上海2」「重庆公司」「中国香港」「CBG北京」。
    城市后面必须跟机构/地点词或编号，否则「北京烤鸭」「上海大众汽车」这类不会命中。
    """
    tok = re.sub(r"\d{1,2}$", "", tok)  # 「上海2」「北京3」：同城多岗位的编号
    if tok in KNOWN_CITIES:
        return tok
    if tok.startswith("中国") and tok[2:] in KNOWN_CITIES:  # 中国香港
        return tok[2:]
    for city in sorted(KNOWN_CITIES, key=len, reverse=True):
        if not tok.startswith(city):
            continue
        rest = tok[len(city):]
        if rest and len(rest) <= 10 and (rest in _CITY_SUFFIXES
                                         or any(rest.startswith(s) or rest.endswith(s) for s in _CITY_SUFFIXES)):
            return city
    m = _CITY_AFTER_LATIN.match(tok)
    return m.group("city") if m else None


def cities_from_title(title: str | None) -> list[str]:
    if not title:
        return []
    out: list[str] = []
    for tok in _TITLE_DELIMS.split(title):
        tok = tok.strip()
        if tok.endswith("市") and len(tok) > 2:
            tok = tok[:-1]
        city = _city_of_token(tok)
        if city is None:
            stripped = _PROVINCE_PREFIX.sub("", tok)
            tok = stripped[:-1] if stripped.endswith("市") and len(stripped) > 2 else stripped
            city = _city_of_token(tok)
        if city and city not in out:
            out.append(city)
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


# 外资 ATS（Workday / SmartRecruiters）的城市是英文；只映射确定的中文城市名
CITY_EN = {
    "aomen": "澳门",
    "baoding": "保定",
    "beijing": "北京",
    "bengbu": "蚌埠",
    "changchun": "长春",
    "changsha": "长沙",
    "changzhou": "常州",
    "chengdu": "成都",
    "chongqing": "重庆",
    "dalian": "大连",
    "dongguan": "东莞",
    "foshan": "佛山",
    "fuzhou": "福州",
    "ganzhou": "赣州",
    "guangzhou": "广州",
    "guilin": "桂林",
    "guiyang": "贵阳",
    "haerbin": "哈尔滨",
    "haikou": "海口",
    "hangzhou": "杭州",
    "harbin": "哈尔滨",
    "hefei": "合肥",
    "hohhot": "呼和浩特",
    "hong kong": "香港",
    "hongkong": "香港",
    "hsinchu": "新竹",
    "huhehaote": "呼和浩特",
    "huizhou": "惠州",
    "huzhou": "湖州",
    "jiangmen": "江门",
    "jiaxing": "嘉兴",
    "jinan": "济南",
    "jinhua": "金华",
    "jiujiang": "九江",
    "kunming": "昆明",
    "kunshan": "昆山",
    "langfang": "廊坊",
    "lanzhou": "兰州",
    "lasa": "拉萨",
    "lhasa": "拉萨",
    "lianyungang": "连云港",
    "linyi": "临沂",
    "liuzhou": "柳州",
    "luoyang": "洛阳",
    "maanshan": "马鞍山",
    "macao": "澳门",
    "macau": "澳门",
    "mianyang": "绵阳",
    "nanchang": "南昌",
    "nanjing": "南京",
    "nanning": "南宁",
    "nantong": "南通",
    "ningbo": "宁波",
    "qingdao": "青岛",
    "qinhuangdao": "秦皇岛",
    "quanzhou": "泉州",
    "sanya": "三亚",
    "shanghai": "上海",
    "shantou": "汕头",
    "shaoxing": "绍兴",
    "shenyang": "沈阳",
    "shenzhen": "深圳",
    "shijiazhuang": "石家庄",
    "suzhou": "苏州",
    "taipei": "台北",
    "taiyuan": "太原",
    "taizhou": "泰州",
    "tangshan": "唐山",
    "tianjin": "天津",
    "urumqi": "乌鲁木齐",
    "weifang": "潍坊",
    "weihai": "威海",
    "wenzhou": "温州",
    "wuhan": "武汉",
    "wuhu": "芜湖",
    "wulumuqi": "乌鲁木齐",
    "wuxi": "无锡",
    "xi'an": "西安",
    "xiamen": "厦门",
    "xian": "西安",
    "xianggang": "香港",
    "xiangtan": "湘潭",
    "xiangyang": "襄阳",
    "xining": "西宁",
    "xuzhou": "徐州",
    "yancheng": "盐城",
    "yangzhou": "扬州",
    "yantai": "烟台",
    "yibin": "宜宾",
    "yichang": "宜昌",
    "yinchuan": "银川",
    "yueyang": "岳阳",
    "zhangzhou": "漳州",
    "zhaoqing": "肇庆",
    "zhengzhou": "郑州",
    "zhenjiang": "镇江",
    "zhongshan": "中山",
    "zhoushan": "舟山",
    "zhuhai": "珠海",
    "zhuzhou": "株洲",
    "zibo": "淄博",
}


def city_from_english(name: str | None) -> str | None:
    return CITY_EN.get((name or "").strip().lower())
