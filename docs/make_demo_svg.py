"""Render docs/demo.sh's real output as an animated terminal SVG (docs/demo.svg).

    PATH=.venv/bin:$PATH python docs/make_demo_svg.py

GitHub renders SVG animations in READMEs, and the file stays a few KB. For a GIF,
use `vhs docs/demo.tape` instead.
"""

from __future__ import annotations

import html
import os
import subprocess
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
CHAR_W, LINE_H, PAD, TOP = 7.8, 19, 18, 44
STEP_S = 0.42  # seconds between lines
HOLD_S = 6.0  # final frame


def capture() -> list[str]:
    env = dict(os.environ, NO_COLOR="1")
    out = subprocess.run(
        ["sh", str(HERE / "demo.sh")], capture_output=True, text=True, env=env, check=True
    )
    lines = out.stdout.splitlines()
    while lines and not lines[0].strip():
        lines.pop(0)
    return lines


def style_for(line: str) -> str:
    s = line.lstrip()
    if s.startswith("#"):
        return "c"
    if s.startswith("$ "):
        return "p"
    if s.startswith("GATE: FAIL"):
        return "bad b"
    if s.startswith("GATE: PASS"):
        return "ok b"
    if "REGRESSION" in s or s.startswith("✗"):
        return "bad"
    if s.startswith("✓"):
        return "ok"
    if "deleted or renamed" in s:
        return "warn"
    return "t"


def render(lines: list[str]) -> str:
    width = int(PAD * 2 + CHAR_W * max(len(line) for line in lines))
    height = int(TOP + LINE_H * len(lines) + PAD)
    total = STEP_S * len(lines) + HOLD_S
    css = [
        "text{font:13px ui-monospace,SFMono-Regular,Menlo,Consolas,monospace;white-space:pre}",
        ".t{fill:#d0d7de}.c{fill:#8b949e;font-style:italic}.p{fill:#e6edf3;font-weight:600}",
        ".ok{fill:#3fb950}.bad{fill:#f85149}.warn{fill:#d29922}.b{font-weight:700}",
    ]
    rows = []
    for i, line in enumerate(lines):
        start = 100 * STEP_S * i / total
        appear = min(start + 100 * 0.15 / total, 99)
        css.append(
            f"@keyframes k{i}{{0%,{start:.2f}%{{opacity:0}}{appear:.2f}%,97%{{opacity:1}}100%{{opacity:0}}}}"
            f".l{i}{{animation:k{i} {total:.1f}s linear infinite}}"
        )
        y = TOP + LINE_H * (i + 1) - 5
        rows.append(
            f'<text class="{style_for(line)} l{i}" x="{PAD}" y="{y}">{html.escape(line)}</text>'
        )
    return f"""<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" role="img" aria-label="sprintwarden demo: deleting an old test makes pytest green, but sprint gate fails">
<style>{"".join(css)}</style>
<rect width="100%" height="100%" rx="8" fill="#0d1117"/>
<circle cx="20" cy="18" r="6" fill="#ff5f56"/><circle cx="40" cy="18" r="6" fill="#ffbd2e"/><circle cx="60" cy="18" r="6" fill="#27c93f"/>
<text class="c" x="{width / 2:.0f}" y="22" text-anchor="middle">sprintwarden demo</text>
{chr(10).join(rows)}
</svg>
"""


def main() -> int:
    lines = capture()
    (HERE / "demo.svg").write_text(render(lines), encoding="utf-8")
    (HERE / "demo.txt").write_text("\n".join(lines) + "\n", encoding="utf-8")
    print(f"wrote docs/demo.svg ({len(lines)} lines)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
