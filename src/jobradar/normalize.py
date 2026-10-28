"""从岗位标题等文本中提取校招字段。规则保守：拿不准就返回 None（CLAUDE.md：不要猜）。"""

import re
from datetime import datetime, timedelta, timezone
from functools import cache
from pathlib import Path

import yaml

_CST = timezone(timedelta(hours=8))

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
# 门店类后缀：零售/餐饮/茶饮的岗位标题几乎都是「城市 + 门店名 + 店」。
# 2026-10-26 实测喜茶 748 条实习岗城市覆盖 0%，标题形如「实习生（上海新嘉中心店）」
# 「实习生烘焙师（杭州湖滨88Lab店）」——「店」是明写的工作地点，不是推测。
_CITY_STORE_SUFFIX = "店"
_CITY_AFTER_LATIN = re.compile(r"^[A-Za-z0-9]+(?P<city>" + "|".join(sorted(KNOWN_CITIES, key=len, reverse=True)) + r")$")
_TITLE_STORE = re.compile(
    r"^(?P<city>" + "|".join(sorted(KNOWN_CITIES, key=len, reverse=True)) + r")[^，,、；;]{0,14}店$")

# 「城市 + 岗位类词」是招聘标题里最常见的写法之一，但它**不是**「城市 + 机构」：
# 「27届校招北京-高中语文教师」「北京-销售管培生」「上海客服专员」。
# 这类标题里的城市是明确的办公地点，可是上面那套「后缀必须是机构词」的规则会漏掉，
# 因为「北京」后面跟的是「-」或者直接接了岗位名。
# 判据收紧到「城市是片段的**开头**，且片段里还包含明确的岗位类词」——
# 这样「北京烤鸭」不会命中（没有岗位词），「上海大众汽车」也不会。
_TITLE_PREFIX = re.compile(r"^(?:20\d{2}届?|\d{2}届|20\d{2}|校招|社招|春招|秋招|提前批|实习|暑期|寒假|"
                           r"日常|全职|兼职|应届|海外|\d{1,2}月)+")
_JOB_WORDS = ("教师", "讲师", "顾问", "工程师", "经理", "专员", "管培生", "培训生", "实习生", "研究员",
              "设计师", "分析师", "开发", "运营", "销售", "客服", "店长", "店员", "助理", "秘书",
              "会计", "审计", "出纳", "法务", "程序员", "架构师", "科学家", "主管",
              "总监", "leader", "Leader", "实习", "校招", "岗位", "岗", "医师", "药师", "护士",
              "技师", "技术员", "实验员", "编辑", "记者", "主播", "策划", "文案", "翻译", "律师",
              "文员", "操作工", "技工", "维修", "司机", "业务员", "客户经理", "代表", "专家")

# 反例闸门：命中这些词时，即使城市后面挂着岗位类词也**不采信**。
# 「上海大众汽车工程师」「北京大学合作项目专员」「深圳湾实验室研究员」——这里城市是专有名词的
# 一部分（上汽大众、北大、深圳湾实验室），不是办公地点。判错会把岗位挂到错误城市的日历条目上，
# 比留空更糟：用户按城市筛会看到自己投不了的岗。
_CITY_FALSE_FRIENDS = ("大学", "学院", "中学", "小学", "实验室", "汽车", "湾", "交易所", "电视台",
                       "航空", "地铁", "银行", "医院", "研究院", "本部", "先驱")


