"""一键重建入口池：从原始证据一路跑到「可用入口清单」。

为什么要有这个脚本：清理链有 5 个阶段（冲突解析 → 合并 → 错配检测 → 评级 → 导航升级），
每阶段都可能因为规则调整而需要重跑。手工按顺序敲命令容易漏步、也容易把中间产物覆盖成
半成品。这里把顺序固定下来，任何一步失败立刻停。

阶段：
  1. resolve_conflicts.py   careers_confirmed(1848) → careers_final + careers_rejected
  2. merge_entries.py       careers_final + careers_rescued → entry_pool（每公司一条）
  3. detect_mismatch.py     entry_pool 内剔除「标题写着别家名」的错配
  4. grade_entries.py       entry_pool → entry_graded（A 列表页 / B 招聘子站 / C 招聘页 / D 非招聘）
  5. navigate_careers.py    C/D 里「招聘入口藏在二级页」的，同域下一层找列表页，升级为 A
  6. 汇总                   entry_usable = A + B

用法：
    python3 work/rebuild_pool.py
"""

import json
import subprocess
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PY = sys.executable

STEPS = [
    ("冲突解析", "work/resolve_conflicts.py"),
    ("合并定型", "work/merge_entries.py"),
    ("错配检测", "work/detect_mismatch.py"),
    ("入口评级", "work/grade_entries.py"),
    ("导航升级", "work/navigate_careers.py"),
]


def count(p: Path) -> int:
    if not p.exists():
        return 0
    return sum(1 for s in p.read_text(encoding="utf-8").splitlines() if s.strip())


def main() -> int:
    for label, script in STEPS:
        print(f"\n===== {label} ({script}) =====", flush=True)
        # 导航是断点续跑的，重建时必须清空，否则会沿用上一轮（基于旧池）的结论
        if script.endswith("navigate_careers.py"):
            nav = ROOT / "work/navigated.jsonl"
            if nav.exists():
                nav.unlink()
        r = subprocess.run([PY, script], cwd=ROOT, capture_output=True, text=True)
        tail = [ln for ln in (r.stdout or "").strip().splitlines() if ln.strip()][-4:]
        for ln in tail:
            print("  " + ln)
        if r.returncode != 0:
            print("  STDERR:", (r.stderr or "")[-800:])
            return r.returncode

    graded = [json.loads(s) for s in
              (ROOT / "work/entry_graded.jsonl").read_text(encoding="utf-8").splitlines() if s.strip()]

    # 把导航升级结果合并回评级：升级成功的条目，url 换成找到的列表页，grade 提到 A
    nav_p = ROOT / "work/navigated.jsonl"
    upgraded = 0
    if nav_p.exists():
        nav = {}
        for s in nav_p.read_text(encoding="utf-8").splitlines():
            if s.strip():
                d = json.loads(s)
                if d.get("upgrade"):
                    nav[d["company"]] = d["upgrade"]
        for r in graded:
            up = nav.get(r["company"])
            if up and r["grade"] in ("C", "D"):
                r["url"] = up["url"]
                r["grade"] = "A"
                r["grade_why"] = "navigated"
                upgraded += 1

    usable = [r for r in graded if r["grade"] in ("A", "B")]
    out = ROOT / "work/entry_usable.jsonl"
    out.write_text("".join(json.dumps(x, ensure_ascii=False) + "\n" for x in usable), encoding="utf-8")
    # 评级结果也回写，保证 entry_graded 与 usable 一致（下游都读这两个文件）
    (ROOT / "work/entry_graded.jsonl").write_text(
        "".join(json.dumps(x, ensure_ascii=False) + "\n" for x in graded), encoding="utf-8")

    print("\n===== 汇总 =====")
    print("  graded:", len(graded), dict(Counter(r["grade"] for r in graded)))
    print("  导航升级:", upgraded)
    print("  usable(A+B):", len(usable))
    return 0


if __name__ == "__main__":
    sys.exit(main())
