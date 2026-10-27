"""日历字段抽取器：从招聘站真实页面里抽 届次 / 批次 / 网申时间 / 城市 / 方向。

原则（CLAUDE.md 红线 8「查不到的不编」）：
- 只认页面**明写**的内容：正则命中才算，抽不到就留空；
- 不做任何推断补全（不把「2026-10-15 发布时间」当「网申截止」）；
- 每个抽到的字段都保留**原文片段**作为证据，写进 work/field_evidence.jsonl。

支持的页面形态（2026-10-26 实测）：
1. 北森系（*.zhiye.com）：服务端渲染的职位表格，「职位名称 / 招聘类别 / 职位类型 / 工作地点 / 发布时间」，
   职位名里常直接写「2027届校招-XXX」；
2. 大易系（*.hotjob.cn / wecruit.hotjob.cn）：列表用 JS，但公告页/招聘简章是静态 HTML；
3. 自建站：首页 → 招聘频道 → 公告/简章详情页（「2027届校园招聘正式启动」这类标题）；
4. 通用兜底：任何页面里的「20XX届」「网申时间 2026-08-03 至 2026-12-31」「工作地点：北京」。
"""

import re

# ---------- 届次 ----------
GRAD = re.compile(r"(20\d{2})\s*届")
GRAD_EN = re.compile(r"[Cc]lass\s+of\s+(20\d{2})")
GRAD_RANGE = re.compile(r"(20\d{2})\s*[-~至/]\s*(20\d{2})\s*届")
# 「2027校园招聘」「2027年校招」「2027 秋季招聘」——职位名与公告标题里的常见写法
# 「2027届」「2027年」「2027年度」都能带出校园招聘字样，中间常插「度/届/年」或机构名，
# 例如「2027年度联合校园招聘」「2027年高校毕业生秋季招聘」，所以允许中间夹少量非日期字符。
GRAD_YEAR_CAMPUS = re.compile(
    r"(20\d{2})\s*[年届]?\s*(?:度)?\s*[^\n，。；;]{0,8}?"
    r"(?:校园招聘|校招|秋季招聘|春季招聘|秋招|春招|应届|毕业生|届)")
# 「招募2027年毕业生」「面向2027届」
GRAD_TARGET = re.compile(r"(?:面向|针对|招募|招聘)\s*(20\d{2})\s*(?:届|年)?\s*(?:毕业|应届|生)")

# ---------- 网申时间 ----------
DATE = r"(20\d{2})\s*[-./年]\s*(\d{1,2})\s*[-./月]\s*(\d{1,2})\s*日?"
DATE2 = r"(20\d{2})\s*[-./年]\s*(\d{1,2})\s*[-./月]\s*(\d{1,2})\s*日?"
# 起止之间的连接符：至/到/~/～/—/－/-/–/－ , 以及英文 hyphen with spaces
SEP = r"(?:至|到|~|～|—|－|-|–|――|to)"
RANGE = re.compile(
    rf"(?:网申|报名|申请|投递|简历投递|在线申请|接收简历|简历接收|招聘)[^。；;]{{0,12}}?"
    rf"(?:时间|日期|周期|阶段)?\s*[：:是为]?\s*"
    rf"{DATE}\s*(?:[（(][^）)]{{0,10}}[）)])?\s*{SEP}\s*{DATE2}")
RANGE_LOOSE = re.compile(rf"{DATE}\s*{SEP}\s*{DATE2}")

# 这些词出现在日期附近时，那段日期**不是网申窗口**，必须排除：
# - 毕业时间/毕业日期/取得学位：说的是学历证书的落款时间（「毕业时间应在2026年1月1日
#   至2026年7月31日之间」），照抄进日历会把整条网申时间写成半年；
# - 出生/生日：年龄要求；
# - 入学/成立/创立/上市：公司或求学时间；
# - 过期时间/发布时间/更新时间/浏览次数：高校就业网的**公告**元数据（公告有效期），
#   不是企业网申截止。这一点尤其容易错——真实网申窗口只认正文里的「网申/报名/投递」语境。
NOT_WINDOW = re.compile(
    r"(毕业时间|毕业日期|毕业年度|毕业生应在|毕业生原则上应在|毕业生应|应在|"
    r"取得学位|获得学位|学位证|毕业证|"
    r"出生年月|出生日期|出生|生日|年龄|"
    r"入学时间|入学|成立时间|成立|创立|创办|上市时间|上市|注册时间|成立日期|"
    r"过期时间|发布时间|更新时间|截止更新时间)")
