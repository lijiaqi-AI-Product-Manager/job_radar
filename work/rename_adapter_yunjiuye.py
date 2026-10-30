"""把适配器 id 从 campus_saas 重命名为 yunjiuye（云就业）。

原因：契约测试用 `<adapter>_*` 前缀匹配 fixtures 目录，`campus_saas_*` 会被
`campus` 适配器一并认领，导致 campus 跑到 yunjiuye 的 fixtures 上报错。
改名后前缀不再冲突，也跟平台中文名对得上。
"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def rewrite(path: Path, pairs: list[tuple[str, str]]) -> None:
    t = path.read_text(encoding="utf-8")
    before = t
    for old, new in pairs:
        t = t.replace(old, new)
    if t != before:
        path.write_text(t, encoding="utf-8")
        print("rewrote", path.relative_to(ROOT))


# 1) 适配器模块
src = ROOT / "src" / "jobradar" / "adapters" / "campus_saas.py"
dst = ROOT / "src" / "jobradar" / "adapters" / "yunjiuye.py"
if src.exists():
    rewrite(
        src,
        [
            ('id = "campus_saas"', 'id = "yunjiuye"'),
            ("CampusSaasAdapter", "YunjiuyeAdapter"),
            ('"""「云就业」SaaS 高校就业网适配器（聚合口径 grade C）。',
             '"""「云就业」SaaS 高校就业网适配器（id: yunjiuye，聚合口径 grade C）。'),
        ],
    )
    src.rename(dst)
    print("renamed module ->", dst.name)

# 2) 源表
ys = ROOT / "sources" / "campus_saas.yaml"
if ys.exists():
    rewrite(ys, [("adapter: campus_saas", "adapter: yunjiuye"), ("campus-saas-", "yunjiuye-")])
    ys.rename(ROOT / "sources" / "yunjiuye.yaml")
    print("renamed sources -> sources/yunjiuye.yaml")

# 3) 测试
tp = ROOT / "tests" / "adapters" / "test_campus_saas.py"
if tp.exists():
    rewrite(
        tp,
        [
            ("jobradar.adapters.campus_saas", "jobradar.adapters.yunjiuye"),
            ("CampusSaasAdapter", "YunjiuyeAdapter"),
            ("campus_saas", "yunjiuye"),
            ("campus-saas-", "yunjiuye-"),
        ],
    )
    tp.rename(ROOT / "tests" / "adapters" / "test_yunjiuye.py")
    print("renamed test -> test_yunjiuye.py")

# 4) fixtures 目录 + source.yaml
fx = ROOT / "tests" / "fixtures" / "campus_saas_campus-saas-shanghaijiangong"
if fx.exists():
    sy = fx / "source.yaml"
    rewrite(sy, [("campus_saas", "yunjiuye"), ("campus-saas-", "yunjiuye-")])
    fx.rename(ROOT / "tests" / "fixtures" / "yunjiuye_yunjiuye-shanghaijiangong")
    print("renamed fixtures dir")

# 5) 覆盖率口径
cr = ROOT / "scripts" / "coverage_report.py"
rewrite(cr, [('"campus_saas"', '"yunjiuye"')])

# 6) work 脚本
for name in ("gen_saas_yaml.py", "crawl_saas_smoke.py"):
    p = ROOT / "work" / name
    if p.exists():
        rewrite(p, [("campus_saas", "yunjiuye"), ("campus-saas-", "yunjiuye-")])

# 7) 残留检查
left = []
for p in list((ROOT / "src").rglob("*.py")) + list((ROOT / "tests").rglob("*.py")) + list((ROOT / "scripts").rglob("*.py")):
    if "campus_saas" in p.read_text(encoding="utf-8"):
        left.append(str(p.relative_to(ROOT)))
print("residual campus_saas:", left or "none")