def _city_prefix_with_jobword(tok: str) -> str | None:
    """「北京-高中语文教师」这类：城市打头 + 片段里有岗位类词 → 判为城市。

    城市前面常挂着届次/批次前缀（「27届校招北京」「2027暑期实习上海」），所以不能只试
    `startswith(city)`，要先剥掉「届次/校招/实习」这类前缀——这一步不能省，实测不剥会导致
    3.3 万条北森校招标题里实打实写了城市的那些全被漏掉。
    另外「城市独占整个片段」也算：delims 已经把「-」「（）」切开，
    「27届校招北京-高中语文教师」切出来的就是裸的「北京」，片段里根本没有岗位词可看。

    三道闸门缺一不可：①前缀能剥/裸城市；②片段里有岗位类词；③没有专有名词反例。
    """
    orig = tok
    stripped = _TITLE_PREFIX.sub("", tok)
    if stripped != tok and stripped:
        tok = stripped
    for city in sorted(KNOWN_CITIES, key=len, reverse=True):
        if not tok.startswith(city):
            continue
        rest = tok[len(city):]
        # 裸城市片段（tok 原样就是城市，或剥完前缀正好是城市）
        if not rest and (tok in KNOWN_CITIES or orig in KNOWN_CITIES):
            return city
        if not rest:
            continue
        if any(bad in rest for bad in _CITY_FALSE_FRIENDS):
            continue
        if any(w in rest for w in _JOB_WORDS):
            return city
    return None


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
    if m:
        return m.group("city")
    return _city_prefix_with_jobword(tok)


def cities_from_title(title: str | None) -> list[str]:
    if not title:
        return []
    out: list[str] = []
    for raw_tok in _TITLE_DELIMS.split(title):
        tok = raw_tok.strip()
        if tok.endswith("市") and len(tok) > 2:
            tok = tok[:-1]
        city = _city_of_token(tok)
        if city is None:
            stripped = _PROVINCE_PREFIX.sub("", tok)
            # 注意这里**不能**把 tok 覆盖掉：覆盖之后下面的门店规则只看被剥了省份前缀的
            # 后半段（「上海新嘉中心店」→「新嘉中心店」），城市就丢了。
            tok = stripped[:-1] if stripped.endswith("市") and len(stripped) > 2 else stripped
            city = _city_of_token(tok)
            if city and city not in out:
                out.append(city)
                continue
            tok = raw_tok.strip()
        if city and city not in out:
            out.append(city)
            continue
        # 「城市 + 门店名 + 店」：城市必须在片段**开头**，且整段以「店」结尾、长度有限。
        # 「北京烤鸭店」这类也会命中——但它在招聘标题里出现时，说的就是北京的门店，可以接受。
        m = _TITLE_STORE.match(tok)
        if m and m.group("city") not in out:
            out.append(m.group("city"))
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


# JD 正文里的学历常常不是结构化字段，而是散在"任职要求"里。直接按关键字抓会把
# "团队由 30 位博士组成" 误判成博士岗，所以必须带上下文锚点：
#   ① 学历/学位/教育背景/岗位要求/任职资格 之后 12 字内的学历词；
#   ② 学历词后面紧跟"研究生/学历/学位/及以上/以上/毕业"。
_JD_DEGREE_ANCHOR = re.compile(
    r"(?:学历|学位|教育(?:背景|经历)|任职(?:要求|资格)|岗位要求|招聘要求)[^\n。；]{0,12}?(博士|硕士|本科|大专)"
)
_JD_DEGREE_SUFFIX = re.compile(
    r"(?<![获取授])(博士|硕士|本科|大专)(?:研究生|学历|学位|及以上|以上|毕业)"
)


def normalize_degree(value: str | None) -> str | None:
    """把各平台五花八门的学历字段归一到四档（大专/本科/硕士/博士），认不出返回 None。

    2026-10-28 抽样实测（16,103 条）：适配器把平台原值直接塞进 degree_min，
    出现 `本科及以上`、`硕士研究生`、`专科及以上`、`中技（中专/技校/职高）`、`不限`
    ——同一个字段 26 种写法，按它做「本科及以上」筛选会同时漏掉和错放。
    低于大专的（高中/中专/初中/小学）不在四档里，按"无学历门槛"记 None。
    """
    if not value:
        return None
    s = value.strip()
    for d in DEGREES:  # 「博士研究生」先命中博士，不会被 硕士 抢走
        if d in s:
            return d
    if "专科" in s:
        return "大专"
    if "研究生" in s:
        return "硕士"
    return None