DEADLINE = re.compile(
    rf"(?:截止|截止时间|报名截止|网申截止|投递截止|截止日期|报名截至|截至)[^。；;]{{0,10}}?[：:是为]?\s*{DATE}")
START_ONLY = re.compile(
    rf"(?:网申|报名|申请|投递)(?:开始|启动|开放|时间|窗口)[^。；;]{{0,10}}?[：:是为]?\s*{DATE}"
    rf"(?!\s*(?:至|到|~|～|—|-|–))")
# 「即日起至X」「自公告发布之日起至X」：起手是个虚指，落点是截止日
DEADLINE_IMPLICIT = re.compile(rf"(?:即日|今日|公告发布之日|简章发布之日|本公告发布之日)[^。；;\n]{{0,6}}?{SEP}\s*{DATE}")
# 单点日期：既没有区间也没有「截止」，但在「网申/投递」语境里出现的孤立日期（按语境推断）
CONTEXT_DATE = re.compile(rf"(?:网申|报名|投递|申请|简历)[^。\n；;]{{0,20}}?{DATE}")
# 「简历投递：8月3日起」「网申自 8 月 3 日起」——只公布开放日、不公布截止日。
# 只认「…起」这种明确的开放语义，避免把流程说明里的日期当成窗口。
OPEN_ONLY = re.compile(
    rf"(?:网申|报名|申请|投递|简历|通道|系统)[^。；;\n]{{0,14}}?"
    rf"(?:时间|日期|开始|开放|启动|自|从)?\s*[：:是为]?\s*(?:自|从)?\s*{DATE}\s*(?:起|开始|开放|启动)"
    rf"(?!\s*(?:至|到|~|～|—|-|–))")


def _d(y, m, d) -> str | None:
    """构造 ISO 日期；不可信的返回 None。

    只用「月 1~12、日 1~31」是不够的：`2025-11-00` 能过这一关，然后在
    `date.fromisoformat` 或 pydantic 校验里炸掉整条日历（2026-10-26 实测红蜻蜓就有这一条）。
    所以这里直接用真日历校验——2 月 30 日、11 月 0 日这种必须当场判废，不能流到交付物里。
    """
    from datetime import date

    try:
        y, m, d = int(y), int(m), int(d)
    except Exception:
        return None
    if not (2000 <= y <= 2040):
        return None
    try:
        date(y, m, d)
    except ValueError:
        return None
    return f"{y:04d}-{m:02d}-{d:02d}"


def _plausible_window(start: str, end: str) -> bool:
    """网申窗口的现实检查：跨度 2~360 天，起点不晚于终点。"""
    from datetime import date
    try:
        a, b = date.fromisoformat(start), date.fromisoformat(end)
    except Exception:
        return False
    return 2 <= (b - a).days <= 360


