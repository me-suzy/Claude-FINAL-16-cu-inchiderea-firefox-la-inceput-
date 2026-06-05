# -*- coding: utf-8 -*-
"""Genereaza o iconita .ico faina (document + sageata de download) pentru launcher."""
from PIL import Image, ImageDraw

S = 256
img = Image.new("RGBA", (S, S), (0, 0, 0, 0))
d = ImageDraw.Draw(img)

# --- fundal cu gradient vertical (navy -> albastru), colturi rotunjite ---
grad = Image.new("RGB", (S, S))
gd = ImageDraw.Draw(grad)
top = (24, 54, 88)
bot = (52, 120, 178)
for y in range(S):
    t = y / (S - 1)
    r = int(top[0] + (bot[0] - top[0]) * t)
    g = int(top[1] + (bot[1] - top[1]) * t)
    b = int(top[2] + (bot[2] - top[2]) * t)
    gd.line([(0, y), (S, y)], fill=(r, g, b))

mask = Image.new("L", (S, S), 0)
md = ImageDraw.Draw(mask)
md.rounded_rectangle([6, 6, S - 6, S - 6], radius=52, fill=255)
img.paste(grad, (0, 0), mask)

# --- foaia alba (documentul) ---
sheet = [70, 40, 176, 196]
d.rounded_rectangle(sheet, radius=12, fill=(248, 248, 246))
# banda aurie sus
d.rounded_rectangle([70, 40, 176, 70], radius=12, fill=(214, 162, 42))
d.rectangle([70, 58, 176, 70], fill=(214, 162, 42))
# linii de text (gri)
ly = 88
for w in (86, 78, 90, 70, 84, 60):
    d.rounded_rectangle([84, ly, 84 + w, ly + 9], radius=4, fill=(176, 178, 182))
    ly += 20

# --- badge verde cu sageata de download (jos-dreapta) ---
cx, cy, r = 184, 190, 40
d.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(40, 165, 86))
d.ellipse([cx - r, cy - r, cx + r, cy + r], outline=(248, 248, 246), width=4)
# sageata in jos
d.rectangle([cx - 7, cy - 20, cx + 7, cy + 4], fill=(255, 255, 255))
d.polygon([(cx - 18, cy + 2), (cx + 18, cy + 2), (cx, cy + 24)], fill=(255, 255, 255))

out = r"d:\TEST\arcanum_capture\arcanum.ico"
img.save(out, format="ICO", sizes=[(256, 256), (128, 128), (64, 64), (48, 48), (32, 32), (16, 16)])
print("iconita salvata:", out)
