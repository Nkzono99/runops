"""Render the runops README images (hero, conversation) in light and dark.

Text is drawn with IBM Plex fonts (SIL OFL, fetched from google/fonts on first
use) and saved as SVG paths, so the images do not depend on the viewer's fonts.

    python .github/assets/make_readme_art.py            # writes the SVGs here
    python .github/assets/make_readme_art.py --preview  # also writes PNG previews

Requires matplotlib.
"""
from __future__ import annotations

import sys
import tempfile
import urllib.request
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt
from matplotlib.font_manager import FontProperties
from matplotlib.patches import Circle, FancyBboxPatch

HERE = Path(__file__).parent
OUT = HERE
PREVIEW = "--preview" in sys.argv
FONTS = Path(tempfile.gettempdir()) / "runops-readme-fonts"
FONT_FILES = {
    "IBMPlexMono-Regular.ttf": "ibmplexmono",
    "IBMPlexMono-Medium.ttf": "ibmplexmono",
    "IBMPlexMono-SemiBold.ttf": "ibmplexmono",
    "IBMPlexSansJP-Regular.ttf": "ibmplexsansjp",
    "IBMPlexSansJP-Medium.ttf": "ibmplexsansjp",
}
FONTS.mkdir(exist_ok=True)
for name, family in FONT_FILES.items():
    if not (FONTS / name).is_file():
        url = f"https://github.com/google/fonts/raw/main/ofl/{family}/{name}"
        urllib.request.urlretrieve(url, FONTS / name)

FP = {
    "mono": FontProperties(fname=FONTS / "IBMPlexMono-Regular.ttf"),
    "mono-md": FontProperties(fname=FONTS / "IBMPlexMono-Medium.ttf"),
    "mono-sb": FontProperties(fname=FONTS / "IBMPlexMono-SemiBold.ttf"),
    "jp": FontProperties(fname=FONTS / "IBMPlexSansJP-Regular.ttf"),
    "jp-md": FontProperties(fname=FONTS / "IBMPlexSansJP-Medium.ttf"),
}

PALETTES = {
    "light": dict(paper="#fbfcfc", ink="#151a1e", ink2="#4a565f", rule="#dfe5e8", brand="#0e6e68",
                  brand_s="#e3f1ef", run="#1f63c6", run_s="#e6eefb", done="#2f7d3a", done_s="#e7f3e8",
                  pend="#a0620c", pend_s="#fbf0dc", note="#e8eef0"),
    "dark": dict(paper="#12181c", ink="#e8eef1", ink2="#9aa7b0", rule="#26313a", brand="#3fc1b4",
                 brand_s="#123331", run="#6aa6ff", run_s="#142640", done="#6cc77a", done_s="#15301b",
                 pend="#e3a548", pend_s="#33260f", note="#1b242b"),
}

matplotlib.rcParams["svg.fonttype"] = "path"
matplotlib.rcParams["svg.hashsalt"] = "runops"


class Canvas:
    def __init__(self, w: int, h: int, pal: dict[str, str]) -> None:
        self.pal = pal
        self.fig = plt.figure(figsize=(w / 100, h / 100), dpi=100)
        self.fig.patch.set_alpha(0)
        self.ax = self.fig.add_axes((0, 0, 1, 1))
        self.ax.set_xlim(0, w)
        self.ax.set_ylim(h, 0)
        self.ax.axis("off")
        self.ax.patch.set_alpha(0)

    def rect(self, x, y, w, h, r, fill, edge=None, lw=0.0):
        self.ax.add_patch(FancyBboxPatch((x, y), w, h, boxstyle=f"round,pad=0,rounding_size={r}",
                                         facecolor=self.pal.get(fill, fill),
                                         edgecolor=self.pal.get(edge, edge) if edge else "none",
                                         linewidth=lw))

    def line(self, x1, y1, x2, y2, color, lw=1.0):
        self.ax.plot([x1, x2], [y1, y2], color=self.pal[color], linewidth=lw, solid_capstyle="butt")

    def dot(self, x, y, r, color):
        self.ax.add_patch(Circle((x, y), r, facecolor=self.pal[color], edgecolor="none"))

    def text(self, x, y, s, font, size_px, color, ha="left"):
        self.ax.text(x, y, s, fontproperties=FP[font], fontsize=size_px * 0.72, color=self.pal[color],
                     va="baseline", ha=ha)

    def save(self, stem: str) -> None:
        self.fig.savefig(OUT / f"{stem}.svg", transparent=True, metadata={"Date": None})
        if PREVIEW:
            bg = "#ffffff" if "light" in stem else "#0d1117"
            self.fig.savefig(OUT / f"{stem}.png", facecolor=bg, dpi=150)
        plt.close(self.fig)


