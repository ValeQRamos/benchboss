"""Write docs/images/logo.png: the pixel basketball from ui/logo.py, scaled up 16x.

    python tools/make_logo.py            # or: python tools/make_logo.py --scale 8 out.png

Only the standard library writes the PNG (zlib and struct), so this needs no image package.
Pixels outside the ball are transparent. The colors are the dark theme's.
"""

from __future__ import annotations

import argparse
import struct
import sys
import zlib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))  # the checkout's design, even without `pip install -e`

from benchboss.ui.logo import BALL, colors  # noqa: E402
from benchboss.ui.theme import DARK  # noqa: E402

OUT = ROOT / "docs" / "images" / "logo.png"


def rgba(rows: tuple[str, ...], scale: int) -> list[bytes]:
    """One RGBA scanline per output row."""
    paint = {k: bytes(int(v[i:i + 2], 16) for i in (1, 3, 5)) + b"\xff"
             for k, v in colors(DARK).items()}
    clear = b"\x00\x00\x00\x00"
    lines = []
    for row in rows:
        line = b"".join(paint.get(ch, clear) * scale for ch in row)
        lines += [line] * scale
    return lines


def png(lines: list[bytes]) -> bytes:
    height, width = len(lines), len(lines[0]) // 4

    def chunk(tag: bytes, data: bytes) -> bytes:
        return (struct.pack(">I", len(data)) + tag + data
                + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF))

    header = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)  # 8 bit RGBA
    raw = b"".join(b"\x00" + line for line in lines)  # filter type 0 on every scanline
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", header) + chunk(b"IDAT", zlib.compress(raw, 9))
            + chunk(b"IEND", b""))


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("out", nargs="?", type=Path, default=OUT, help="where to write the PNG")
    ap.add_argument("--scale", type=int, default=16, help="screen pixels per logo pixel")
    args = ap.parse_args()
    args.out.parent.mkdir(parents=True, exist_ok=True)
    args.out.write_bytes(png(rgba(BALL, max(1, args.scale))))
    print(f"wrote {args.out}")


if __name__ == "__main__":
    main()
