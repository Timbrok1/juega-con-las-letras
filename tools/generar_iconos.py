#!/usr/bin/env python3
"""Dibuja los iconos de la app (pantalla de inicio del iPhone y PWA) en icons/.

Fondo naranja del juego, sílaba «ma» en Andika y una estrella.
Todo el dibujo cabe en el 80 % central, así que sirve también como icono
«maskable» (Android lo recorta en círculo). Requiere Pillow: pip install pillow
"""
import math
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent.parent
FUENTE = ROOT / "fonts/andika-700.woff2"
NARANJA, BLANCO, AMARILLO, TINTA = "#FF7A59", "#FFFFFF", "#F7B731", "#2B2B3A"


def estrella(d, cx, cy, r, color):
    pts = []
    for i in range(10):
        a = -math.pi / 2 + i * math.pi / 5
        rr = r if i % 2 == 0 else r * 0.45
        pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
    d.polygon(pts, fill=color)


def icono(n):
    s = 4  # se dibuja a x4 y se reduce para suavizar bordes
    N = n * s
    im = Image.new("RGB", (N, N), NARANJA)
    d = ImageDraw.Draw(im)
    # tarjeta blanca centrada
    m = N * 0.17
    d.rounded_rectangle([m, m * 1.15, N - m, N - m * 0.85], radius=N * 0.12, fill=BLANCO)
    f = ImageFont.truetype(str(FUENTE), int(N * 0.40))
    d.text((N / 2, N * 0.53), "ma", font=f, fill=TINTA, anchor="mm")
    estrella(d, N * 0.72, N * 0.27, N * 0.095, AMARILLO)
    return im.resize((n, n), Image.LANCZOS)


if __name__ == "__main__":
    out = ROOT / "icons"
    out.mkdir(exist_ok=True)
    for n, nombre in [(180, "apple-touch-icon.png"), (192, "icon-192.png"), (512, "icon-512.png")]:
        icono(n).save(out / nombre, optimize=True)
        print("icons/" + nombre)
