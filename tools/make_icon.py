"""Rysuje ikonę LiquidERP (zlewka z liquidem i kroplą) do static/.

Wymaga Pillow (tylko do generowania):  .venv\\Scripts\\python.exe -m pip install pillow
Uruchomienie:  .venv\\Scripts\\python.exe tools\\make_icon.py
"""
import math
import os

from PIL import Image, ImageDraw, ImageFilter

S = 1024  # rysujemy w dużej skali i zmniejszamy – gładkie krawędzie
OUT = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "static")


def vgradient(size, top, bottom):
    w, h = size
    img = Image.new("RGBA", size)
    px = img.load()
    for y in range(h):
        t = y / max(h - 1, 1)
        color = tuple(round(a + (b - a) * t) for a, b in zip(top, bottom))
        for x in range(w):
            px[x, y] = color
    return img


def paste_masked(base, layer, mask):
    base.alpha_composite(Image.composite(layer, Image.new("RGBA", base.size), mask))


def draw_icon():
    img = Image.new("RGBA", (S, S), (0, 0, 0, 0))

    # Tło: zaokrąglony kwadrat z gradientem w kolorze akcentu aplikacji.
    bg_mask = Image.new("L", (S, S))
    ImageDraw.Draw(bg_mask).rounded_rectangle((32, 32, S - 32, S - 32), radius=220, fill=255)
    paste_masked(img, vgradient((S, S), (70, 140, 245, 255), (28, 52, 130, 255)), bg_mask)

    # Delikatna poświata za zlewką.
    glow = Image.new("RGBA", (S, S))
    ImageDraw.Draw(glow).ellipse((210, 300, 814, 900), fill=(255, 190, 120, 70))
    img.alpha_composite(glow.filter(ImageFilter.GaussianBlur(70)))

    # Kształt zlewki: prosty cylinder z zaokrąglonym dnem.
    left, right, top, bottom = 300, 724, 330, 840
    body = Image.new("L", (S, S))
    d = ImageDraw.Draw(body)
    d.rounded_rectangle((left, top, right, bottom), radius=80, fill=255)
    d.rectangle((left, top, right, top + 100), fill=255)

    # Szkło: półprzezroczyste wnętrze.
    paste_masked(img, Image.new("RGBA", (S, S), (255, 255, 255, 46)), body)

    # Liquid: pomarańczowo-różowy gradient z falą na powierzchni.
    level = 560
    liquid = Image.new("L", (S, S))
    wave = [(x, level + 16 * math.sin((x - left) / 68)) for x in range(left - 40, right + 41, 4)]
    ImageDraw.Draw(liquid).polygon(wave + [(right + 40, S), (left - 40, S)], fill=255)
    liquid = Image.composite(liquid, Image.new("L", (S, S)), body)
    paste_masked(img, vgradient((S, S), (255, 196, 92, 255), (240, 84, 110, 255)), liquid)

    # Bąbelki w liquidzie.
    bd = ImageDraw.Draw(img)
    for x, y, r in ((430, 700, 26), (520, 640, 16), (545, 770, 30), (450, 795, 13), (590, 690, 11)):
        bd.ellipse((x - r, y - r, x + r, y + r), fill=(255, 255, 255, 110))

    # Kontur szkła (grubsza krawędź) i wywinięty wylot.
    edge = body.filter(ImageFilter.MaxFilter(35))
    edge = Image.composite(edge, Image.new("L", (S, S)), Image.eval(body, lambda v: 255 - v))
    paste_masked(img, Image.new("RGBA", (S, S), (255, 255, 255, 255)), edge)
    od = ImageDraw.Draw(img)
    od.rounded_rectangle((left - 40, top - 34, right + 40, top + 4), radius=19, fill=(255, 255, 255, 255))

    # Podziałka po prawej stronie.
    for i, y in enumerate((440, 520, 600, 680, 760)):
        length = 70 if i % 2 == 0 else 44
        od.rounded_rectangle((right - 34 - length, y - 7, right - 34, y + 7), radius=7, fill=(255, 255, 255, 200))

    # Odblask na szkle.
    od.rounded_rectangle((left + 34, top + 60, left + 62, bottom - 120), radius=14, fill=(255, 255, 255, 90))

    # Kropla nad zlewką.
    drop = Image.new("L", (S, S))
    dd = ImageDraw.Draw(drop)
    cx, cy, r = 512, 210, 62
    dd.ellipse((cx - r, cy - r, cx + r, cy + r), fill=255)
    dd.polygon([(cx - r * 0.92, cy - r * 0.38), (cx, cy - r * 2.1), (cx + r * 0.92, cy - r * 0.38)], fill=255)
    paste_masked(img, vgradient((S, S), (255, 214, 120, 255), (250, 120, 90, 255)), drop)
    od.ellipse((cx - 30, cy - 26, cx - 8, cy - 4), fill=(255, 255, 255, 170))
    return img


def main():
    big = draw_icon()
    big.resize((512, 512), Image.LANCZOS).save(os.path.join(OUT, "icon-512.png"))
    big.resize((64, 64), Image.LANCZOS).save(os.path.join(OUT, "favicon.png"))
    big.resize((256, 256), Image.LANCZOS).save(
        os.path.join(OUT, "liquiderp.ico"),
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)])
    print("Zapisano ikony w", OUT)


if __name__ == "__main__":
    main()