def degree_min_from_jd(text: str | None) -> str | None:
    """从 JD 正文推断最低学历要求；没有可信的上下文时返回 None（宁缺勿错）。

    degree_min_from_text 只适合平台的结构化学历字段（本身就是学历值），
    正文必须用带锚点的规则，否则描述性文字（"博士团队""本科院校"）会污染统计。
    """
    if not text:
        return None
    found = _JD_DEGREE_ANCHOR.findall(text) or _JD_DEGREE_SUFFIX.findall(text)
    if not found:
        return None
    return min(found, key=DEGREES.index)


# 「长期开放」哨兵：平台用 2100 年之后（甚至 3000-01-01、9999-12-31）表示"没有截止日"。
# 当成真日期会让"找快截止的岗位"筛出一堆 3000 年，必须归一成 None。
_LONG_TERM_YEAR = 2100


def date_only(value, *, floor_year: int = 2000) -> str | None:
    """把各平台五花八门的日期表示归一成 'YYYY-MM-DD'；取不到可信日期就返回 None。

    覆盖 2026-10-26 实测的几种形态（都是公开列表接口原值，不是猜的）：
      - 大易 `'2026-11-17 23:59:59'`         → '2026-11-17'
      - 北森 `'0001-01-01T00:00:00'`          → None（未填）
      - 飞书/美团毫秒时间戳 `1786960999000`   → '2026-08-17'（按东八区）
      - ISO 串带时区 `'2026-10-26T13:15:00+08:00'`
    越界时间戳（99999999999999999 之类）不能让 `datetime.fromtimestamp` 抛 ValueError。
    """
    if value is None or value == "":
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)) or (isinstance(value, str) and value.isdigit()):
        try:
            n = float(value)
        except (TypeError, ValueError):
            return None
        # 10 位是秒，13 位是毫秒；再往外就是脏数据
        ms = n if n > 1e11 else n * 1000
        if ms <= 0 or ms > 2_208_988_800_000:  # 2040-01-01 之后一律不认
            return None
        try:
            return datetime.fromtimestamp(ms / 1000, _CST).date().isoformat()
        except (ValueError, OverflowError, OSError):
            return None
    if not isinstance(value, str):
        return None
    s = value.strip()
    # 腾讯列表接口给的是中文日期「2026年10月21日」，先归一成 ISO 再走下面的解析
    m = re.fullmatch(r"(\d{4})\s*年\s*(\d{1,2})\s*月\s*(\d{1,2})\s*日?", s)
    if m:
        y, mo, d = (int(x) for x in m.groups())
        if 2000 <= y < _LONG_TERM_YEAR and 1 <= mo <= 12 and 1 <= d <= 31:
            return f"{y:04d}-{mo:02d}-{d:02d}"
        return None
    head = s[:10]
    if len(head) != 10 or head[4] != "-" or head[7] != "-":
        return None
    try:
        y, m, d = (int(x) for x in head.split("-"))
    except ValueError:
        return None
    if not (floor_year <= y < _LONG_TERM_YEAR and 1 <= m <= 12 and 1 <= d <= 31):
        return None
    return head


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


