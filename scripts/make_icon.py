#!/usr/bin/env python3
"""Generate the ImagineAI source app icon (1024x1024 RGBA PNG) with stdlib only.

A violet->pink rounded square (matching the app's logo gradient) with a white
4-point sparkle (astroid) — the same ✦ motif used in the header.
"""
import struct
import sys
import zlib

SIZE = 1024
C = SIZE / 2.0
MARGIN = 36
H = (SIZE / 2.0) - MARGIN          # half-extent of the square
R = 188.0                          # corner radius
HR = H - R
VIOLET = (139, 92, 246)
PINK = (236, 72, 153)
WHITE = (250, 248, 255)


def lerp(a, b, t):
    return a + (b - a) * t


def inside_round_square(ax, ay):
    qx = max(0.0, ax - HR)
    qy = max(0.0, ay - HR)
    return (qx * qx + qy * qy) <= (R * R)


def astroid(px, py, cx, cy, rad):
    nx = abs(px - cx) / rad
    ny = abs(py - cy) / rad
    if nx > 1.0 or ny > 1.0:
        return False
    return (nx ** (2.0 / 3.0) + ny ** (2.0 / 3.0)) <= 1.0


def build():
    buf = bytearray(SIZE * SIZE * 4)
    i = 0
    for y in range(SIZE):
        ay = abs(y + 0.5 - C)
        for x in range(SIZE):
            ax = abs(x + 0.5 - C)
            if not inside_round_square(ax, ay):
                i += 4  # transparent
                continue
            t = ((x / SIZE) * 0.5 + (y / SIZE) * 0.5)
            r = int(lerp(VIOLET[0], PINK[0], t))
            g = int(lerp(VIOLET[1], PINK[1], t))
            b = int(lerp(VIOLET[2], PINK[2], t))
            # main centered sparkle + a small accent sparkle top-right
            if astroid(x + 0.5, y + 0.5, C, C, 312.0) or \
               astroid(x + 0.5, y + 0.5, 760.0, 300.0, 96.0):
                r, g, b = WHITE
            buf[i] = r
            buf[i + 1] = g
            buf[i + 2] = b
            buf[i + 3] = 255
            i += 4
    return bytes(buf)


def png(width, height, rgba):
    def chunk(typ, data):
        return struct.pack(">I", len(data)) + typ + data + \
            struct.pack(">I", zlib.crc32(typ + data) & 0xFFFFFFFF)
    ihdr = struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0)
    stride = width * 4
    raw = bytearray()
    for y in range(height):
        raw.append(0)
        raw.extend(rgba[y * stride:(y + 1) * stride])
    return (b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
            + chunk(b"IDAT", zlib.compress(bytes(raw), 9)) + chunk(b"IEND", b""))


def main():
    out = sys.argv[1] if len(sys.argv) > 1 else "icon-source.png"
    open(out, "wb").write(png(SIZE, SIZE, build()))
    print(f"wrote {out}")


if __name__ == "__main__":
    main()
