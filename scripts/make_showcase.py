"""Render a candidate workflow from checked-in tool-result excerpts.

Requires Pillow and a CJK font; MP4 export also requires FFmpeg on PATH.
The scenes illustrate a workflow, not a recorded client or measured response time.
Usage: python scripts/make_showcase.py --video-dir .tmp/showcase
"""

from __future__ import annotations

import argparse
import json
import shutil
import subprocess
from functools import lru_cache
from pathlib import Path

from make_assets import BLUE, GREEN, LINE, MUTED, PANEL, WHITE, font
from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parents[1]
ASSETS = ROOT / "docs/assets"
AMBER = "#f0c777"
BACKGROUND = "#0b1220"


@lru_cache(maxsize=48)
def face(size: int, bold: bool = False):
    return font(size, bold)


def lines(draw, text, size, width, bold=False):
    result, current = [], ""
    for char in text:
        if char == "\n" or (current and draw.textlength(current + char, font=face(size, bold)) > width):
            result.append(current)
            current = "" if char == "\n" else char
        else:
            current += char
    return [*result, current] if current else result


def paragraph(draw, xy, text, size, width, color=WHITE, bold=False, spacing=1.5):
    x, y = xy
    for line in lines(draw, text, size, width, bold):
        draw.text((x, y), line, font=face(size, bold), fill=color)
        y += round(size * spacing)
    return y


def card(draw, box, color=LINE):
    draw.rounded_rectangle(box, radius=18, fill=PANEL, outline=color, width=2)


