"""按证据筛选 yunjiuye 源：只保留「已提交的 94 条」∪「本轮快速冒烟有产出」的源。"""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
YAML = ROOT / "sources" / "yunjiuye.yaml"
KEEP = ROOT / "work" / "_keep_ids.txt"

keep = {line.strip() for line in KEEP.read_text(encoding="utf-8").splitlines() if line.strip()}
text = YAML.read_text(encoding="utf-8")
head, _, body = text.partition("sources:\n")

entries: list[list[str]] = []
cur: list[str] = []
for line in body.splitlines():
    if line.startswith("  #"):
        entries.append(["COMMENT", line])
        continue
    if line.startswith("  - id: "):
        if cur:
            entries.append(["ENTRY", "\n".join(cur)])
        cur = [line]
    elif cur and line.startswith("    "):
        cur.append(line)
    else:
        entries.append(["OTHER", line])
if cur:
    entries.append(["ENTRY", "\n".join(cur)])

out = [head + "sources:\n"]
kept = 0
for kind, chunk in entries:
    if kind != "ENTRY":
        out.append(chunk + "\n")
        continue
    sid = chunk.split("- id: ")[1].split("\n")[0].strip()
    if sid in keep:
        out.append(chunk + "\n")
        kept += 1
YAML.write_text("".join(out), encoding="utf-8")
print("kept", kept, "of", len([1 for k, _ in entries if k == "ENTRY"]))
