"""用真实网络录制某个源的 fixtures（每页一个响应），写到 tests/fixtures/<adapter_id>/。

用法：uv run python scripts/record_fixtures.py <source_id> [--max-pages 2]
- 只发少量请求（max_pages 限量），遵守 source 的限速。
- 录完必须人工/Claude 检查：不含 cookie/token/个人信息；体积 < 300KB；必要时裁剪 items。
- 运行后同目录会写入 source.yaml（max_pages 已固定），供契约测试使用。
- `--truncate N --anchor 片段`：只保留 anchor **最后一次出现处**往后的内容（拿不到 N 字节就用全部）。
  直接截前 N 字节是错的：详情页的 JD 正文在 60~90KB 处，截头就没正文了（2026-10-26 实测）。
  为什么取最后一次出现：第一次出现在 `<style>` / 内联 JSON 配置里（`"JobDetailsDate":0` 的兄弟键），
  真正的卡片在页面靠后位置。取 `rfind` 才能稳定落在正文区。
  截断后必须重跑契约测试确认仍然通过。
"""

import argparse
import json
import re
import sys
from pathlib import Path

import yaml

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))

from jobradar.adapters.base import load_all, make_client  # noqa: E402
from jobradar.adapters.recording import RecordingTransport  # noqa: E402
from jobradar.compliance import RobotsPolicy  # noqa: E402
from jobradar.sources import load_sources  # noqa: E402


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("source_id")
    ap.add_argument("--max-pages", type=int, default=2)
    ap.add_argument("--page-size", type=int, default=20, help="适配器支持 params.page_size 时生效")
    ap.add_argument("--multi-source", action="store_true",
                    help="该适配器服务多家公司时加此参数，fixtures 写到 tests/fixtures/<adapter>_<source>/")
    ap.add_argument("--truncate", type=int, default=0,
                    help="录完把响应截到 N 字节（0=不截）。未命中 --anchor 的文件不截")
    ap.add_argument("--anchor", default="",
                    help="截断以这个子串为中心（如 ats-description）。空=从文件头截")
    ap.add_argument("--span", default="",
                    help='列表页专用："起,止"。只保留「起」第一次出现处到「止」第一次出现处之后的片段。'
                         '例 --span \'id="search-results",</section>\' 就只留搜索结果整段，'
                         '把页面首尾的 150KB 主题样式/导航全丢掉。比 --anchor/--truncate 都更准')
    ap.add_argument("--keep-tail", action="store_true",
                    help="配合 --anchor-first：不切 <style> 之后的尾巴。详情页必传（日期/截止日都在正文之后）")
    ap.add_argument("--span-tail", type=int, default=0,
                    help="配合 --span 使用：span 未命中的响应（即详情页）只保留前 N 字节。"
                         "详情页的正文在 80~130KB 处，N 要够大；先跑一次看 --span 让它多长再定")
    ap.add_argument("--anchor-first", default="",
                    help="给列表页用：从**第一次**出现该子串处开始截（如 id=\"position-list\"）。"
                         "列表页的卡片在正文中间、后面还有 50KB <style>，用 --anchor 会截出更大的文件")
    ap.add_argument("--truncate-after", type=int, default=1,
                    help="只有第 N 个及以后的响应才截（默认 1=全截；列表页是第 1 个响应时传 2）")
    ap.add_argument("--keep-details", type=int, default=None, dest="keep_details",
                    help="只保留前 K 个详情请求及其响应（删掉后面没被测试直接断言的那些）。"
                         "0/不传=全留。列表页、总数页、分页 POST 永远保留。"
                         "判定靠 source.params.url_filter（该源详情 URL 的正则），不猜。")
    args = ap.parse_args()

    source = next((s for s in load_sources(ROOT / "sources") if s.id == args.source_id), None)
    if source is None:
        print(f"source {args.source_id} not found in sources/")
        return 1
    source.params = {**source.params, "max_pages": args.max_pages, "page_size": args.page_size}
    # 一个适配器可以服务多家公司（如 feishu_atsx 服务蔚来/小鹏/Momenta，各自域名不同）。
    # 这时 fixtures 必须按 **source** 分目录，否则后录的会覆盖先录的、契约测试也回放不到自己的域名。
    # 约定：只服务一家公司的适配器仍用 <adapter_id>/（历史 fixtures 路径不变）。
    multi = args.multi_source
    out = ROOT / "tests" / "fixtures" / (f"{source.adapter}_{source.id}" if multi else source.adapter)
    cls = load_all(include_drafts=True)[source.adapter]
    transport = RecordingTransport(out, secret_patterns=cls.secret_patterns)
    adapter = cls(source, make_client(transport, policy=RobotsPolicy()))
    jobs = list(adapter.fetch_all())
    (out / "source.yaml").write_text(
        yaml.safe_dump(source.model_dump(mode="json"), allow_unicode=True, sort_keys=False), encoding="utf-8"
    )
    print(f"recorded {len(transport.entries)} responses, {len(jobs)} jobs -> {out}")
    if args.keep_details is not None:
        # 详情 URL 的正则由源自己声明（params.url_filter）。没有它就不知道哪些响应是详情，
        # 只能靠「不是第一个 URL」这种启发式——2026-10-26 试过，会把 positionTotal、第 2 页 index
        # 全当详情删掉，回放直接 UnmatchedRequest。
        pattern = re.compile((source.params or {}).get("url_filter") or r"$^")
        kept: list[dict] = []
        details = 0
        for e in transport.entries:
            if pattern.search(e["url"]):
                details += 1
                if details > args.keep_details:
                    (out / e["file"]).unlink(missing_ok=True)
                    continue
            kept.append(e)
        if not details:
            print("--keep-details 未生效：source.yaml 里没有 params.url_filter")
        transport.entries = kept
        (out / "manifest.json").write_text(
            json.dumps(kept, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")
        print(f"kept {len(kept)} entries ({min(details, args.keep_details)} of {details} details)")

    # `--span` 单独给也要生效（它自带截断语义，不需要再传 --truncate）
    if args.truncate or args.span:
        saved = 0
        skipped = 0
        for i, e in enumerate(transport.entries, 1):
            if i < args.truncate_after:
                continue
            f = out / e["file"]
            raw = f.read_bytes()
            # 注意这里是 `and`：--span 的文件本来就可能比 --truncate 小，但依然要按 span 切。
            start = 0
            if args.span:
                a, _, b = args.span.partition(",")
                # 别用 `i` 做切片下标：外层 `for i, e in enumerate(...)` 的页码变量会被就地覆盖，
                # 之后 `args.truncate_after` 判断就全错（2026-10-26 踩过）。
                i0 = raw.find(a.encode("utf-8"))
                j = raw.find(b.encode("utf-8"), i0) if i0 >= 0 else -1
                if i0 >= 0 and j >= 0:
                    f.write_bytes(raw[i0:j + len(b)])
                    saved += len(raw) - (j + len(b) - i0)
                    continue
                # span 没命中（详情页没有列表容器）是**正常情况**，继续往下走 anchor 分支
            if args.anchor_first:
                pos = raw.find(args.anchor_first.encode("utf-8"))
                if pos < 0:
                    skipped += 1
                    continue
                start = max(0, pos - 1024)
            elif args.anchor:
                pos = raw.rfind(args.anchor.encode("utf-8"))
                if pos < 0:
                    skipped += 1
                    continue
                # 往前留 1KB，让正则能吃到锚点前紧邻的标签开头
                start = max(0, pos - 1024)
            elif args.span and getattr(args, "span_tail", 0):
                # 详情页：正文之后的「可能感兴趣的职位 / 页脚」对断言没用，按字节砍尾。
                # 砍多少由调用方用 --span-tail 明确给出（详情页体积差异大，不能一刀切）。
                start = 0
            elif not args.span:
                skipped += 1
                continue
            cut = raw[start:]
            if args.span and args.span_tail:
                cut = cut[:args.span_tail]
            if args.anchor_first and start > 0 and not args.keep_tail:
                # 尾巴（`<style>` 主题样式 / 页脚）对解析没用，切掉能再省一半。
                # ⚠ 列表页可以切（卡片与分页控件都在 <style> 之前），
                #   **详情页不行** —— 发布时间 `span.job-date` 在正文之前、但页脚与
                #   「可能感兴趣的职位」在正文之后，一刀切会把仍在 <style> 之后的内容也砍掉。
                #   所以详情页要传 --keep-tail（2026-10-26 实测：不传就丢了 3 个日期字段）。
                tail = cut.find(b"<style", len(args.anchor_first) + 1024)
                if tail > 0:
                    cut = cut[:tail]
            f.write_bytes(cut)
            saved += len(raw) - len(cut)
        msg = f"trimmed entries[{args.truncate_after}:], saved {saved // 1024}KB"
        if skipped:
            msg += f", skipped {skipped} (anchor not found)"
        print(msg)

    total = sum(x.stat().st_size for x in out.rglob("*") if x.is_file())
    print(f"fixtures {out.name}: {total / 1024:.0f}KB" + ("  ⚠ 超过契约上限 300KB" if total >= 300_000 else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