# 地级市里常见、但 CITY_EN 还没收的几十个 —— 外企英文站点（Avature / Workday / Radancy）
# 把地点写成 `Chengdu` / `Xi'an` / `Hohhot`，缺映射就只能给英文，本地用户读起来别扭。
# 只收**确定对应**的地级市；同名异写（`Xian`/`Xi'an`、`Hohhot`/`Huhehaote`）两条都收。
CITY_EN_EXTRA = {
    "anqing": "安庆", "anshan": "鞍山", "anyang": "安阳", "baoji": "宝鸡", "baotou": "包头",
    "benxi": "本溪", "cangzhou": "沧州", "changde": "常德", "chaozhou": "潮州",
    "chenzhou": "郴州", "chifeng": "赤峰", "dalian": "大连", "dandong": "丹东",
    "daqing": "大庆", "datong": "大同", "dazhou": "达州", "deyang": "德阳",
    "dezhou": "德州", "dongying": "东营", "eerduosi": "鄂尔多斯", "ordos": "鄂尔多斯",
    "fushun": "抚顺", "fuyang": "阜阳", "guigang": "贵港", "haerbin": "哈尔滨",
    "harbin": "哈尔滨", "handan": "邯郸", "hangzhou": "杭州", "hanzhong": "汉中",
    "hefei": "合肥", "hengshui": "衡水", "hengyang": "衡阳", "heyuan": "河源",
    "heze": "菏泽", "hezhou": "贺州", "huaian": "淮安", "huaibei": "淮北",
    "huaihua": "怀化", "huainan": "淮南", "huanggang": "黄冈", "huangshi": "黄石",
    "hohhot": "呼和浩特", "huhehaote": "呼和浩特", "huizhou": "惠州", "jiayuguan": "嘉峪关",
    "jian": "吉安", "jiaozuo": "焦作", "jiaxing": "嘉兴", "jieyang": "揭阳",
    "jilin": "吉林", "jinan": "济南", "jingdezhen": "景德镇", "jingmen": "荆门",
    "jingzhou": "荆州", "jinhua": "金华", "jining": "济宁", "jinzhong": "晋中",
    "jinzhou": "锦州", "jiujiang": "九江", "kaifeng": "开封", "kunming": "昆明",
    "laiwu": "莱芜", "langfang": "廊坊", "lanzhou": "兰州", "leshan": "乐山",
    "lijiang": "丽江", "linfen": "临汾", "linyi": "临沂", "lishui": "丽水",
    "liuzhou": "柳州", "luohe": "漯河", "luoyang": "洛阳", "luzhou": "泸州",
    "maanshan": "马鞍山", "maoming": "茂名", "meishan": "眉山", "meizhou": "梅州",
    "mianyang": "绵阳", "mudanjiang": "牡丹江", "nanchang": "南昌", "nanchong": "南充",
    "nanjing": "南京", "nanning": "南宁", "nantong": "南通", "nanyang": "南阳",
    "ningbo": "宁波", "panzhihua": "攀枝花", "pingdingshan": "平顶山", "putian": "莆田",
    "qingdao": "青岛", "qingyuan": "清远", "qinhuangdao": "秦皇岛", "qinzhou": "钦州",
    "qiqihaer": "齐齐哈尔", "quanzhou": "泉州", "qujing": "曲靖", "rizhao": "日照",
    "sanmenxia": "三门峡", "sanya": "三亚", "shanghai": "上海", "shangqiu": "商丘",
    "shantou": "汕头", "shaoguan": "韶关", "shaoxing": "绍兴", "shaoyang": "邵阳",
    "shenyang": "沈阳", "shenzhen": "深圳", "shijiazhuang": "石家庄", "shiyan": "十堰",
    "siping": "四平", "suining": "遂宁", "suqian": "宿迁", "suzhou": "苏州", "tai'an": "泰安",
    "taian": "泰安", "taicang": "太仓", "taizhou": "台州", "taiyuan": "太原",
    "tangshan": "唐山", "tianjin": "天津", "tieling": "铁岭", "tongliao": "通辽",
    "weifang": "潍坊", "weihai": "威海", "wenzhou": "温州", "wuhan": "武汉",
    "wuhu": "芜湖", "wuxi": "无锡", "xianyang": "咸阳", "xiangyang": "襄阳",
    "xingtai": "邢台", "xining": "西宁", "xinxiang": "新乡", "xinyang": "信阳",
    "xuchang": "许昌", "xuzhou": "徐州", "yancheng": "盐城", "yangzhou": "扬州",
    "yantai": "烟台", "yibin": "宜宾", "yichang": "宜昌", "yinchuan": "银川",
    "yueyang": "岳阳", "yuncheng": "运城", "yuxi": "玉溪", "zaozhuang": "枣庄",
    "zhangjiakou": "张家口", "zhangzhou": "漳州", "zhanjiang": "湛江", "zhaoqing": "肇庆",
    "zhengzhou": "郑州", "zhenjiang": "镇江", "zhongshan": "中山", "zhoushan": "舟山",
    "zhuhai": "珠海", "zhumadian": "驻马店", "zhuzhou": "株洲", "zibo": "淄博",
    "zigong": "自贡", "zunyi": "遵义",
}
CITY_EN = {**CITY_EN_EXTRA, **CITY_EN}  # 原有条目优先（已有的写法/简称要保住）
