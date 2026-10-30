"""裁剪录制的页面型 fixtures：只保留正文那一段。

录制下来的详情页整页 HTML 约 72KB，链接/脚本占了绝大多数。适配器解析只用到
「职位详情」之后的纯文本，所以把每份 .txt 截成「首个 职位详情 前 2KB ~ 之后 12KB」，
既保证字段齐全，又把体积压到契约上限以内。
"""
from __future__ import annotations

import json
from pathlib import Path

FX = Path("tests/fixtures/campus_saas_campus-saas-shanghaijiangong")
KEEP_BEFORE = 2048
KEEP_AFTER = 14000

manifest = json.loads((FX / "manifest.json").read_text(encoding="utf-8"))
print("manifest keys:", list(manifest)[:6])
for p in sorted(FX.glob("*.txt")):
    raw = p.read_text(encoding="utf-8", errors="replace")
    i = raw.find("职位详情")
    if i < 0:
        print(f"{p.name}: 无「职位详情」，跳过（{len(raw)}B）")
        continue
    start = max(0, i - KEEP_BEFORE)
    out = raw[start : i + KEEP_AFTER]
    p.write_text(out, encoding="utf-8")
    print(f"{p.name}: {len(raw)} -> {len(out)}")
