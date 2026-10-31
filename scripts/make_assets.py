"""Render repository artwork from checked-in, real CLI result excerpts.

Requires Pillow: python scripts/make_assets.py
Set JOBRADAR_FONT / JOBRADAR_FONT_BOLD to override the CJK fonts.
The animation presents excerpts, without simulating live capture or network speed.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from urllib.parse import urlsplit
from xml.sax.saxutils import escape

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "docs" / "assets"
W, H = 1120, 660
BG, PANEL, LINE = "#0b1220", "#111d30", "#26354a"
WHITE, MUTED, GREEN, BLUE = "#edf4fc", "#94a8bf", "#58e0b3", "#7bb7ff"


def font(size: int, bold: bool = False):
    override = os.environ.get("JOBRADAR_FONT_BOLD" if bold else "JOBRADAR_FONT")
    candidates = [override] if override else []
    candidates += [
        "C:/Windows/Fonts/msyhbd.ttc" if bold else "C:/Windows/Fonts/msyh.ttc",
        "/usr/share/fonts/opentype/noto/NotoSansCJK-Bold.ttc" if bold
        else "/usr/share/fonts/opentype/noto/NotoSansCJK-Regular.ttc",
    ]
    for candidate in candidates:
        if candidate and Path(candidate).exists():
            return ImageFont.truetype(candidate, size)
    raise RuntimeError("Set JOBRADAR_FONT and JOBRADAR_FONT_BOLD to CJK font files")


def fitted(draw, value: str, face, width: int) -> str:
    if draw.textlength(value, font=face) <= width:
        return value
    while value and draw.textlength(value + "…", font=face) > width:
        value = value[:-1]
    return value + "…"


def wrap(draw, text: str, face, width: int) -> list[str]:
    lines, current = [], ""
    for word in text.split(" "):
        proposed = f"{current} {word}".strip()
        if current and draw.textlength(proposed, font=face) > width:
            lines.append(current)
            current = word
        else:
            current = proposed
    return [*lines, current]


def terminal(scene: dict, index: int, language: str, typed: float, shown: int):
    en = language == "en"
    im = Image.new("RGB", (W, H), BG)
    d = ImageDraw.Draw(im)
    d.rounded_rectangle((16, 16, W - 16, H - 16), radius=20, fill=PANEL, outline=LINE, width=2)
    for n, color in enumerate(("#ff7b72", "#e9c46a", GREEN)):
        d.ellipse((40 + n * 24, 40, 52 + n * 24, 52), fill=color)
    d.text((128, 31), "job_radar / local SQLite", font=font(20), fill=MUTED)
    label = ["FILTER BY COMPANY", "SEARCH TITLES + JD", "RECRUITMENT CALENDAR"][index]
    d.text((W - 360, 35), label, font=font(15, True), fill=GREEN)
    d.line((40, 78, W - 40, 78), fill=LINE, width=1)
    command = scene["command"]
    command = command[:int(len(command) * typed)]
    lines = wrap(d, command, font(22), W - 145)
    d.text((42, 105), "$", font=font(24, True), fill=GREEN)
    for n, line in enumerate(lines):
        d.text((77, 105 + n * 33), line, font=font(22), fill=WHITE)
    d.text((44, 186), "RESULT EXCERPT" if en else "真实查询结果 · 节选", font=font(17), fill=MUTED)
    if index < 2:
        for n, row in enumerate(scene["results"][:shown]):
            y = 225 + n * 102
            d.rounded_rectangle((40, y, W - 40, y + 90), radius=12, fill="#17263b")
            d.text((58, y + 10), fitted(d, row["title"], font(24, True), W - 120),
                   font=font(24, True), fill=WHITE)
            cities = " / ".join(row.get("cities") or [])
            meta = f'{row["company"]}  ·  {cities}  ·  {row.get("grad_year") or "—"}'
            d.text((58, y + 51), fitted(d, meta, font(18), W - 120), font=font(18), fill=BLUE)
    elif shown:
        row = scene["results"][0]
        d.rounded_rectangle((40, 225, W - 40, 535), radius=12, fill="#17263b")
        d.text((62, 245), f'{row["group_name"]}  /  {row["grad_year"]}  /  {row["project_type"]}',
               font=font(30, True), fill=WHITE)
        fields = [
            ("Apply" if en else "网申时间", f'{row["apply_start"]} → {row["apply_end"]}'),
            ("Cities" if en else "招聘城市", " / ".join(row["cities"])),
            ("Tracks" if en else "招聘方向", " / ".join(t["direction"] for t in row["tracks"])),
            ("Source" if en else "原始来源", urlsplit(row["apply_url"]).netloc),
        ]
        for n, (key, value) in enumerate(fields):
            y = 315 + n * 45
            d.text((62, y), key, font=font(19), fill=MUTED)
            d.text((205, y), fitted(d, value, font(20), W - 270), font=font(20), fill=BLUE)
    footer = ("Real snapshot · result excerpts · source text preserved" if en
              else "真实快照 · 结果节选 · 保留来源原文")
    d.text((44, 562), footer, font=font(17), fill=MUTED)
    d.text((44, 595), f'data_as_of: {scene["data_as_of"]}', font=font(17), fill=MUTED)
    d.text((W - 294, 595), "CLI  /  MCP  /  SQLite", font=font(17, True), fill=GREEN)
    for n in range(3):
        d.rounded_rectangle((W - 108 + 22 * n, 563, W - 94 + 22 * n, 568), radius=2,
                            fill=GREEN if index == n else LINE)
    return im


def animation(data: dict, language: str):
    frames, durations = [], []
    for index, scene in enumerate(data["scenes"]):
        for step in range(1, 9):
            frames.append(terminal(scene, index, language, step / 8, 0))
            durations.append(90)
        for shown in range(1, len(scene["results"]) + 1):
            frames.append(terminal(scene, index, language, 1, shown))
            durations.append(350)
        durations[-1] = 2900
    palette = frames[0].quantize(colors=96)
    indexed = [f.quantize(palette=palette, dither=Image.Dither.NONE) for f in frames]
    destination = OUT / f"demo-{language}.gif"
    indexed[0].save(destination, save_all=True, append_images=indexed[1:], duration=durations,
                    loop=0, optimize=True, disposal=1)
    return frames[-1]


def hero(language: str):
    en = language == "en"
    heading = "Find your next opportunity. Keep the data." if en else "把招聘信息，变成你的本地数据库。"
    subtitle = ("China jobs & recruitment calendars. Search locally. Follow the source." if en
                else "中国校招 · 实习 · 社招 · 招聘日历    /    本地查询，直达来源")
    heading, subtitle = escape(heading), escape(subtitle)
    svg = f'''<svg xmlns="http://www.w3.org/2000/svg" width="1600" height="430" viewBox="0 0 1600 430" role="img" aria-label="job_radar">
<defs><linearGradient id="bg" x2="1" y2="1"><stop stop-color="#0b1220"/><stop offset="1" stop-color="#142e40"/></linearGradient>
<radialGradient id="glow"><stop stop-color="#58e0b3" stop-opacity=".18"/><stop offset="1" stop-color="#58e0b3" stop-opacity="0"/></radialGradient></defs>
<rect width="1600" height="430" rx="24" fill="url(#bg)"/>
<circle cx="1400" cy="206" r="255" fill="url(#glow)"/>
<g fill="none" stroke="#58e0b3" stroke-opacity=".18"><circle cx="1400" cy="206" r="160"/><circle cx="1400" cy="206" r="110"/><circle cx="1400" cy="206" r="60"/><path d="M1205 206h390M1400 11v390"/></g>
<path d="M1400 206l113-113a160 160 0 0 1 47 113Z" fill="#58e0b3" opacity=".10"/>
<g fill="#58e0b3"><circle cx="1450" cy="140" r="7"/><circle cx="1305" cy="245" r="5"/><circle cx="1485" cy="278" r="5"/></g>
<g font-family="Segoe UI,Microsoft YaHei,Noto Sans,sans-serif">
<text x="70" y="100" fill="#58e0b3" font-size="18" letter-spacing="5">OPEN RECRUITMENT DATA</text>
<text x="66" y="196" fill="#edf4fc" font-weight="750" font-size="84">job_radar<tspan fill="#58e0b3">.</tspan></text>
<text x="70" y="266" fill="#edf4fc" font-size="{35 if en else 40}" font-weight="600">{heading}</text>
<text x="70" y="311" fill="#a3b6cc" font-size="22">{subtitle}</text>
<g font-size="16" fill="#bcecdc"><rect x="70" y="350" width="88" height="34" rx="17" fill="#1c3940"/><text x="96" y="373">CLI</text>
<rect x="170" y="350" width="96" height="34" rx="17" fill="#1c3940"/><text x="196" y="373">MCP</text>
<rect x="278" y="350" width="110" height="34" rx="17" fill="#1c3940"/><text x="300" y="373">SQLite</text>
<rect x="400" y="350" width="158" height="34" rx="17" fill="#1c3940"/><text x="421" y="373">Daily snapshots</text></g></g></svg>'''
    (OUT / ("hero-en.svg" if en else "hero.svg")).write_text(svg, encoding="utf-8")


def social_preview():
    im = Image.new("RGB", (1280, 640), BG)
    d = ImageDraw.Draw(im)
    for radius in (210, 150, 90):
        d.ellipse((1110 - radius, 200 - radius, 1110 + radius, 200 + radius), outline=LINE, width=2)
    d.line((900, 200, 1280, 200), fill=LINE, width=2)
    d.line((1110, 0, 1110, 420), fill=LINE, width=2)
    d.ellipse((1168, 114, 1182, 128), fill=GREEN)
    d.text((72, 60), "OPEN RECRUITMENT DATA", font=font(22, True), fill=GREEN)
    d.text((66, 126), "job_radar.", font=font(92, True), fill=WHITE)
    d.text((72, 278), "把招聘信息，变成你的本地数据库。", font=font(42, True), fill=WHITE)
    d.text((72, 350), "校招 / 实习 / 社招 / 招聘日历", font=font(28), fill=MUTED)
    d.text((72, 431), "CLI     MCP     SQLite     Daily snapshots", font=font(27, True), fill=GREEN)
    d.line((72, 508, 1208, 508), fill=LINE, width=2)
    d.text((72, 545), "Search locally. Follow the source.", font=font(25), fill=MUTED)
    d.text((1005, 545), "MIT / Python", font=font(23), fill=MUTED)
    im.save(OUT / "social-preview.png", optimize=True)


def main():
    data = json.loads((OUT / "demo-data.json").read_text(encoding="utf-8"))
    for language in ("zh", "en"):
        preview = animation(data, language)
        hero(language)
        if language == "zh":
            (ROOT / ".tmp").mkdir(exist_ok=True)
            preview.save(ROOT / ".tmp" / "readme-demo-preview.png")
    social_preview()
    for path in sorted(OUT.iterdir()):
        print(f"{path.name}: {path.stat().st_size:,} bytes")


if __name__ == "__main__":
    main()
