#!/usr/bin/env python3
"""Control de calidad de los audios: los transcribe con Whisper y marca los dudosos.

Compara lo que «oye» Whisper con el texto esperado, ignorando tildes, signos y
letras que suenan igual (B/V, LL/Y, H muda, C/K/QU, C/Z, G/J). Al final crea
una página HTML con los audios dudosos para escucharlos y decidir cuáles
rehacer con:  python tools/generar_audios.py --rehacer ma xi ...

Whisper se equivoca a menudo con sílabas sueltas, así que una marca no significa
que el audio esté mal: solo que conviene escucharlo.

Uso:
    ~/.venvs/juego-lectura/bin/pip install faster-whisper     # una vez
    ~/.venvs/juego-lectura/bin/python tools/revisar_audios.py [--modelo small] [--salida revision.html]
"""
import argparse
import html
import json
import re
import sys
import unicodedata
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import generar_audios as g  # noqa: E402


def sonido(t):
    """Clave fonética aproximada de un texto en español."""
    t = unicodedata.normalize("NFD", t.lower())
    t = "".join(c for c in t if unicodedata.category(c) != "Mn" or c == "̃")
    t = unicodedata.normalize("NFC", t)
    t = re.sub(r"[^a-zñ ]", "", t)
    for a, b in [("ch", "ç"), ("qu", "k"), (r"c(?=[aou])", "k"), (r"c(?=[ei])", "z"), (r"g(?=[ei])", "j"),
                 (r"gu(?=[ei])", "g"), ("ll", "y"), ("rr", "r"), ("v", "b"), ("w", "u"), ("h", ""), ("x", "ks"),
                 (r"(.)\1+", r"\1"), (" ", "")]:
        t = re.sub(a, b, t)
    return t


def leer(path):
    """Audio a 16 kHz en float32 con ffmpeg (evita depender de PyAV)."""
    import subprocess
    import numpy as np

    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", "16000", "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    return np.frombuffer(pcm, np.int16).astype(np.float32) / 32768


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--modelo", default="small", help="modelo de Whisper: base, small, medium…")
    ap.add_argument("--salida", default=str(g.ROOT / "revision.html"))
    a = ap.parse_args()

    from faster_whisper import WhisperModel

    modelo = WhisperModel(a.modelo, device="cpu", compute_type="int8")
    d = g.cargar_datos()
    continuos = {v.lower() for v in d.get("CONTINUANT", {}).values()}  # sonidos largos (ya no se usan)
    dudosos, total = [], 0
    for t in g.textos(d):
        k = g.clave(t)
        f = g.AUDIO / f"{k}.mp3"
        if not f.exists():
            continue
        total += 1
        segs, _ = modelo.transcribe(leer(f), language="es", beam_size=5, vad_filter=False,
                                    condition_on_previous_text=False)
        oido = " ".join(s.text.strip() for s in segs).strip()
        if t.lower() in continuos:
            ok = sonido(oido) in ("", sonido(t)) or set(sonido(oido)) <= set(sonido(t))
        else:
            ok = sonido(oido) == sonido(t)
        print(f"{'  ' if ok else '❗'} {t:40s} oído: {oido}")
        if not ok:
            dudosos.append((t, k, oido))

    filas = "".join(
        f'<tr><td><b>{html.escape(t)}</b></td><td>{html.escape(o) or "<i>(nada)</i>"}</td>'
        f'<td><audio controls preload="none" src="audio/{k}.mp3"></audio></td><td><code>{html.escape(t)}</code></td></tr>'
        for t, k, o in dudosos)
    Path(a.salida).write_text(f"""<!doctype html><html lang="es"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Revisar audios</title>
<style>body{{font-family:system-ui,sans-serif;margin:16px;background:#FFF8EC;color:#2B2B3A}}
table{{border-collapse:collapse;width:100%}}td{{padding:6px;border-bottom:1px solid #ddd;vertical-align:middle}}
@media (prefers-color-scheme:dark){{body{{background:#1d1d24;color:#eee}}}}</style></head><body>
<h1>Audios dudosos: {len(dudosos)} de {total}</h1>
<p>Whisper no ha entendido estos audios como el texto esperado. Escúchalos: si alguno suena mal,
rehazlo con <code>python3 tools/generar_audios.py --rehacer TEXTO1 TEXTO2…</code></p>
<table><tr><th>Texto</th><th>Whisper oyó</th><th>Audio</th><th>Para rehacer</th></tr>{filas}</table>
</body></html>""", encoding="utf-8")
    print(f"\n{len(dudosos)} dudosos de {total}. Página: {a.salida}")
    json.dump([{"texto": t, "oido": o} for t, _, o in dudosos],
              open(Path(a.salida).with_suffix(".json"), "w", encoding="utf-8"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()
