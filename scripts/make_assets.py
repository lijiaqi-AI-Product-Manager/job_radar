"""生成 README 演示 GIF（中/英）与 GitHub social preview。

用 Pillow 手绘终端动画：不需要录屏、可重复生成、体积可控。
运行（需要 Pillow）：
  python scripts/make_assets.py
产物：docs/assets/demo-zh.gif、demo-en.gif、social-preview.png
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets"
OUT.mkdir(parents=True, exist_ok=True)

W, H = 900, 506
BAR = 34
FPS = 8
SECONDS = 15
BG = (13, 17, 23)
BAR_BG = (22, 27, 34)
FG = (201, 209, 217)
DIM = (139, 148, 153)
GREEN = (63, 185, 80)
BLUE = (88, 166, 255)
YELLOW = (210, 168, 255)
WHITE = (240, 246, 252)

CJK = r"C:\Windows\Fonts\msyh.ttc"
MONO = r"C:\Windows\Fonts\consola.ttf"
MONO_B = r"C:\Windows\Fonts\consolab.ttf"


def font(path: str, size: int):
    return ImageFont.truetype(path, size)


# ---------- 场景脚本：(相对时间秒, 行内容, 颜色, 是否逐字打出) ----------

ZH = [
    (0.0, "jobradar demo", DIM, False),
    (0.4, "~ $ jobradar update", WHITE, True),
    (1.4, "  -> data-latest   jobs 20.4 MB + jd_text 34.9 MB", DIM, False),
    (2.2, "  √ 279 个数据源 · 88,608 个在招岗位 · JD 正文 99.8%", GREEN, False),
    (3.6, "  √ 数据截至 2026-10-24 03:17（每日自动更新）", GREEN, False),
    (4.6, "~ $ jobradar search --company 腾讯 --city 深圳 --limit 3", WHITE, True),
    (6.0, "腾讯 │ 后台开发工程师 │ 深圳 │ 校招 │ 2027届 │ join.qq.com", FG, False),
    (6.6, "腾讯 │ 算法工程师     │ 深圳 │ 校招 │ 2027届 │ join.qq.com", FG, False),
    (7.2, "腾讯 │ 产品经理       │ 深圳 │ 实习 │ 2028届 │ join.qq.com", FG, False),
    (8.4, "~ $ jobradar calendar --group 阿里巴巴 --table", WHITE, True),
    (9.6, "阿里巴巴 · 2027届 · 秋招", BLUE, False),
    (10.1, "  方向：技术类（智能算法、Agent Infra 工程师…）", FG, False),
    (10.6, "  网申：来源未写（不代表已截止）", FG, False),
    (11.1, "  城市：北京、上海、杭州、深圳、成都", FG, False),
    (11.6, "  入口：campus-talent.alibaba.com/campus/position", FG, False),
    (12.8, "√ 零服务器 · 纯本地 SQLite · CLI / MCP / Skill", GREEN, False),
    (13.6, "github.com/lijiaqimun-coder/job_radar", YELLOW, False),
]

EN = [
    (0.0, "jobradar demo", DIM, False),
    (0.4, "~ $ jobradar update", WHITE, True),
    (1.4, "  -> data-latest   jobs 20.4 MB + jd_text 34.9 MB", DIM, False),
    (2.2, "  √ 279 sources · 88,608 open jobs · JD text 99.8%", GREEN, False),
    (3.6, "  √ data as of 2026-10-24 03:17 UTC+8 (daily refresh)", GREEN, False),
    (4.6, "~ $ jobradar search --company 腾讯 --city 深圳 --limit 3", WHITE, True),
    (6.0, "Tencent │ Backend Engineer  │ Shenzhen │ campus │ 2027 │ join.qq.com", FG, False),
    (6.6, "Tencent │ ML Engineer       │ Shenzhen │ campus │ 2027 │ join.qq.com", FG, False),
    (7.2, "Tencent │ Product Manager   │ Shenzhen │ intern │ 2028 │ join.qq.com", FG, False),
    (8.4, "~ $ jobradar calendar --group 阿里巴巴 --table", WHITE, True),
    (9.6, "Alibaba · Class of 2027 · Autumn campus", BLUE, False),
    (10.1, "  tracks: engineering (algorithms, Agent Infra…)", FG, False),
    (10.6, "  window: not stated by source (open-ended?)", FG, False),
    (11.1, "  cities: Beijing, Shanghai, Hangzhou, Shenzhen", FG, False),
    (11.6, "  apply : campus-talent.alibaba.com/campus/position", FG, False),
    (12.8, "√ no server · local SQLite · CLI / MCP / Skill", GREEN, False),
    (13.6, "github.com/lijiaqimun-coder/job_radar", YELLOW, False),
]


def rounded(draw, box, r, fill):
    draw.rounded_rectangle(box, radius=r, fill=fill)


def render_frames(script, mono, mono_bold):
    frames = []
    total = FPS * SECONDS
    for i in range(total):
        t = i / FPS
        img = Image.new("RGB", (W, H), BG)
        d = ImageDraw.Draw(img)
        # 标题栏
        d.rectangle([0, 0, W, BAR], fill=BAR_BG)
        for j, color in enumerate(((255, 95, 86), (255, 189, 46), (39, 201, 63))):
            d.ellipse([16 + j * 22, 12, 28 + j * 22, 24], fill=color)
        d.text((96, 9), "jobradar — zsh", font=mono, fill=DIM)
        y = BAR + 18
        for t0, text, color, typed in script:
            if t < t0:
                continue
            shown = text
            if typed:
                # 0.7 秒内逐字出现
                ratio = min(1.0, (t - t0) / 0.7)
                shown = text[: max(1, int(len(text) * ratio))]
            f = mono_bold if text.startswith("~ $") else mono
            is_cjk = any("\u4e00" <= ch <= "\u9fff" for ch in shown)
            if is_cjk and mono is not None:
                f = ImageFont.truetype(CJK, 19)
            d.text((28, y), shown, font=f, fill=color)
            if typed and shown != text:  # 光标
                w = d.textlength(shown, font=f)
                d.rectangle([28 + w + 2, y + 2, 28 + w + 9, y + 21], fill=FG)
            y += 26 if not is_cjk else 28
        # 进度条（前 0.8 秒）
        frames.append(img)
    return frames


def save_gif(frames, path: Path, colors: int = 64):
    pal = [f.quantize(colors=colors, method=Image.Quantize.MEDIANCUT) for f in frames]
    pal[0].save(path, save_all=True, append_images=pal[1:], duration=int(1000 / FPS),
                loop=0, optimize=True, disposal=2)
    print(f"{path.name}: {path.stat().st_size / 1e6:.2f} MB  {len(frames)} frames")


def social_preview(path: Path):
    w, h = 1280, 640
    img = Image.new("RGB", (w, h), BG)
    # 背景光斑：只放在右上与右下，避免压住左侧文字
    for cx, cy, r, col in ((1180, 40, 360, (22, 40, 60)), (1290, 700, 280, (24, 22, 46))):
        layer = Image.new("RGB", (w, h), BG)
        ImageDraw.Draw(layer).ellipse([cx - r, cy - r, cx + r, cy + r], fill=col)
        img = Image.blend(img, layer, 0.5)
    d = ImageDraw.Draw(img)
    title = font(r"C:\Windows\Fonts\msyhbd.ttc", 86)
    sub = font(CJK, 33)
    small = font(CJK, 25)
    stat_f = font(r"C:\Windows\Fonts\consolab.ttf", 44)
    label = font(CJK, 22)
    d.text((80, 58), "job_radar", font=title, fill=WHITE)
    d.text((80, 224), "每日自动更新的中国校招 / 实习 / 社招岗位数据集", font=sub, fill=(206, 216, 230))
    d.text((80, 280), "零服务器 · 纯本地 SQLite · CLI / MCP / Skill 给 AI agent 直接查", font=small, fill=DIM)
    stats = [("279", "数据源"), ("88.6k", "在招岗位"), ("494/500", "公司覆盖"), ("99.8%", "JD 正文")]
    x = 80
    for i, (num, name) in enumerate(stats):
        d.text((x, 372), num, font=stat_f, fill=BLUE if i % 2 == 0 else GREEN)
        d.text((x, 434), name, font=label, fill=DIM)
        x += 290
    d.line([80, 528, 1200, 528], fill=(48, 54, 61), width=2)
    d.text((80, 554), "github.com/lijiaqimun-coder/job_radar", font=small, fill=(180, 190, 205))
    d.text((905, 554), "MIT · daily release", font=small, fill=DIM)
    img.save(path, "PNG", optimize=True)
    print(f"{path.name}: {path.stat().st_size / 1e3:.0f} KB")


def main():
    try:
        mono = ImageFont.truetype(MONO, 19)
        mono_b = ImageFont.truetype(MONO_B, 19)
    except OSError:
        print("no fonts", file=sys.stderr)
        return 1
    save_gif(render_frames(ZH, mono, mono_b), OUT / "demo-zh.gif")
    save_gif(render_frames(EN, mono, mono_b), OUT / "demo-en.gif")
    social_preview(OUT / "social-preview.png")
    return 0


if __name__ == "__main__":
    sys.exit(main())