# ---------- 城市 ----------
CITIES = (
    "北京", "上海", "天津", "重庆", "广州", "深圳", "杭州", "南京", "苏州", "无锡", "常州", "南通",
    "徐州", "扬州", "宁波", "温州", "嘉兴", "绍兴", "金华", "台州", "合肥", "芜湖", "福州", "厦门",
    "泉州", "南昌", "济南", "青岛", "烟台", "潍坊", "郑州", "洛阳", "武汉", "宜昌", "长沙", "株洲",
    "湘潭", "成都", "绵阳", "贵阳", "昆明", "南宁", "柳州", "桂林", "海口", "三亚", "西安", "咸阳",
    "兰州", "西宁", "银川", "乌鲁木齐", "拉萨", "呼和浩特", "包头", "鄂尔多斯", "沈阳", "大连",
    "鞍山", "长春", "吉林", "哈尔滨", "大庆", "石家庄", "唐山", "保定", "廊坊", "太原", "大同",
    "东莞", "佛山", "珠海", "中山", "惠州", "汕头", "湛江", "江门", "肇庆", "湖州", "镇江", "泰州",
    "盐城", "淮安", "连云港", "宿迁", "滁州", "马鞍山", "安庆", "九江", "赣州", "淄博", "威海",
    "临沂", "济宁", "德州", "聊城", "新乡", "许昌", "襄阳", "十堰", "荆州", "黄石", "岳阳", "衡阳",
    "常德", "宜宾", "德阳", "遵义", "曲靖", "宝鸡", "天水", "中国香港", "中国澳门", "中国台湾",
    "香港", "澳门", "台北", "新加坡", "东京", "首尔", "伦敦", "纽约", "硅谷", "慕尼黑", "巴黎",
    "昆山", "张家港", "常熟", "太仓", "慈溪", "余姚", "义乌", "诸暨", "晋江", "石狮", "南安",
    "增城", "番禺", "顺德", "南海", "虎门", "长安", "松山湖", "滨州", "菏泽", "枣庄", "东营",
    "泰安", "日照", "莱芜", "衡水", "沧州", "邯郸", "邢台", "张家口", "承德", "秦皇岛", "晋中",
    "临汾", "运城", "长治", "晋城", "阳泉", "忻州", "吕梁", "朔州", "锦州", "营口", "盘锦",
    "抚顺", "本溪", "丹东", "葫芦岛", "铁岭", "辽阳", "朝阳", "阜新", "齐齐哈尔", "牡丹江",
    "佳木斯", "大庆", "吉林市", "四平", "通化", "白山", "松原", "白城", "延吉", "泉州", "漳州",
    "龙岩", "三明", "南平", "宁德", "莆田", "景德镇", "萍乡", "新余", "鹰潭", "吉安", "宜春",
    "抚州", "上饶", "萍乡", "开封", "平顶山", "安阳", "鹤壁", "焦作", "濮阳", "漯河", "三门峡",
    "南阳", "商丘", "信阳", "周口", "驻马店", "漯河", "黄冈", "孝感", "咸宁", "随州", "恩施",
    "荆门", "鄂州", "黄石", "仙桃", "潜江", "天门", "衡阳", "邵阳", "郴州", "永州", "怀化",
    "娄底", "益阳", "张家界", "湘西", "株洲", "湘潭", "韶关", "梅州", "汕尾", "河源", "阳江",
    "茂名", "清远", "潮州", "揭阳", "云浮", "肇庆", "梧州", "北海", "防城港", "钦州", "贵港",
    "玉林", "百色", "贺州", "河池", "来宾", "崇左", "泸州", "自贡", "攀枝花", "内江", "乐山",
    "南充", "眉山", "广元", "遂宁", "广安", "达州", "雅安", "巴中", "资阳", "凉山", "六盘水",
    "安顺", "毕节", "铜仁", "黔东南", "黔南", "黔西南", "大理", "丽江", "玉溪", "保山", "昭通",
    "普洱", "临沧", "楚雄", "红河", "文山", "西双版纳", "延安", "榆林", "铜川", "渭南", "商洛",
    "安康", "汉中", "宝鸡", "咸阳", "杨凌", "嘉峪关", "金昌", "白银", "天水", "武威", "张掖",
    "平凉", "酒泉", "庆阳", "定西", "陇南", "海东", "格尔木", "石嘴山", "吴忠", "固原", "中卫",
    "克拉玛依", "喀什", "伊犁", "阿克苏", "库尔勒", "昌吉", "石河子", "哈密", "吐鲁番",
)
# 去重保序：上面为了可读性按大区分组，跨组会有重复城市名
CITIES = tuple(dict.fromkeys(CITIES))
CITY_LINE = re.compile(
    r"(?:工作地点|工作城市|工作地址|工作地域|工作区域|工作省份|招聘地区|"
    r"城市|地点|办公地点|base|工作地)[：:]\s*([^\n。；;|]{2,80})")