def scene(data, index, reveal, portrait=False):
    w, h = (720, 1280) if portrait else (1120, 630)
    im = Image.new("RGB", (w, h), BACKGROUND)
    d = ImageDraw.Draw(im)
    p = 46 if portrait else 48
    content = w - 2 * p
    d.text((p, 28), "job_radar.", font=face(30, True), fill=WHITE)
    labels = ["从需求开始", "发现真实候选", "核对岗位要求", "查看招聘窗口", "开始你的查询"]
    d.text((w - p - 220, 36), f"0{index + 1} / 05  {labels[index]}", font=face(17), fill=GREEN)
    d.line((p, 83, w - p, 83), fill=LINE, width=1)
    title_size = 43 if portrait else 42
    titles = ["找工作，\n少翻几个招聘网站。", "先选城市，再核条件。", "字段有冲突？\n把证据摊开。", "招聘窗口，\n明确与未知分开。", "把招聘信息，\n接入你的助手。"]
    y = paragraph(d, (p, 116), titles[index], title_size, content, bold=True, spacing=1.35)
    y += 18

    if index == 0:
        y = paragraph(d, (p, y), "中国校招 · 实习 · 社招 · 招聘日历", 24, content, GREEN)
        y += 24
        question = "帮我找苏州或无锡的财务校招，排除上海。2027届明确匹配与届次未知的分开列。"
        question_lines = lines(d, question, 26, content - 48)
        box_h = 42 + len(question_lines) * 39
        card(d, (p, y, w - p, y + box_h), GREEN)
        paragraph(d, (p + 24, y + 18), question, 26, content - 48, spacing=1.5)
        y += box_h + 28
        if portrait:
            for n, text in enumerate(["01  说出城市、方向与排除条件", "02  查看真实候选与缺失字段", "03  阅读来源，确认资格与投递"]):
                d.text((p, y + n * 62), text, font=face(23, n == reveal), fill=GREEN if n <= reveal else MUTED)
        else:
            d.text((p, y), "说出需求   →   查看候选   →   核对来源", font=face(25, True), fill=GREEN)

    elif index == 1:
        y = paragraph(d, (p, y), "苏州 / 无锡 · 财务校招 · 排除含上海的记录", 23, content, GREEN)
        y += 16
        for row in data["search"]["results"][:min(reveal + 1, 2)]:
            height = 132 if portrait else 100
            card(d, (p, y, w - p, y + height))
            title_y = paragraph(d, (p + 22, y + 13), row["title"], 25, content - 44, bold=True, spacing=1.25)
            meta = f'{row["company"]} · {" / ".join(row["cities"])} · 明确2027届'
            paragraph(d, (p + 22, title_y + 7), meta, 20, content - 44, BLUE, spacing=1.25)
            y += height + 14
        if reveal > 0:
            coverage = data["search"]["filter_coverage"]["grad_year"]
            note = f'保留其他条件时：{coverage["known"]}条已标注届次 / {coverage["unknown"]}条未标注。'
            y = paragraph(d, (p, y + 6), note, 20, content, MUTED)
            paragraph(d, (p, y + 5), f'查询共{data["search"]["total"]}个展示分组；此处仅列2个，候选需继续核实。', 18, content, MUTED)

    elif index == 2:
        row = data["qualification"]
        y = paragraph(d, (p, y), f'独立详情案例 · {row["company"]}（北京）', 23, content, BLUE)
        y += 18
        if portrait:
            for label, value, color in [("已存学历字段", "硕士", AMBER), ("JD原文候选要求", "本科及以上学历", GREEN)]:
                card(d, (p, y, w - p, y + 118), color)
                d.text((p + 22, y + 12), label, font=face(19), fill=MUTED)
                d.text((p + 22, y + 47), value, font=face(32, True), fill=color)
                y += 136
        else:
            cw = (content - 22) // 2
            for n, (label, value, color) in enumerate([("已存学历字段", "硕士", AMBER), ("JD原文候选要求", "本科及以上学历", GREEN)]):
                x = p + n * (cw + 22)
                card(d, (x, y, x + cw, y + 108), color)
                d.text((x + 22, y + 12), label, font=face(19), fill=MUTED)
                d.text((x + 22, y + 47), value, font=face(31, True), fill=color)
            y += 126
        if reveal:
            y = paragraph(d, (p, y), "并列保留冲突证据，回到来源核实；不直接判定符合或排除。", 22, content, WHITE)
            paragraph(d, (p, y + 10), f'正文观测：{row["text_observed_at"]}', 18, content, MUTED)

    elif index == 3:
        cal = data["calendar"]
        y = paragraph(d, (p, y), "2026-11-03 回查 · 2027届秋招正式批", 23, content, BLUE)
        y += 20
        numbers = [(cal["window_counts"]["open"], "完整批次日期窗口", GREEN), (cal["window_counts"]["unknown"], "窗口未知，需核实", AMBER)]
        cw = (content - 22) // 2
        for n, (count, label, color) in enumerate(numbers):
            x = p if portrait else p + n * (cw + 22)
            yy = y + n * 160 if portrait else y
            ww = content if portrait else cw
            card(d, (x, yy, x + ww, yy + 138), color)
            d.text((x + 23, yy + 9), str(count), font=face(54, True), fill=color)
            d.text((x + 23, yy + 87), label, font=face(21), fill=WHITE)
        y += 330 if portrait else 155
        if reveal:
            y = paragraph(d, (p, y), f'本次共{cal["returned"]}条候选；日期不全的单独说明。', 22, content)
            paragraph(d, (p, y + 8), "完整日期窗口也不等于当前已确认可投。", 20, content, MUTED)

    else:
        y = paragraph(d, (p, y), "安装工具 → 下载快照 → 连接 MCP / skill", 24, content, GREEN)
        y += 24
        for n, text in enumerate(["说出你的条件，保留每一项排除要求", "查看来源、原文与数据观测时间", "确认后到原始网站投递"]):
            d.text((p, y + n * 52), text, font=face(23, n == reveal), fill=WHITE if n <= reveal else MUTED)
        y += 170
        d.text((p, y), "试用 · 反馈 · 分享   /   欢迎 Star", font=face(26, True), fill=GREEN)
        if portrait:
            y += 78
            qr = data.get("_qr")
            if qr is not None:
                im.paste(qr.resize((190, 190), Image.Resampling.NEAREST), (p, y))
                paragraph(d, (p + 215, y + 30), "GitHub\njob_radar\n开源 · MIT", 24, content - 215, MUTED)
            d.line((p, 862, w - p, 862), fill=LINE, width=1)
            paragraph(d, (p, 900), "校招 / 实习 / 社招 / 招聘日历", 25, content, GREEN, bold=True)
            paragraph(d, (p, 955), "按城市、公司、方向与届次发现机会。\n未知条件单列，投递前回到原站确认。", 23, content, MUTED)

    # Every scene states the origin and limits; no invented host-client footage.
    footer_y = h - (104 if portrait else 66)
    d.line((p, footer_y - 16, w - p, footer_y - 16), fill=LINE, width=1)
    paragraph(d, (p, footer_y), "流程示意 · 真实工具结果节选 · 非客户端录屏", 16, content, MUTED)
    d.text((p, footer_y + 29), "2026-11-02快照 / 不代表实时资格或申请状态", font=face(15), fill=MUTED)
    progress = (index * 3 + reveal + 1) / 15
    d.rectangle((0, h - 5, int(w * progress), h), fill=GREEN)
    return im


