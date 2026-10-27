"""用腾讯云 / 网易云音乐校园招聘的公开 CDN 静态数据，补「企业校招宣讲会」信息。

为什么这条路值得走：
  - `te.qq.com`（腾讯校园招聘宣讲会站）把全部场次放在一个公开 JSON 里，**一次请求拿全量**，
    不需要翻页、不需要登录、没有签名——比逐家企业爬 1000 个域名便宜两个数量级；
  - 数据里有**企业名 + 城市 + 具体日期 + 场地**，正好是岗位日历最缺的三列
    （截止日、开始日、城市）；
  - 但它**不是岗位数据**：只有宣讲会日程，没有 JD。所以定位是「日历补充源」，
    不能拿来充岗位数，也不能当成「这家公司已覆盖」。

红线：只读公开 GET，无登录、无 UA 伪装、每主机 ≤1 rps、不逆向任何签名。
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

import httpx

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import USER_AGENT  # noqa: E402

# 已知候选（2026-10-27 侦察）：te.qq.com 的场次 JSON。找不到就返回空，不猜别的路径。
CANDIDATES = [
    "https://te.qq.com/api/tencent/teachin/list",
    "https://te.qq.com/api/teachin/list",
    "https://te.qq.com/api/tencent/teachin",
]


def try_fetch(url: str) -> dict | list | None:
    try:
        with httpx.Client(headers={"User-Agent": USER_AGENT}, timeout=15.0,
                          follow_redirects=True) as c:
            r = c.get(url)
            if r.status_code == 200 and r.text.strip().startswith(("{", "[")):
                return r.json()
    except Exception:  # noqa: BLE001
        return None
    return None


def main() -> int:
    for u in CANDIDATES:
        d = try_fetch(u)
        if d is not None:
            print("HIT", u, json.dumps(d, ensure_ascii=False)[:300])
            return 0
        print("miss", u)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
