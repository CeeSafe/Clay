#!/usr/bin/env python3
"""Writes the image-decoder fixtures: PNGs of every color type and bit depth (all five row filters, Adam7, stored /
fixed / dynamic deflate, IDAT split into tiny chunks, tRNS) and BMPs (1/4/8-bit palettes, 16/24/32-bit, bit fields,
top-down, the OS/2 core header). Each NAME.png / NAME.bmp has NAME.rgba, the expected pixels (R, G, B, A bytes,
row-major), computed from the source values; where Pillow decodes the file the same way, it is checked against
Pillow too, so the encoder here is not the only judge. manifest.txt lists the names.

Usage: make_images.py OUT_DIR
"""
import os, struct, sys, zlib, random

W, H = 13, 11  # odd sizes exercise Adam7's partial passes and row padding


def chunk(kind, data):
    return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data) & 0xFFFFFFFF)


def paeth(a, b, c):
    p = a + b - c
    pa, pb, pc = abs(p - a), abs(p - b), abs(p - c)
    return a if pa <= pb and pa <= pc else (b if pb <= pc else c)


def filter_rows(rows, bpp, rng):
    out = bytearray()
    prev = bytes(len(rows[0])) if rows else b""
    for row in rows:
        f = rng.randrange(5)
        out.append(f)
        for x in range(len(row)):
            a = row[x - bpp] if x >= bpp else 0
            b = prev[x]
            c = prev[x - bpp] if x >= bpp else 0
            pred = [0, a, b, (a + b) // 2, paeth(a, b, c)][f]
            out.append((row[x] - pred) & 255)
        prev = row
    return out


def pack_row(samples, depth):
    if depth == 8:
        return bytes(samples)
    if depth == 16:
        return b"".join(struct.pack(">H", s) for s in samples)
    out, acc, n = bytearray(), 0, 0
    for s in samples:
        acc = (acc << depth) | s
        n += depth
        if n == 8:
            out.append(acc)
            acc, n = 0, 0
    if n:
        out.append(acc << (8 - n))
    return bytes(out)


PASSES = [(0, 0, 8, 8), (4, 0, 8, 8), (0, 4, 4, 8), (2, 0, 4, 4), (0, 2, 2, 4), (1, 0, 2, 2), (0, 1, 1, 2)]


def png(path, ctype, depth, pixels, channels, *, interlace=False, plte=None, trns=None, level=6, strategy=None,
        idat_size=None, seed=1):
    """`pixels[y][x]` is a tuple of `channels` raw samples."""
    rng = random.Random(seed)
    bits = channels * depth
    bpp = max(1, bits // 8)
    raw = bytearray()
    passes = PASSES if interlace else [(0, 0, 1, 1)]
    for x0, y0, dx, dy in passes:
        xs, ys = list(range(x0, W, dx)), list(range(y0, H, dy))
        if not xs or not ys:
            continue
        rows = [pack_row([s for x in xs for s in pixels[y][x]], depth) for y in ys]
        raw += filter_rows(rows, bpp, rng)
    if strategy is not None:
        co = zlib.compressobj(level, zlib.DEFLATED, 15, 9, strategy)
        z = co.compress(bytes(raw)) + co.flush()
    else:
        z = zlib.compress(bytes(raw), level)
    ihdr = struct.pack(">IIBBBBB", W, H, depth, ctype, 0, 0, 1 if interlace else 0)
    data = b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr)
    data += chunk(b"tEXt", b"Comment\x00an ancillary chunk to skip")
    if plte is not None:
        data += chunk(b"PLTE", bytes(c for e in plte for c in e))
    if trns is not None:
        data += chunk(b"tRNS", trns)
    step = idat_size or len(z)
    for i in range(0, len(z), step):
        data += chunk(b"IDAT", z[i:i + step])
    data += chunk(b"IEND", b"")
    open(path, "wb").write(data)


def write_expected(path, rgba):
    open(path, "wb").write(bytes(c for row in rgba for px in row for c in px))


def pillow_agrees(path, rgba):
    try:
        from PIL import Image
    except ImportError:
        return True
    im = Image.open(path).convert("RGBA")
    got = list(im.getdata())
    want = [px for row in rgba for px in row]
    return got == want


def main():
    out = sys.argv[1]
    os.makedirs(out, exist_ok=True)
    rng = random.Random(7)
    names = []

    def emit(name, ext, rgba, check_pillow=True):
        path = os.path.join(out, f"{name}.{ext}")
        write_expected(os.path.join(out, f"{name}.rgba"), rgba)
        if check_pillow and not pillow_agrees(path, rgba):
            sys.exit(f"Pillow disagrees with the expected pixels of {name}.{ext}")
        names.append(f"{name}.{ext}")

    def grid(f):
        return [[f(x, y) for x in range(W)] for y in range(H)]

    # ---- PNG ----
    for depth in (1, 2, 4, 8, 16):
        top = (1 << depth) - 1
        px = grid(lambda x, y: (rng.randrange(top + 1),))
        scale = (lambda v: v >> 8) if depth == 16 else (lambda v: v * 255 // top)
        rgba = [[(scale(p[0]),) * 3 + (255,) for p in row] for row in px]
        for il in (False, True):
            name = f"gray{depth}{'_i' if il else ''}"
            png(os.path.join(out, name + ".png"), 0, depth, px, 1, interlace=il, seed=depth)
            emit(name, "png", rgba, check_pillow=depth != 16)
    # gray 8 with a tRNS key
    px = grid(lambda x, y: ((x * 20 + y) % 256,))
    key = px[3][4][0]
    rgba = [[(p[0],) * 3 + (0 if p[0] == key else 255,) for p in row] for row in px]
    png(os.path.join(out, "gray8_trns.png"), 0, 8, px, 1, trns=struct.pack(">H", key))
    emit("gray8_trns", "png", rgba)

    for depth in (8, 16):
        top = (1 << depth) - 1
        px = grid(lambda x, y: tuple(rng.randrange(top + 1) for _ in range(3)))
        sh = 8 if depth == 16 else 0
        rgba = [[tuple(c >> sh for c in p) + (255,) for p in row] for row in px]
        for il in (False, True):
            name = f"rgb{depth}{'_i' if il else ''}"
            png(os.path.join(out, name + ".png"), 2, depth, px, 3, interlace=il, seed=depth + 1)
            emit(name, "png", rgba, check_pillow=depth != 16)
        px4 = grid(lambda x, y: tuple(rng.randrange(top + 1) for _ in range(4)))
        rgba4 = [[tuple(c >> sh for c in p) for p in row] for row in px4]
        for il in (False, True):
            name = f"rgba{depth}{'_i' if il else ''}"
            png(os.path.join(out, name + ".png"), 6, depth, px4, 4, interlace=il, seed=depth + 2)
            emit(name, "png", rgba4, check_pillow=depth != 16)
        pxga = grid(lambda x, y: tuple(rng.randrange(top + 1) for _ in range(2)))
        rgbaga = [[(p[0] >> sh,) * 3 + (p[1] >> sh,) for p in row] for row in pxga]
        name = f"graya{depth}"
        png(os.path.join(out, name + ".png"), 4, depth, pxga, 2, seed=depth + 3)
        emit(name, "png", rgbaga, check_pillow=depth != 16)
    # rgb 8 with a tRNS key
    px = grid(lambda x, y: ((x * 19) % 256, (y * 23) % 256, 77))
    key = px[5][2]
    rgba = [[p + (0 if p == key else 255,) for p in row] for row in px]
    png(os.path.join(out, "rgb8_trns.png"), 2, 8, px, 3, trns=struct.pack(">HHH", *key))
    emit("rgb8_trns", "png", rgba)

    # palettes, with partial tRNS
    for depth in (1, 2, 4, 8):
        n = min(1 << depth, 200)
        plte = [(rng.randrange(256), rng.randrange(256), rng.randrange(256)) for _ in range(n)]
        alphas = bytes(rng.randrange(256) for _ in range(n // 2 + 1))[:n]
        px = grid(lambda x, y: (rng.randrange(n),))
        rgba = [[plte[p[0]] + ((alphas[p[0]] if p[0] < len(alphas) else 255),) for p in row] for row in px]
        for il in (False, True):
            name = f"pal{depth}{'_i' if il else ''}"
            png(os.path.join(out, name + ".png"), 3, depth, px, 1, interlace=il, plte=plte, trns=alphas, seed=depth + 4)
            emit(name, "png", rgba)

    # deflate variants on one RGBA image: stored, fixed Huffman, best, and IDAT split into 7-byte chunks
    px = grid(lambda x, y: ((x * 13) % 256, (y * 29) % 256, (x * y) % 256, 255 - x * 9))
    rgba = [[p for p in row] for row in px]
    png(os.path.join(out, "stored.png"), 6, 8, px, 4, level=0)
    emit("stored", "png", rgba)
    png(os.path.join(out, "fixed.png"), 6, 8, px, 4, strategy=zlib.Z_FIXED)
    emit("fixed", "png", rgba)
    png(os.path.join(out, "best.png"), 6, 8, px, 4, level=9)
    emit("best", "png", rgba)
    png(os.path.join(out, "split.png"), 6, 8, px, 4, idat_size=7)
    emit("split", "png", rgba)
    # a larger, compressible image so long matches and distances get used
    global W, H
    W, H = 96, 80
    big = grid(lambda x, y: ((x // 8) * 30 % 256, (y // 8) * 40 % 256, 128, 255))
    png(os.path.join(out, "big.png"), 6, 8, big, 4, level=9)
    emit("big", "png", big)
    W, H = 13, 11

    # ---- BMP ----
    def bmp(name, bpp, rgba, *, palette=None, top_down=False, header=40, bitfields=None, alpha_mask=0):
        stride = (W * bpp + 31) // 32 * 4
        rows = []
        for y in range(H):
            row = bytearray()
            if bpp <= 8:
                index = [palette.index(px[:3]) for px in rgba[y]]
                row = bytearray(pack_row(index, bpp))
            else:
                for r, g, b, a in rgba[y]:
                    if bpp == 24:
                        row += bytes((b, g, r))
                    elif bpp == 16:
                        row += struct.pack("<H", ((r >> 3) << 10) | ((g >> 3) << 5) | (b >> 3))
                    else:
                        row += struct.pack("<I", (a << 24) | (r << 16) | (g << 8) | b)
            row += bytes(stride - len(row))
            rows.append(bytes(row))
        pixels = b"".join(rows if top_down else rows[::-1])
        if header == 12:
            info = struct.pack("<IHHHH", 12, W, H, 1, bpp)
            pal = b"".join(bytes((b, g, r)) for r, g, b in palette) if palette else b""
        else:
            compression = 3 if bitfields else 0
            info = struct.pack("<IiiHHIIiiII", header, W, -H if top_down else H, 1, bpp, compression, len(pixels),
                               2835, 2835, len(palette) if palette else 0, 0)
            if header > 40:
                masks = bitfields or (0, 0, 0)
                info += struct.pack("<IIII", masks[0], masks[1], masks[2], alpha_mask)
                info += bytes(header - len(info))
            elif bitfields:
                info += struct.pack("<III", *bitfields)
            pal = b"".join(bytes((b, g, r, 0)) for r, g, b in palette) if palette else b""
        offset = 14 + len(info) + len(pal)
        data = b"BM" + struct.pack("<IHHI", offset + len(pixels), 0, 0, offset) + info + pal + pixels
        open(os.path.join(out, name + ".bmp"), "wb").write(data)

    opaque = grid(lambda x, y: ((x * 17) % 256, (y * 21) % 256, (x + y) * 9 % 256, 255))
    bmp("bgr24", 24, opaque)
    emit("bgr24", "bmp", opaque)
    bmp("bgr24_top", 24, opaque, top_down=True)
    emit("bgr24_top", "bmp", opaque)
    bmp("bgrx32", 32, opaque)
    emit("bgrx32", "bmp", opaque)
    translucent = grid(lambda x, y: ((x * 17) % 256, (y * 21) % 256, 99, (x * 20 + y * 3) % 256))
    bmp("bgra32_v4", 32, translucent, header=108, bitfields=(0x00FF0000, 0x0000FF00, 0x000000FF), alpha_mask=0xFF000000)
    emit("bgra32_v4", "bmp", translucent)
    five = grid(lambda x, y: (((x * 3) % 32) << 3, ((y * 5) % 32) << 3, ((x + y) % 32) << 3, 255))
    five_expected = [[tuple((c >> 3) * 255 // 31 for c in p[:3]) + (255,) for p in row] for row in five]
    bmp("rgb555", 16, five)
    emit("rgb555", "bmp", five_expected)
    for bpp in (1, 4, 8):
        n = 1 << bpp
        palette = []
        while len(palette) < n:
            e = (rng.randrange(256), rng.randrange(256), rng.randrange(256))
            if e not in palette:
                palette.append(e)
        img = grid(lambda x, y: palette[rng.randrange(n)] + (255,))
        bmp(f"bmp_pal{bpp}", bpp, img, palette=palette)
        emit(f"bmp_pal{bpp}", "bmp", img)
        if bpp == 8:
            bmp("core8", 8, img, palette=palette, header=12)
            emit("core8", "bmp", img)

    open(os.path.join(out, "manifest.txt"), "w").write("\n".join(names) + "\n")
    print(f"{len(names)} fixtures in {out}")


if __name__ == "__main__":
    main()