def video(frames, durations, directory, portrait):
    ffmpeg = shutil.which("ffmpeg")
    if not ffmpeg:
        raise RuntimeError("MP4 export requires FFmpeg on PATH")
    mode = "portrait" if portrait else "landscape"
    working = directory / mode
    working.mkdir(parents=True, exist_ok=True)
    concat = []
    for i, (im, ms) in enumerate(zip(frames, durations, strict=True)):
        path = working / f"{i:02d}.png"
        im.save(path)
        concat += [f"file '{path.name}'", f"duration {ms / 1000}"]
    concat.append(f"file '{len(frames) - 1:02d}.png'")
    playlist = working / "frames.txt"
    playlist.write_text("\n".join(concat) + "\n", encoding="utf-8")
    destination = directory / f"job-radar-{mode}.mp4"
    size = "1080:1920" if portrait else "1920:1080"
    subprocess.run([
        ffmpeg, "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", str(playlist),
        "-vf", f"scale={size}:flags=lanczos,fps=24,format=yuv420p", "-c:v", "libx264",
        "-crf", "22", "-preset", "medium", "-movflags", "+faststart", "-an",
        "-t", str(sum(durations) / 1000), str(destination),
    ], check=True)
    print(f"{destination}: {destination.stat().st_size:,} bytes", flush=True)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--input", type=Path, default=ASSETS / "candidate-demo-data.json")
    parser.add_argument("--video-dir", type=Path, help="Export landscape and portrait MP4s here")
    args = parser.parse_args()
    data = json.loads(args.input.read_text(encoding="utf-8"))
    assert data["search"]["data_as_of"] == "2026-11-02T14:39:29Z"
    assert all("上海" not in row["cities"] for row in data["search"]["results"])
    assert data["qualification"]["qualification_evidence"]["degree"]["conflict"]
    # QR support is optional and local; no external QR service is used.
    try:
        import qrcode
    except ImportError:
        pass
    else:
        data["_qr"] = qrcode.make(data["repository"]).convert("RGB")
    durations = [1100, 1200, 3700] * 5
    for portrait in (False, True):
        frames = [scene(data, i, reveal, portrait) for i in range(5) for reveal in range(3)]
        if not portrait:
            sampler = Image.new("RGB", (800, 90))
            for n in range(5):
                sampler.paste(frames[n * 3 + 2].resize((160, 90)), (n * 160, 0))
            palette = sampler.quantize(colors=112)
            indexed = [im.quantize(palette=palette, dither=Image.Dither.NONE) for im in frames]
            indexed[0].save(ASSETS / "candidate-demo.gif", save_all=True, append_images=indexed[1:],
                            duration=durations, loop=0, optimize=True, disposal=1)
            frames[-1].save(ASSETS / "candidate-preview.png", optimize=True)
        else:
            frames[-1].save(ASSETS / "candidate-poster.png", optimize=True)
        if args.video_dir:
            args.video_dir.mkdir(parents=True, exist_ok=True)
            video(frames, durations, args.video_dir.resolve(), portrait)


if __name__ == "__main__":
    main()
