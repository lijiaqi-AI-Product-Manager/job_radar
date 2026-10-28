import pytest

from jobradar.normalize import (
    batch_from_text,
    cities_from_text,
    cities_from_title,
    date_only,
    degree_min_from_jd,
    degree_min_from_text,
    grad_year_from_jd,
    grad_year_from_text,
    looks_like_location,
    normalize_degree,
)


@pytest.mark.parametrize("text,year", [
    ("【27校招】人力管培生(J15003)", 2027),
    ("审计员（2027届校招-北京分所）(J10667)", 2027),
    ("硬件工程师（27届校招）", 2027),
    ("算法工程师岗-AI机器视觉（2027校招）", 2027),
    ("2028届暑期实习-前端开发", 2028),
    ("27届校招-AI平台研发工程师(J19213)", 2027),
    ("【2026届春招】测试工程师", 2026),
    ("销售总监/经理（CBG/全国）(J13700)", None),
    ("3A动作冒险游戏-战斗主策划", None),
    ("工作经验2027年以上", None),   # 不是届别
    ("J12027 后端开发", None),     # 编号里的数字不算
    ("【2027】研究助理岗(J19663)", 2027),
    ("【2027】云控制台开发工程师（AI架构）-成都(J14240)", 2027),
    ("（2027届校招）财富管理培训生", 2027),
    ("项目经理（2027）", None),     # 括号里只有年份但不在开头的方括号里，不算
    ("【27年校招】AI战略与产品运营管培生(J14975)", 2027),
])
def test_grad_year(text, year):
    assert grad_year_from_text(text) == year


@pytest.mark.parametrize("text,year", [
    ("射频IC工程师-上海-2027(J11703)", 2027),
    ("2027-数字IC后端工程师-上海(J10312)", 2027),
    ("项目经理（2027）", 2027),
    ("工程师（3年以上经验，2027年以上不招）", None),
    ("J12027 后端开发", None),
    ("后端开发工程师", None),
])
def test_grad_year_loose_for_campus_titles(text, year):
    """校招/实习标题中独立出现的年份即届别（宽松模式只用于 campus/intern）。"""
    assert grad_year_from_text(text, loose=True) == year


@pytest.mark.parametrize("text,batch", [
    ("【2027届提前批】算法工程师", "提前批"),
    ("2027届秋招正式批-产品经理", "正式批"),
    ("【补录】硬件工程师", "补录"),
    ("2026届春招-运营", "春招"),
    ("2027秋季校园招聘 销售工程师", "秋招"),
    ("2027秋招 销售", "秋招"),
    ("后端开发工程师", None),
])
def test_batch(text, batch):
    assert batch_from_text(text) == batch


def test_none_and_empty():
    assert grad_year_from_text(None) is None and batch_from_text("") is None


@pytest.mark.parametrize("desc,req,year", [
    ("面向 2027 届毕业生，本科及以上", None, 2027),
    (None, "2028届优先", 2028),
    ("2026届、2027届均可投递", None, None),   # 同一份 JD 写了两个届别：不猜
    ("2027年毕业", None, None),               # 只认"届"；"年毕业"容易和入职年份混
    ("", "", None),
    (None, None, None),
])
def test_grad_year_from_jd(desc, req, year):
    """标题没写届别时，JD 原文里明写的「20XX届」可以作为兜底；有歧义就不填。"""
    assert grad_year_from_jd(desc, req) == year


@pytest.mark.parametrize("text,cities", [
    ("北京市", ["北京"]),
    ("江苏省-连云港市", ["连云港"]),
    ("深圳", ["深圳"]),
    ("上海市,北京市", ["上海", "北京"]),
    ("广东省·深圳市", ["深圳"]),
    ("海外", ["海外"]),
    ("", []),
    (None, []),
    ("北京市,北京市", ["北京"]),
    ("北京市-海淀区", ["北京"]),       # 有"市"一级时取市，不取区
    ("浙江省-杭州市-余杭区", ["杭州"]),
    ("上海市-浦东新区,江苏省-苏州市", ["上海", "苏州"]),
])
def test_cities(text, cities):
    assert cities_from_text(text) == cities


