import pytest

from helpers import T, make_job
from jobradar.normalize import categorize
from jobradar.pipeline.ingest import ingest_run


@pytest.mark.parametrize("title,expected", [
    ("算法工程师（大模型）", ("技术", "算法")),
    ("【27校招】AI培训生(J14938)", ("管培", "管培生")),
    ("产品经理（算法方向）", ("产品", "产品经理")),
    ("模拟IC设计工程师（27届校招）", ("技术", "芯片/硬件")),
    ("数字IC验证工程师", ("技术", "芯片/硬件")),
    ("后端开发工程师", ("技术", "后端")),
    ("Java开发工程师", ("技术", "后端")),
    ("Android开发工程师", ("技术", "客户端")),
    ("前端开发工程师", ("技术", "前端")),
    ("测试开发工程师", ("技术", "测试")),
    ("嵌入式软件工程师", ("技术", "嵌入式")),
    ("软件工程师（27届校招）", ("技术", "软件开发")),
    ("UI设计师", ("设计", "设计")),
    ("芯片设计师", ("技术", "芯片/硬件")),
    ("设备工程师", ("工程制造", "工艺/设备")),
    ("销售总监/经理（CBG/全国）(J13700)", ("市场销售", "销售")),
    ("品牌传播高级总监(J13868)", ("市场销售", "市场")),
    ("审计员（2027届校招-北京分所）(J10667)", ("职能", "财务审计")),
    ("数据科学(J20776)", ("技术", "数据")),
    ("AI Agent研发(J20860)", ("技术", "算法")),
    ("固态电池CAE仿真主管工程师(J32876)", ("工程制造", "汽车工程")),
    ("底盘NVH主管工程师(J33055)", ("工程制造", "汽车工程")),
    ("内饰助理工程师（门护板）(J32945)", ("工程制造", "汽车工程")),
    ("PQE工程师", ("工程制造", "质量")),
    ("电气技术工程师", ("工程制造", "机械/电气")),
    ("项目管理-C(海天光机)(J11652)", ("项目管理", "项目管理")),
    ("项目专员(J17367)", ("项目管理", "项目管理")),
    ("产品经理（项目方向）", ("产品", "产品经理")),
    ("车载天线工程师(芜湖)(J33442)", ("技术", "芯片/硬件")),
    ("2027届-口服制剂研发研究员-江苏无锡(J24895)", ("医药", "医药研发")),
    ("证券研究所行业研究员", ("金融", "投研")),
    ("3A动作冒险游戏-战斗主策划", (None, None)),
    ("临床医师（武汉）(J14957)", ("医药", "临床医学")),
])
def test_categorize(title, expected):
    assert categorize(title) == expected


def test_category_change_does_not_create_change_event(jobs_db):
    """职类是推导数据：规则调整后静默更新，不能制造假的"变更"事件。"""
    ingest_run(jobs_db, "s1", [make_job(1, category=None, subcategory=None)], ts=T(1))
    res = ingest_run(jobs_db, "s1", [make_job(1, category="技术", subcategory="算法")], ts=T(2))
    assert res.changed == 0
    assert jobs_db.execute("SELECT COUNT(*) FROM job_event WHERE type='change'").fetchone()[0] == 0
    row = jobs_db.execute("SELECT category, subcategory FROM job WHERE id='s1:1'").fetchone()
    assert (row["category"], row["subcategory"]) == ("技术", "算法")
