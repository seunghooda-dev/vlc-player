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
    for y in range(size):
        for x in range(size):
            nx = x / max(1, size - 1)
            ny = y / max(1, size - 1)
            r = int(10 + 12 * (1 - ny) + 5 * nx)
            g = int(14 + 17 * (1 - ny) + 8 * nx)
            b = int(22 + 34 * (1 - ny) + 26 * nx)
            pix[x, y] = (r, g, b, 255)
    img.alpha_composite(Image.composite(bg, Image.new("RGBA", (size, size), (0, 0, 0, 0)), mask))

    glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    gd = ImageDraw.Draw(glow)
    gd.ellipse((-size * 0.22, -size * 0.28, size * 0.82, size * 0.58), fill=(56, 164, 255, 60))
    gd.ellipse((size * 0.40, size * 0.50, size * 1.25, size * 1.18), fill=(45, 212, 191, 36))
    glow = glow.filter(ImageFilter.GaussianBlur(size // 14))
    img.alpha_composite(glow)
    return img


def draw_icon(size=1024):
    scale = size / 1024
    img = _rounded_gradient(size, int(190 * scale))
    d = ImageDraw.Draw(img)

    def xy(values):
        return tuple(int(v * scale) for v in values)

    shadow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    sd = ImageDraw.Draw(shadow)
    sd.rounded_rectangle(xy((152, 218, 872, 748)), radius=int(74 * scale), fill=(0, 0, 0, 145))
    shadow = shadow.filter(ImageFilter.GaussianBlur(int(30 * scale)))
    img.alpha_composite(shadow)

    d.rounded_rectangle(xy((142, 196, 882, 724)), radius=int(70 * scale), fill=(18, 23, 34, 238), outline=(91, 167, 255, 210), width=max(3, int(10 * scale)))
    d.rounded_rectangle(xy((196, 268, 828, 600)), radius=int(36 * scale), fill=(8, 12, 20, 255), outline=(55, 66, 86, 255), width=max(2, int(6 * scale)))

    # Broadcast safe-frame crosshair
    d.line(xy((220, 305, 320, 305)), fill=(243, 244, 248, 145), width=max(2, int(5 * scale)))
    d.line(xy((270, 255, 270, 355)), fill=(243, 244, 248, 145), width=max(2, int(5 * scale)))
    d.line(xy((704, 305, 804, 305)), fill=(243, 244, 248, 145), width=max(2, int(5 * scale)))
    d.line(xy((754, 255, 754, 355)), fill=(243, 244, 248, 145), width=max(2, int(5 * scale)))

    # Audio/QC bars
    bars = [96, 138, 188, 245, 198, 154, 118]
    for i, h in enumerate(bars):
        x0 = 276 + i * 66
        y0 = 558 - h
        color = (74, 222, 128, 255) if i < 5 else (255, 209, 102, 255)
        d.rounded_rectangle(xy((x0, y0, x0 + 32, 558)), radius=int(12 * scale), fill=color)

    # Yellow QC line and check mark
    d.line(xy((228, 636, 796, 636)), fill=(255, 209, 102, 255), width=max(3, int(9 * scale)))
    d.line(xy((648, 464, 708, 524)), fill=(45, 212, 191, 255), width=max(7, int(18 * scale)))
    d.line(xy((708, 524, 808, 394)), fill=(45, 212, 191, 255), width=max(7, int(18 * scale)))

    # Text
    font_big = _font(int(124 * scale), bold=True)
    font_small = _font(int(54 * scale), bold=True)
    text = "MXF"
    tw = d.textbbox((0, 0), text, font=font_big)[2]
    d.text(((size - tw) / 2, int(735 * scale)), text, font=font_big, fill=(243, 244, 248, 255))
    sub = "QC"
    sw = d.textbbox((0, 0), sub, font=font_small)[2]
    d.text(((size - sw) / 2, int(858 * scale)), sub, font=font_small, fill=(90, 167, 255, 245))

    # Outer highlight
    d.rounded_rectangle(xy((18, 18, 1006, 1006)), radius=int(190 * scale), outline=(255, 255, 255, 42), width=max(2, int(5 * scale)))
    return img


def main():
    base = draw_icon(1024)
    base.resize((256, 256), Image.Resampling.LANCZOS).save(PNG_PATH)
    sizes = [(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)]
    base.save(ICO_PATH, sizes=sizes)
    print(ICO_PATH)


if __name__ == "__main__":
    main()