@pytest.mark.parametrize("title,cities", [
    ("验证工程师-深圳-2027(J11700)", ["深圳"]),
    ("临床医师（武汉）(J14957)", ["武汉"]),
    ("设备员-青岛(J34014)", ["青岛"]),
    ("数字IC后端工程师(base武汉/大连/苏州/西安/珠海/成都-27届校招)(J12716)", ["武汉", "大连", "苏州", "西安", "珠海", "成都"]),
    ("2027-数字IC后端工程师-上海(J10312)", ["上海"]),
    ("北京大学合作项目专员", []),          # 不在分隔符之间，不算
    ("深圳湾实验室研究员", []),
    ("后端开发工程师", []),
    # 2026-10-22：北森标题里的城市分隔符与「城市+机构」写法（实测缺失城市的标题提取率 0% → 有解）
    ("2027届校招-销售管理类（直营电商/济南&青岛）(J14673)", ["济南", "青岛"]),
    ("2027届校招-系统支持顾问（软件交付部/苏州｜郑州）(J14673)", ["苏州", "郑州"]),
    ("审计员-武汉总所(J10552)", ["武汉"]),
    ("审计员（2027届校招-上海自贸区分所）(J10677)", ["上海"]),
    ("测试开发工程师-成都1(J10674)", ["成都"]),
    ("业务员（中国香港）(J11541)", ["香港"]),
    ("【2027校招】SQE（重庆公司）(J16716)", ["重庆"]),
    ("人才管理交付经理（CBG北京）(J14590)", ["北京"]),
    ("北京烤鸭师傅", []),                  # 城市+非机构词，不猜
    ("上海大众汽车工程师", []),
    # 2026-10-26：北森校招标题里「届次前缀 + 城市」的写法（真实抓取样本）
    ("27届校招北京-高中语文一对一教师(J55560)", ["北京"]),
    ("2027届校招-北京-销售管培生", ["北京"]),
    ("暑期实习上海-测试开发", ["上海"]),
    ("北京-运营助理", ["北京"]),
    ("成都-前端开发工程师", ["成都"]),
    # 这些城市是专有名词的一部分，判成办公地点会把岗位挂到错误城市 → 一律留空
    ("研发技术岗（北京本部）", []),
    ("北京先驱-数字海洋部科研岗(J33568)", []),
    ("审计业务岗（北京特派办）(J89186)", []),
])
def test_cities_from_title(title, cities):
    assert cities_from_title(title) == cities


@pytest.mark.parametrize("text,ok", [
    ("北京市", True), ("江苏省-连云港市", True), ("北京市-海淀区,武汉市", True), ("深圳", True),
    ("海淀区", True), ("全国", True), ("海外", True),
    ("中船智海创新研究院有限公司", False), ("技术研发类", False), ("", False), (None, False),
])
def test_looks_like_location(text, ok):
    assert looks_like_location(text) is ok


@pytest.mark.parametrize("text,degree", [
    ("硕士、博士", "硕士"), ("本科及以上", "本科"), ("博士", "博士"), ("大专", "大专"),
    ("本科/硕士", "本科"), ("不限", None), ("", None), (None, None),
])
def test_degree_min(text, degree):
    assert degree_min_from_text(text) == degree


@pytest.mark.parametrize("text,degree", [
    ("任职要求：本科及以上学历，计算机相关专业", "本科"),
    ("1. 硕士及以上学历；2. 有实习经历优先", "硕士"),
    ("学历：大专", "大专"),
    ("2024 年毕业于荷兰莱顿大学获博士学位", None),   # 描述经历，不是岗位要求
    ("团队由 30 位博士组成", None),                  # 描述团队，不是岗位要求
    ("统招本科毕业，3 年以上经验", "本科"),
    ("岗位要求：\n1、本科及以上；\n2、熟练使用 Python", "本科"),
    ("五险一金，提供班车", None),
])
def test_degree_min_from_jd_needs_context(text, degree):
    """JD 正文必须带上下文锚点，否则"博士团队"这类描述会把统计拉高。"""
    assert degree_min_from_jd(text) == degree


