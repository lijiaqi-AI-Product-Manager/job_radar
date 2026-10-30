"""把人工复核过的「目标公司 -> 就业网登记名」写成 sources/campus.yaml。

复核结论（2026-10-30，南开就业网 1,000 条招聘信息）：
- 收：目标公司本体或其分公司/子公司/研究院（同一集团在招）。
- 不收：①「迪卡侬…南开大悦城分公司」→ 大悦城（地名撞名）；②「东莞市步步高实验学校」
  → 步步高（同名不同业）；③ 已覆盖公司。
"""

from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "sources" / "campus.yaml"

# 目标公司 -> 就业网上出现过的登记名（严格按这串字符串做归属校验）
CURATED: dict[str, list[str]] = {
    "蓝月亮": ["蓝月亮（中国）有限公司"],
    "兴业银行": ["兴业银行股份有限公司天津分行"],
    "华为": ["华为技术有限公司"],
    "鲁南制药": ["鲁南制药集团股份有限公司"],
    "华能集团": ["华能天成融资租赁有限公司", "华能山东石岛湾核电有限公司"],
    "中国华能": ["中国华能集团有限公司"],
    "山东高速": ["山东高速齐鲁号欧亚班列运营有限公司"],
    "平安银行": ["平安银行股份有限公司长沙分行"],
    "新奥集团": ["新奥集团股份有限公司"],
    "中信集团": ["中信证券股份有限公司深圳分公司", "中信金融租赁有限公司", "中信信托有限责任公司"],
    "中国中煤": ["中国中煤能源集团有限公司"],
    "中国出口信用保险": ["中国出口信用保险公司"],
    "中国大唐": ["中国大唐集团数字科技有限公司"],
    "中国旅游集团": ["中国旅游集团有限公司"],
    "中国铁塔": ["中国铁塔股份有限公司浙江省分公司"],
    "中广核": ["中广核（北京）新能源科技有限公司"],
    "京能集团": ["京能数字产业有限公司"],
    "保利集团": ["保利和润房地产投资顾问有限公司"],
    "华润江中": ["华润江中药业股份有限公司"],
    "华润集团": ["华润雪花啤酒（中国）投资有限公司", "华润江中药业股份有限公司"],
    "四川九洲": ["四川九洲投资控股集团有限公司"],
    "国家电投": ["国家电投集团天津电力有限公司"],
    "国泰海通": ["国泰海通证券股份有限公司湖南分公司"],
    "天合光能": ["天合光能股份有限公司"],
    "天士力": ["天士力医药集团股份有限公司"],
    "恒丰银行": ["恒丰银行股份有限公司"],
    "格林美": ["格林美股份有限公司"],
    "温州银行": ["温州银行股份有限公司"],
    "西安银行": ["西安银行股份有限公司"],
    "重庆银行": ["重庆银行股份有限公司"],
    "中科闻歌": ["北京中科闻歌科技股份有限公司"],
    "奥翔药业": ["浙江奥翔药业股份有限公司"],
    "虎牙": ["广州虎牙科技有限公司"],
    "恒瑞医药": ["江苏恒瑞医药股份有限公司"],
}

HEADER = """# 高校就业网「招聘信息」源（聚合口径 grade C）。
# 2026-10-30 首批：南开大学学生就业指导中心 /correcruit/，1,000 条招聘信息里
# 与目标池对齐出 34 家未覆盖公司，人工复核后逐家建源（见 work/gen_campus_yaml.py）。
# 合规：公开 HTML、无登录/验证码/签名；只读招聘信息栏目；1 req/s。
# 归属：params.match 是该企业在就业网登记的**公司全名**，必须归一后完全相等才入库，
#       模糊匹配会把「迪卡侬…大悦城分公司」错认成「大悦城」，所以刻意不做模糊。
defaults:
  adapter: campus
  recruit_types: [campus]
  rate_limit_rps: 1
  params:
    school: nankai
    max_pages: 50            # 「招聘信息」栏目约 50 页共 1,000 条，翻到底
    list_cache_ttl: 600      # 同校多源共用列表页缓存，避免把站点打成 1,700 次请求
  compliance:
    checked_on: 2026-10-30
    robots: allowed            # career.nankai.edu.cn 无 robots.txt 限制项
    terms: "公开招聘信息栏目（企业投递给学校的岗位信息），无需登录；不碰学生简历/投递接口"
    notes: "聚合渠道 grade C：岗位由学校就业网发布，不等于公司官网直发；1 req/s。"

sources:
"""


def slug(name: str) -> str:
    try:
        table = json.loads((ROOT / "work" / "pinyin_single.json").read_text(encoding="utf-8"))
    except FileNotFoundError:
        table = {}
    out = []
    for ch in name:
        if ch.isascii() and (ch.isalnum() or ch in "-_"):
            out.append(ch.lower())
        else:
            out.append(table.get(ch, ""))
    s = re.sub(r"[^a-z0-9]+", "", "".join(out))
    return s or "x"


def main() -> int:
    lines = [HEADER]
    seen: set[str] = set()
    for company, matches in CURATED.items():
        sid = f"campus-nankai-{slug(company)}"
        if sid in seen:
            raise SystemExit(f"dup id {sid}")
        seen.add(sid)
        yml_list = "[" + ", ".join(f'"{m}"' for m in matches) + "]"
        lines.append(f"  - id: {sid}\n    company: {company}\n    params: {{match: {yml_list}}}\n")
    OUT.write_text("".join(lines), encoding="utf-8")
    print(f"sources={len(CURATED)} -> {OUT}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