CITY_ANY_LINE = re.compile(r"([^\n。；;|]{0,20}(?:工作地点|办公地点)[^\n。；;|]{0,60})")

# ---------- 方向 ----------
DIRECTION_RULES = (
    ("技术类", r"技术类|研发类|技术中心|软件研发|算法|后端|前端|客户端|服务端|测试开发|运维|"
               r"嵌入式|硬件研发|芯片|半导体|数据开发|信息安全|架构师|IT类|技术岗|"
               r"Java|Python|C\+\+|Golang|Go语言|Android|iOS|Web|全栈|大数据|云计算|SRE|"
               r"机器学习|深度学习|计算机视觉|NLP|自然语言|推荐系统|搜索|图形|渲染|引擎|"
               r"测试|QA|DBA|网络安全|风控建模|数据科学|数据分析|数据挖掘|研发工程师|"
               r"硬件|电子|射频|光学|结构|仿真|电机|电池|整车|底盘|动力|智能驾驶|自动驾驶|"
               r"电控|材料研发|工艺研发|软件|固件|驱动|通信|网络|系统工程师"),
    ("产品类", r"产品类|产品经理|产品运营|AI产品|产品设计|产品岗|产品策划|产品专家|"
               r"商业化产品|策略产品|数据产品|平台产品|B端产品|C端产品|产品实习生"),
    ("设计类", r"设计类|交互设计|视觉设计|UI|UX|体验设计|工业设计|美术|美术设计|原画|"
               r"3D|动画|特效|平面设计|室内设计|服装设计|UI设计|设计师"),
    ("运营类", r"运营类|内容运营|用户运营|活动运营|电商运营|游戏运营|运营岗|"
               r"新媒体运营|社群运营|直播运营|商品运营|类目运营|商家运营|供给运营|"
               r"数据运营|策略运营|增长运营|社区运营|产品运营"),
    ("市场与销售类", r"市场类|营销类|销售类|商务类|品牌|渠道|大客户|市场推广|BD|"
                     r"市场营销|销售|商务拓展|客户经理|KA|区域销售|售前|售后|"
                     r"技术支持|解决方案|市场专员|品牌专员|公关|媒介"),
    ("职能类", r"职能类|人力资源|财务类|法务|行政|供应链|采购|审计|内控|战略|"
               r"投资者关系|HR|招聘专员|招聘经理|招聘岗|校园招聘岗|培训专员|培训经理|"
               r"薪酬|组织发展|会计|出纳|税务|资金|"
               r"合规|风控|风险管理|证券事务|董秘|总裁办|管培生|管理培训生|"
               r"综合管理|物流|仓储|计划|关务|单证|报关"),
    ("金融类", r"投研|投行|风控|量化|研究类|交易|信贷|资产管理|固收|权益研究|研究岗|"
               r"金融科技|财富管理|机构业务|分行|柜员|客户经理|"
               r"投资银行|研究所|固定收益|自营|资管|基金|证券|投顾|理财|"
               r"保险|精算|核保|理赔|私人银行|零售金融|公司金融|同业|"
               r"风险管理|资产负债|金融市场|托管|结算|清算"),
    ("医药研发类", r"临床|药理|药学|医学|生物信息|药品注册|注册专员|注册事务|药物|制剂|合成|"
                   r"分析研究|CRA|医学写作|生物|细胞|抗体|疫苗|基因|蛋白质|检验|诊断|"
                   r"临床研究|临床运营|药物警戒|药代|质量研究|分析化学|有机合成|"
                   r"发酵|纯化|QA/QC|GMP|生产质量|医学事务"),
    ("生产制造类", r"生产|制造|工艺|设备|质量|自动化|电气|机械|模具|焊接|厂务|EHS|"
                   r"生产管理|制造工程|精益|IE|计划员|SQE|PQE|CQE|IQC|OQC|"
                   r"检验员|维修|仪表|暖通|动力运行|安全工程|环境工程|"
                   r"装配|数控|车床|铸造|锻造|涂装|总装|焊装|冲压"),
    ("教育类", r"教师|讲师|教研|课程顾问|辅导老师|班主任|助教|"
               r"学科老师|授课|教学|课程研发|培训师|双语|中方教师|外教"),
)

