from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter


ROOT = Path(__file__).resolve().parent
ICO_PATH = ROOT / "mxf_qc_player.ico"
PNG_PATH = ROOT / "mxf_qc_player_256.png"


def _font(size, bold=False):
    candidates = [
        Path(r"C:\Windows\Fonts\segoeuib.ttf") if bold else Path(r"C:\Windows\Fonts\segoeui.ttf"),
        Path(r"C:\Windows\Fonts\malgunbd.ttf") if bold else Path(r"C:\Windows\Fonts\malgun.ttf"),
        Path(r"C:\Windows\Fonts\arialbd.ttf") if bold else Path(r"C:\Windows\Fonts\arial.ttf"),
    ]
    for path in candidates:
        if path.exists():
            return ImageFont.truetype(str(path), size)
    return ImageFont.load_default()


def _rounded_gradient(size, radius):
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    mask = Image.new("L", (size, size), 0)
    ImageDraw.Draw(mask).rounded_rectangle((0, 0, size - 1, size - 1), radius=radius, fill=255)

    bg = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    pix = bg.load()
    cx = cy = (size - 1) / 2
    max_dist = (cx * cx + cy * cy) ** 0.5
    for y in range(size):
        for x in range(size):
            nx = x / max(1, size - 1)
            ny = y / max(1, size - 1)
            dist = (((x - cx) ** 2 + (y - cy) ** 2) ** 0.5) / max_dist
            brushed = 7 if (y // max(1, size // 84)) % 2 == 0 else -3
            edge = max(0.0, dist - 0.36) * 60
            r = int(14 + 18 * (1 - ny) + 10 * nx - edge + brushed)
            g = int(17 + 22 * (1 - ny) + 13 * nx - edge + brushed)
            b = int(22 + 34 * (1 - ny) + 22 * nx - edge + brushed)
            pix[x, y] = (r, g, b, 255)
    img.alpha_composite(Image.composite(bg, Image.new("RGBA", (size, size), (0, 0, 0, 0)), mask))

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-size * 0.28, -size * 0.25, size * 0.88, size * 0.58), fill=(180, 205, 230, 36))
    gd.ellipse((size * 0.45, size * 0.50, size * 1.22, size * 1.15), fill=(90, 167, 255, 30))
    glow = glow.filter(ImageFilter.GaussianBlur(size // 14))
    img.alpha_composite(glow)
    return img


def draw_icon(size=1024):
    scale = size / 1024
    img = _rounded_gradient(size, int(214 * scale))
    d = ImageDraw.Draw(img)

    def xy(values):
        return tuple(int(v * scale) for v in values)

    # Deep cast shadow for the machined center button
    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.ellipse(xy((150, 160, 874, 884)), fill=(0, 0, 0, 150))
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(34 * scale)))
    img.alpha_composite(shadow)

    # Outer bevel and metal face
    d.ellipse(xy((138, 122, 886, 870)), fill=(9, 12, 18, 250), outline=(167, 183, 205, 132), width=max(4, int(11 * scale)))
    d.ellipse(xy((178, 162, 846, 830)), fill=(26, 32, 42, 255), outline=(48, 58, 74, 255), width=max(3, int(9 * scale)))
    d.arc(xy((178, 162, 846, 830)), 205, 335, fill=(90, 167, 255, 170), width=max(5, int(13 * scale)))
    d.arc(xy((202, 186, 822, 806)), 20, 164, fill=(240, 246, 255, 75), width=max(3, int(8 * scale)))

    # Inner dark glass surface
    inner = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    idr = ImageDraw.Draw(inner)
    idr.ellipse(xy((242, 226, 782, 766)), fill=(6, 9, 15, 242), outline=(78, 92, 116, 210), width=max(3, int(8 * scale)))
    inner_glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(inner_glow)
    gd.ellipse(xy((300, 250, 760, 580)), fill=(255, 255, 255, 24))
    gd.ellipse(xy((282, 552, 792, 820)), fill=(34, 128, 255, 22))
    inner.alpha_composite(inner_glow.filter(ImageFilter.GaussianBlur(int(20 * scale))))
    img.alpha_composite(inner)

    # Chrome play glyph shadow
    play_shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    ps = ImageDraw.Draw(play_shadow)
    ps.polygon([xy((438, 352)), xy((438, 650)), xy((660, 501))], fill=(0, 0, 0, 170))
    play_shadow = play_shadow.filter(ImageFilter.GaussianBlur(int(14 * scale)))
    img.alpha_composite(play_shadow)

    # Main play glyph, large and readable at desktop sizes
    play = [xy((418, 326)), xy((418, 674)), xy((690, 500))]
    d.polygon(play, fill=(232, 239, 248, 255))
    d.line([xy((418, 326)), xy((418, 674)), xy((690, 500)), xy((418, 326))], fill=(255, 255, 255, 170), width=max(2, int(6 * scale)))
    d.line([xy((434, 358)), xy((660, 500)), xy((434, 642))], fill=(111, 191, 255, 120), width=max(2, int(8 * scale)))

    # Subtle QC identity marks
    font_small = _font(int(58 * scale), bold=True)
    label = "MXF"
    tw = d.textbbox((0, 0), label, font=font_small)[2]
    d.text(((size - tw) / 2, int(795 * scale)), label, font=font_small, fill=(170, 184, 204, 210))
    d.line(xy((344, 770, 680, 770)), fill=(90, 167, 255, 115), width=max(2, int(5 * scale)))

    # Outer glass highlight
    d.rounded_rectangle(xy((18, 18, 1006, 1006)), radius=int(214 * scale), outline=(255, 255, 255, 45), width=max(2, int(5 * scale)))
    d.arc(xy((44, 42, 980, 980)), 214, 322, fill=(90, 167, 255, 95), width=max(3, int(8 * scale)))
    return img


def main():
    base = draw_icon(1024)
    base.resize((256, 256), Image.Resampling.LANCZOS).save(PNG_PATH)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    base.save(ICO_PATH, sizes=sizes)
    print(ICO_PATH)


if __name__ == "__main__":
    main()