def hero(theme: str) -> None:
    c = Canvas(880, 300, PALETTES[theme])
    c.rect(0, 0, 880, 300, 12, "paper")
    c.text(44, 112, "runops", "mono-sb", 66, "ink")
    c.rect(46, 130, 40, 5, 2.5, "brand")
    c.text(44, 174, "シミュレーションの run を、", "jp-md", 21, "ink")
    c.text(44, 204, "エージェントと回す。", "jp-md", 21, "ink")
    c.text(44, 254, "$ runo init", "mono", 14, "ink2")
    c.text(150, 254, "あとは会話で", "jp", 14, "ink2")

    ox, oy = 372, 36
    c.rect(ox, oy, 472, 228, 9, "paper", edge="rule", lw=1.0)
    c.text(ox + 18, oy + 28, "runo list", "mono", 12, "ink2")
    c.text(ox + 454, oy + 28, "runs/flat/wc-phiz-scan", "mono", 12, "ink2", ha="right")
    c.line(ox, oy + 42, ox + 472, oy + 42, "rule")
    rows = [
        ("R20261015-0006", "running", "run", "wc0.294_phiz45", "72%"),
        ("R20261015-0005", "pending", "pend", "wc0.294_phiz0", "queue"),
        ("R20261015-0004", "done", "done", "wc0.147_phiz45", "11h 52m"),
        ("R20261015-0002", "done", "done", "wc0_phiz0", "11h 40m"),
    ]
    for i, (rid, state, key, label, extra) in enumerate(rows):
        y = oy + 70 + 34 * i
        c.text(ox + 18, y, rid, "mono", 12.5, "ink")
        c.rect(ox + 148, y - 14, 80, 20, 10, f"{key}_s")
        c.dot(ox + 160, y - 4, 3.5, key)
        c.text(ox + 170, y, state, "mono-md", 12.5, key)
        c.text(ox + 242, y, label, "mono", 12.5, "ink")
        c.text(ox + 454, y, extra, "mono", 12.5, "ink2", ha="right")
    c.rect(ox + 242, oy + 182, 212, 26, 5, "note")
    c.text(ox + 252, oy + 200, "note: 2e4 step でシース形成", "jp", 12, "ink2")
    c.save(f"hero-{theme}")


def conversation(theme: str) -> None:
    c = Canvas(880, 346, PALETTES[theme])
    c.rect(0, 0, 880, 346, 12, "paper")
    c.text(32, 40, "YOU", "mono-md", 12, "ink2")
    c.rect(32, 52, 476, 66, 10, "brand_s")
    c.text(50, 80, "wc を 0, 0.147, 0.294、phiz を 0, 45 で振って。", "jp", 15, "ink")
    c.text(50, 104, "smoke が通ったら全部投げて。", "jp", 15, "ink")

    c.text(32, 152, "AGENT", "mono-md", 12, "ink2")
    c.rect(32, 164, 476, 150, 10, "note")
    c.text(50, 192, "6 件の候補を作りました。", "jp", 15, "ink")
    c.text(50, 216, "gr20001a・800 並列・12 h、計 57,600 core-hours", "jp", 13.5, "ink2")
    c.text(50, 246, "smoke（100 step）は 3 分で正常終了。", "jp", 15, "ink")
    c.text(50, 272, "6 件を投入しました（job 8184100–8184105）。", "jp", 15, "ink")
    c.text(50, 296, "終了予定の頃にもう一度確認します。", "jp", 13.5, "ink2")

    c.line(540, 32, 540, 314, "rule")
    c.text(564, 40, "WHAT RUNS", "mono-md", 12, "ink2")
    cmds = [
        (76, True, "runo sweep flat \\"),
        (96, False, "  --set plasma.wc=0,0.147,0.294 \\"),
        (116, False, "  --set plasma.phiz=0,45"),
        (150, True, "runo new flat --scratch \\"),
        (170, False, "  --set jobcon.nstep=100 --submit"),
        (204, True, "runo sync"),
        (238, True, "runo sweep flat ... --apply \\"),
        (258, False, "  --submit"),
    ]
    for y, prompt, s in cmds:
        if prompt:
            c.text(564, y, "$", "mono-md", 12.5, "brand")
        c.text(578, y, s, "mono", 12.5, "ink")
    c.text(564, 294, "6 submitted · confirmed first", "mono", 12.5, "ink2")
    c.save(f"conversation-{theme}")


for theme in PALETTES:
    hero(theme)
    conversation(theme)
print("ok")