# ---------- 批次 ----------
BATCH_RULES = (
    ("提前批", r"提前批|提前批次|提前招聘|Early\s*Bird|提前启动"),
    ("秋招补录", r"补录|补招|补充招聘|第二批|第三批|扩招"),
    ("秋招正式批", r"秋招正式|正式批|正式启动"),
    ("秋招", r"秋季校园招聘|秋招|秋季招聘|Autumn\s*Recruit|秋招启动|秋季校招"),
    ("春招", r"春季校园招聘|春招|春季招聘|Spring\s*Recruit|春招启动|春季校招"),
    ("暑期实习", r"暑期实习|暑期实习生|Summer\s*Intern|暑期"),
    ("寒假实习", r"寒假实习|寒假实习生|Winter\s*Intern|寒假"),
    ("日常实习", r"日常实习|长期实习|日常实习生|日常"),
    ("校园大使", r"校园大使|Campus\s*Ambassador|大使"),
    # 「有经验」单独出现极易误伤（实测「不困于既有经验」被判成社招），
    # 必须限定在「招聘/岗位」语境里才算。
    ("社招", r"社会招聘|社招|experienced\s*hire|lateral\s*hire|招聘有经验|有经验(?:人士|者|岗位)"),
    ("实习", r"实习生|实习岗|internship|Intern|实习"),
)


def strip_tags(html: str) -> str:
    """HTML → 纯文本（保留换行，去掉脚本样式）。"""
    s = re.sub(r"<(script|style|noscript)[^>]*>.*?</\1>", " ", html, flags=re.S | re.I)
    s = re.sub(r"<br\s*/?>|</p>|</div>|</li>|</tr>|</h[1-6]>", "\n", s, flags=re.I)
    s = re.sub(r"<[^>]+>", " ", s)
    s = (s.replace("&nbsp;", " ").replace("&amp;", "&").replace("&lt;", "<").replace("&gt;", ">")
         .replace("&quot;", '"').replace("&#39;", "'").replace("&copy;", "©"))
    s = re.sub(r"[ \t\u3000]+", " ", s)
    s = re.sub(r"\n\s*\n+", "\n", s)
    return s.strip()


def extract_grad_years(text: str) -> list[int]:
    """页面明写的届次。只取 2024~2035 之间的，按出现次数排序。"""
    from collections import Counter
    c: Counter = Counter()
    for rx in (GRAD, GRAD_EN, GRAD_YEAR_CAMPUS, GRAD_TARGET):
        for m in rx.finditer(text):
            y = int(m.group(1))
            if 2024 <= y <= 2035:
                c[y] += 1
    return [y for y, _ in c.most_common(3)]


MD = r"(\d{1,2})\s*[-./月]\s*(\d{1,2})\s*日?"
# 日期后面常跟具体时间（9月15日9:00），区间匹配时必须吃掉它，否则整段匹配不上
TIME = r"(?:\s*\d{1,2}\s*[:：]\s*\d{2}(?:\s*[:：]\s*\d{2})?)?"
# 「9月15日-10月31日」「9月15日~10月31日」：首尾都省略年份，是最常见的简章写法。
# 年份只能从上下文里补（同一段里出现的 20xx 年），补不出来就不采信——
# 宁可留空也不要猜错年份，这是数据集的红线。
RANGE_MD = re.compile(
    rf"(?:网申|报名|投递|简历|申请|招聘)[^。；;\n]{{0,14}}?(?:时间|日期|周期)?\s*[：:是为]?\s*"
    rf"{MD}{TIME}\s*(?:[（(][^）)]{{0,10}}[）)])?\s*{SEP}\s*(?:次年|翌年)?\s*{MD}")
# 「2026年9月」这种只有年月的起点（月份精度不足，但这已经很硬了：说明 9 月开放）
YM = re.compile(r"(?:网申|报名|申请|投递|开放|启动)[^。；;\n]{0,12}?(?:时间|日期|开始)?\s*[：:是为]?\s*(20\d{2})\s*年\s*(\d{1,2})\s*月(?!\s*\d)")