def test_degree_min_from_jd_prefers_lowest_listed():
    assert degree_min_from_jd("学历要求：硕士、博士") == "硕士"
    assert degree_min_from_jd("任职资格：大专以上，本科优先") == "大专"


@pytest.mark.parametrize("raw,degree", [
    ("大专", "大专"), ("专科", "大专"), ("专科及以上", "大专"), ("大专及以上", "大专"),
    ("本科", "本科"), ("本科及以上", "本科"), ("本科及以上或预备技师", "本科"),
    ("硕士研究生", "硕士"), ("硕士", "硕士"), ("研究生", "硕士"),
    ("博士研究生", "博士"), ("博士", "博士"),
    ("不限", None), ("高中", None), ("中技（中专/技校/职高）", None), (None, None), ("", None),
])
def test_normalize_degree_folds_platform_spellings(raw, degree):
    """平台原值同一字段 26 种写法，必须折成四档，否则筛选既漏又错。"""
    assert normalize_degree(raw) == degree


def test_normalize_degree_prefers_highest_specific_word():
    # 「博士研究生」里既有 博士 也有 研究生，不能落到 硕士
    assert normalize_degree("博士研究生及以上") == "博士"

@pytest.mark.parametrize("en,city", [
    ("Lianyungang", "连云港"),   # Workday 真实写法（pypinyin 生成）
    ("LianYungang", "连云港"),   # 大小写不敏感
    ("Urumqi", "乌鲁木齐"),       # 官方英文名，不是拼音
    ("Harbin", "哈尔滨"),
    ("Lhasa", "拉萨"),
    ("Hohhot", "呼和浩特"),
    ("xi'an", "西安"),
    ("Hong Kong", "香港"),
])
def test_city_from_english_covers_workday_spellings(en, city):
    """外资站（Workday）用英文城市名：拼音 + 官方异写都要能映射，否则城市全空。

    背景（2026-10-24）：CITY_EN 原来只有 27 条，Workday 源的城市覆盖率被它卡在
    64%~90%；补齐到 101 条后 Intel 90%→100%、辉瑞 75%→88%。
    """
    from jobradar.normalize import city_from_english
    assert city_from_english(en) == city


def test_city_from_english_unknown_returns_none():
    from jobradar.normalize import city_from_english
    assert city_from_english("Jiangsu") is None      # 省名不是城市
    assert city_from_english("") is None


@pytest.mark.parametrize("title,expected", [
    ("实习生（上海新嘉中心店）", ["上海"]),          # 省份前缀被剥掉后不能丢城市（2026-10-26 修）
    ("实习生烘焙师（杭州湖滨88Lab店）", ["杭州"]),
    ("咖啡师（成都IFS店）", ["成都"]),
    ("门店伙伴（深圳）", ["深圳"]),
    ("北京烤鸭", []),                                # 不是门店，别误判
    ("上海大众汽车", []),
])
def test_cities_from_store_titles(title, expected):
    assert cities_from_title(title) == expected


# ---- date_only：把各平台的原值归一成 YYYY-MM-DD（2026-10-26 逐个实测的原值）----


@pytest.mark.parametrize("value,expected", [
    ("2026-11-17 23:59:59", "2026-11-17"),          # 大易 endDate
    ("2026年10月21日", "2026-10-21"),                # 腾讯 LastUpdateTime
    ("2026-10-26T13:15:00+08:00", "2026-10-26"),     # ISO 带时区
    (1786960999000, "2026-08-17"),                    # 飞书/美团毫秒时间戳
    ("1792991700000", "2026-10-26"),                  # 字符串形式的时间戳
    (1792991700, "2026-10-26"),                       # 秒级时间戳
])
def test_date_only_accepts_real_platform_values(value, expected):
    assert date_only(value) == expected


@pytest.mark.parametrize("value", [
    "0001-01-01T00:00:00",   # 北森未填（311 个租户全部如此，实测）
    "3000-01-01",            # 大易"长期开放"哨兵
    "9999-12-31",
    None, "", 0, -1,
    99999999999999999,       # 越界时间戳：不能让 fromtimestamp 抛 ValueError
    "not a date", "2026-13-01", "abc",
])
def test_date_only_rejects_sentinels_and_garbage(value):
    assert date_only(value) is None
