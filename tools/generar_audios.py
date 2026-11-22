#!/usr/bin/env python3
"""Genera los audios del juego con Piper (voz neuronal local, gratis).

Lee data.js y crea un MP3 por cada texto que el juego puede decir:
vocales, sílabas de todas las consonantes, palabras y sus sílabas,
sonidos continuos (mmm, sss...) y frases fijas.

Es idempotente: solo genera lo que falta o lo que ha cambiado (texto,
fonemas, voz o ajustes). Al terminar escribe audio/manifest.json, que el
juego usa para saber qué audios existen.

Uso:
    python tools/generar_audios.py                 # genera lo que falte
    python tools/generar_audios.py --lista         # solo muestra los textos
    python tools/generar_audios.py --forzar        # lo regenera todo
    python tools/generar_audios.py --limpiar       # borra MP3 que ya no se usan
    python tools/generar_audios.py --voz es_ES-sharvard-medium --hablante F

Requisitos: pip install -r tools/requirements.txt  y  ffmpeg en el PATH.
"""
import argparse
import hashlib
import json
import os
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "audio"
MANIFEST = AUDIO / "manifest.json"
VOCES_DIR = Path(os.environ.get("PIPER_VOCES", Path.home() / ".local/share/piper-voces"))

VOZ_POR_DEFECTO = "es_ES-davefx-medium"
LENGTH_SCALE = 1.15  # algo más lento que lo normal: es para un niño de 4-5 años

# Fonema largo para los sonidos continuos (CONTINUANT de data.js)
FONEMA_CONTINUO = {"m": "m", "l": "l", "s": "s", "n": "n", "f": "f", "z": "θ", "j": "x"}


# ---------------------------------------------------------------- datos

def cargar_datos():
    txt = (ROOT / "data.js").read_text(encoding="utf-8")
    ini = txt.index("{", txt.index("window.DATA"))
    return json.loads(txt[ini : txt.rindex("}") + 1])


def clave(texto):
    """Nombre de archivo del audio. DEBE coincidir con akey() de index.html."""
    t = unicodedata.normalize("NFC", texto.lower())
    for a, b in (("ñ", "ny"), ("á", "a_"), ("é", "e_"), ("í", "i_"), ("ó", "o_"), ("ú", "u_"), ("ü", "u")):
        t = t.replace(a, b)
    return re.sub(r"[^a-z_]+", "-", t).strip("-")


def silaba(c, v):
    """Igual que syl() de index.html: Q solo forma QUE/QUI."""
    if c == "Q":
        return "QU" + v if v in "EI" else None
    return c + v


def textos(d):
    """Todos los textos que el juego puede pasar a say()."""
    out = list(d["VOWELS"])
    for c in d["ALL_CONS"]:
        for v in d["VOWELS"]:
            s = silaba(c, v)
            if s:
                out.append(s)
    for w in d["WORDS"]:
        out.append(w["w"])
        out.extend(w["s"])
    out.extend(d["CONTINUANT"].values())
    out.extend(d["PHRASES"].values())
    vistos, res = set(), []
    for t in out:
        if t.lower() not in vistos:
            vistos.add(t.lower())
            res.append(t)
    return res


def entrada_piper(texto, continuos):
    """Texto o fonemas [[...]] que se le pasan a Piper.

    Piper (espeak) deletrea algunas sílabas sueltas: «rra» -> «erre erre a»,
    «xi» -> «once» (número romano), «mmm» -> «eme eme eme». Para esas se
    pasan los fonemas directamente.
    """
    t = unicodedata.normalize("NFC", texto.lower())
    if t in continuos:
        return "[[" + FONEMA_CONTINUO[t[0]] + "ː]]"
    m = re.fullmatch(r"rr([aeiou])", t)
    if m:
        return f"[[rˈ{m.group(1)}]]"
    m = re.fullmatch(r"x([aeiou])", t)
    if m:
        return f"[[ksˈ{m.group(1)}]]"
    return t


# ---------------------------------------------------------------- audio

def cargar_voz(nombre):
    from piper import PiperVoice

    VOCES_DIR.mkdir(parents=True, exist_ok=True)
    modelo = VOCES_DIR / f"{nombre}.onnx"
    if not modelo.exists():
        print(f"Descargando la voz {nombre}…")
        subprocess.run([sys.executable, "-m", "piper.download_voices", "--download-dir", str(VOCES_DIR), nombre], check=True)
    return PiperVoice.load(str(modelo))