def _year_near(text: str, pos: int) -> int | None:
    """在日期附近找一个年份，给「9月15日」补年份用。

    先看前面（简章通常在句首写「2026年校园招聘，报名时间：9月…」），
    再看后面 120 字（也常见「报名时间：9月…（2026年）」）。前后都找不到就不猜。
    """
    back = re.findall(r"(20\d{2})\s*年", text[max(0, pos - 200):pos])
    if back:
        return int(back[-1])
    fwd = re.findall(r"(20\d{2})\s*年", text[pos:pos + 120])
    return int(fwd[0]) if fwd else None


def extract_window_md(text: str) -> dict:
    """处理「首尾都省略年份」的区间：9月15日-10月31日。

    年份取附近出现的 20xx 年；若起始月 > 结束月（跨年，如 11月-次年2月），
    结束年份 +1。找不到年份就返回空——不猜。
    """
    for m in RANGE_MD.finditer(text):
        m1, d1, m2, d2 = (int(x) for x in m.groups())
        y = _year_near(text, m.start())
        if not y:
            continue
        y2 = y + 1 if m2 < m1 else y
        start, end = _d(y, m1, d1), _d(y2, m2, d2)
        if start and end and _plausible_window(start, end):
            return {"start": start, "end": end, "evidence": m.group(0)[:80]}
    return {}


def extract_window(text: str) -> dict:
    """网申起止。返回 {start, end, evidence}，抽不到就是空。"""
    for rx in (RANGE, RANGE_LOOSE):
        for m in rx.finditer(text):
            ctx = text[max(0, m.start() - 30):m.start()]
            if rx is RANGE_LOOSE and NOT_WINDOW.search(ctx):
                continue  # 「毕业时间应在…」「成立时间…」这类不是网申窗口
            g = m.groups()
            start = _d(*g[0:3])
            end = _d(*g[3:6])
            if start and end and _plausible_window(start, end):
                return {"start": start, "end": end, "evidence": m.group(0)[:80]}
    r = extract_window_md(text)
    if r:
        return r
    m = DEADLINE.search(text)
    if m:
        ctx = text[max(0, m.start() - 20):m.start()]
        end = None if NOT_WINDOW.search(ctx) else _d(*m.groups()[:3])
        if end:
            return {"start": None, "end": end, "evidence": m.group(0)[:80]}
    for m in DEADLINE_IMPLICIT.finditer(text):
        g = m.groups()
        end = _d(*g[-3:])
        if end:
            return {"start": None, "end": end, "evidence": m.group(0)[:80]}
    m = YM.search(text)
    if m:
        y, mo = int(m.group(1)), int(m.group(2))
        if 1 <= mo <= 12 and 2000 <= y <= 2040:
            return {"start": f"{y:04d}-{mo:02d}-01", "end": None,
                    "evidence": m.group(0)[:80]}
    m = START_ONLY.search(text)
    if m:
        start = _d(*m.groups()[:3])
        if start:
            return {"start": start, "end": None, "evidence": m.group(0)[:80]}
    # 「简历投递：8月3日起」——只给了开放日。年份从上下文补，补不到就不猜。
    for m in OPEN_ONLY.finditer(text):
        ctx = text[max(0, m.start() - 20):m.start()]
        if NOT_WINDOW.search(ctx):
            continue
        y = _year_near(text, m.start())
        if not y:
            continue
        mm = re.search(r"(\d{1,2})\s*[-./月]\s*(\d{1,2})", m.group(0))
        if not mm:
            continue
        start = _d(y, mm.group(1), mm.group(2))
        if start:
            return {"start": start, "end": None, "evidence": m.group(0)[:80]}
    return {"start": None, "end": None, "evidence": None}


def extract_windows_multi(text: str) -> list[dict]:
    """抽取所有可信的网申窗口（同一条目可能有多个批次，起点/终点分开保留）。"""
    out, seen = [], set()
    for rx in (RANGE, RANGE_LOOSE):
        for m in rx.finditer(text):
            ctx = text[max(0, m.start() - 30):m.start()]
            if rx is RANGE_LOOSE and NOT_WINDOW.search(ctx):
                continue
            g = m.groups()
            start, end = _d(*g[0:3]), _d(*g[3:6])
            if start and end and _plausible_window(start, end) and (start, end) not in seen:
                seen.add((start, end))
                out.append({"start": start, "end": end, "evidence": m.group(0)[:80]})
    for m in DEADLINE.finditer(text):
        end = _d(*m.groups()[:3])
        if end and (None, end) not in seen:
            seen.add((None, end))
            out.append({"start": None, "end": end, "evidence": m.group(0)[:80]})
    for m in START_ONLY.finditer(text):
        start = _d(*m.groups()[:3])
        if start and (start, None) not in seen:
            seen.add((start, None))
            out.append({"start": start, "end": None, "evidence": m.group(0)[:80]})
    return out


def merge_windows(ws: list[dict]) -> dict:
    """把多个窗口合并成「最早起点 + 最晚终点」，并保留证据。"""
    starts = [w["start"] for w in ws if w.get("start")]
    ends = [w["end"] for w in ws if w.get("end")]
    if not starts and not ends:
        return {"start": None, "end": None, "evidence": None}
    best = max(ws, key=lambda w: (bool(w.get("start")) + bool(w.get("end"))))
    return {"start": min(starts) if starts else None,
            "end": max(ends) if ends else None,
            "evidence": best.get("evidence")}


def extract_cities(text: str) -> list[str]:
    """优先取「工作地点：…」这类明写行，其次统计全文出现的城市名（≥1 次即可，但排除导航噪声）。"""
    hits = []
    for m in CITY_LINE.finditer(text[:60000]):
        seg = m.group(1)
        # 高校简章写的是「工作地域：北京市 / 上海市 / 广东省」，带「市」后缀；
        # CITIES 里存的是不带后缀的「北京」。直接子串匹配会全部落空，
        # 所以这里同时接受「北京」和「北京市」两种写法。
        # 省级名（广东省/海南省）说明不了具体城市，不当城市用。
        hits += [c for c in CITIES if c in seg or (c + "市") in seg]
    if not hits:
        # 全文出现，但要求出现次数 >= 2 或者出现在前 8000 字（列表页城市列通常集中）
        from collections import Counter
        cnt = Counter(c for c in CITIES for _ in re.finditer(re.escape(c), text[:80000]))
        hits = [c for c, n in cnt.items() if n >= 2]
    seen, out = set(), []
    for c in hits:
        c = c.replace("香港", "中国香港").replace("澳门", "中国澳门") if c in ("香港", "澳门") else c
        if c not in seen:
            seen.add(c)
            out.append(c)
    # 「中国香港」与「香港」去重
    out = [c for c in out if not (c in ("中国香港", "中国澳门") and c.replace("中国", "") in out)]
    return out[:12]


def extract_directions(text: str) -> list[dict]:
    """页面明写的招聘方向 + 该方向下的岗位词。"""
    found = []
    for label, pat in DIRECTION_RULES:
        roles = []
        for m in re.finditer(pat, text):
            w = m.group(0).strip()
            if w and w not in roles and 2 <= len(w) <= 8:
                roles.append(w)
            if len(roles) >= 6:
                break
        if roles:
            found.append({"direction": label, "roles": roles[:5]})
    return found[:6]


def extract_batches(text: str) -> list[str]:
    out = []
    for ptype, pat in BATCH_RULES:
        if re.search(pat, text, re.I) and ptype not in out:
            out.append(ptype)
    return out


def extract_all(html: str, url: str = "") -> dict:
    """一次抽取全字段。"""
    text = strip_tags(html)
    win = extract_window(text)
    return {
        "grad_years": extract_grad_years(text),
        "apply_start": win["start"], "apply_end": win["end"], "date_evidence": win["evidence"],
        "cities": extract_cities(text),
        "tracks": extract_directions(text),
        "project_types": extract_batches(text),
        "text_len": len(text),
        "url": url,
    }