def hablante_id(voz, hablante):
    if hablante is None:
        return None
    mapa = voz.config.speaker_id_map or {}
    if hablante in mapa:
        return mapa[hablante]
    if hablante.isdigit():
        return int(hablante)
    sys.exit(f"Hablante «{hablante}» no existe en esta voz. Opciones: {list(mapa) or 'ninguna'}")


# Recorta silencios al principio y al final, y deja un margen de 40 ms al final.
RECORTE = (
    "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
    "silenceremove=start_periods=1:start_threshold=-45dB,afade=t=in:d=0.03,areverse"
)
# Sonidos continuos: se estiran x4 sin cambiar el tono y se suaviza el final.
ESTIRA = "atempo=0.5,atempo=0.5,areverse,afade=t=in:d=0.25,areverse"


def generar(voz, cfg, entrada, destino, continuo):
    from piper import SynthesisConfig

    with tempfile.TemporaryDirectory() as tmp:
        wav = Path(tmp) / "a.wav"
        with wave.open(str(wav), "wb") as w:
            voz.synthesize_wav(entrada, w, syn_config=SynthesisConfig(**cfg))
        filtro = RECORTE + ("," + ESTIRA if continuo else "") + ",apad=pad_dur=0.04"
        tmp_mp3 = Path(tmp) / "a.mp3"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(wav), "-af", filtro,
             "-ac", "1", "-ar", "22050", "-codec:a", "libmp3lame", "-b:a", "48k", str(tmp_mp3)],
            check=True,
        )
        shutil.move(str(tmp_mp3), destino)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--voz", default=VOZ_POR_DEFECTO, help=f"voz de Piper (por defecto {VOZ_POR_DEFECTO})")
    ap.add_argument("--hablante", help="hablante en voces con varios (p. ej. F o M en es_ES-sharvard-medium)")
    ap.add_argument("--forzar", action="store_true", help="regenerar todos los audios")
    ap.add_argument("--limpiar", action="store_true", help="borrar MP3 que ya no corresponden a ningún texto")
    ap.add_argument("--lista", action="store_true", help="mostrar los textos y salir")
    a = ap.parse_args()

    d = cargar_datos()
    continuos = {v.lower() for v in d["CONTINUANT"].values()}
    lista = textos(d)

    # clave -> entrada de Piper; dos textos con la misma clave deben sonar igual
    plan = {}
    for t in lista:
        k, e = clave(t), entrada_piper(t, continuos)
        if k in plan and plan[k][1] != e:
            sys.exit(f"Choque de nombres: «{plan[k][0]}» y «{t}» darían {k}.mp3")
        plan.setdefault(k, (t, e))

    if a.lista:
        for k, (t, e) in plan.items():
            print(f"{k:22s} {t:24s} {e if e != t.lower() else ''}")
        print(f"\n{len(plan)} audios")
        return

    if not shutil.which("ffmpeg"):
        sys.exit("Falta ffmpeg (sudo apt install ffmpeg).")

    AUDIO.mkdir(exist_ok=True)
    viejo = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    huellas_viejas = viejo.get("huellas", {})

    voz = None
    cfg = {"length_scale": LENGTH_SCALE}
    ajustes = {"voz": a.voz, "hablante": a.hablante, **cfg}
    huellas, nuevos = {}, 0
    for i, (k, (t, e)) in enumerate(plan.items(), 1):
        huella = hashlib.sha1(json.dumps([e, ajustes, RECORTE, ESTIRA], ensure_ascii=False).encode()).hexdigest()[:12]
        huellas[k] = huella
        destino = AUDIO / f"{k}.mp3"
        if not a.forzar and destino.exists() and huellas_viejas.get(k) == huella:
            continue
        if voz is None:
            voz = cargar_voz(a.voz)
            sid = hablante_id(voz, a.hablante)
            if sid is not None:
                cfg["speaker_id"] = sid
        print(f"[{i}/{len(plan)}] {t} -> {k}.mp3")
        generar(voz, cfg, e, destino, t.lower() in continuos)
        nuevos += 1

    sobran = sorted(p.name for p in AUDIO.glob("*.mp3") if p.stem not in plan)
    if a.limpiar:
        for n in sobran:
            (AUDIO / n).unlink()
    elif sobran:
        print(f"Aviso: {len(sobran)} MP3 que ya no se usan (bórralos con --limpiar): {', '.join(sobran[:10])}")

    MANIFEST.write_text(
        json.dumps({"ajustes": ajustes, "files": sorted(plan), "huellas": huellas}, ensure_ascii=False, indent=1) + "\n",
        encoding="utf-8",
    )
    print(f"Listo: {nuevos} generados, {len(plan) - nuevos} ya estaban. Total {len(plan)} audios.")


if __name__ == "__main__":
    main()
