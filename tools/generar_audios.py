#!/usr/bin/env python3
"""Genera los audios del juego.

Lee data.js y crea un MP3 por cada texto que el juego puede decir:
vocales, sílabas de todas las consonantes, palabras y sus sílabas,
sonidos continuos (mmm, sss...) y frases fijas.

Motores:
  - elevenlabs (por defecto): voz «Sarah» con el modelo eleven_v3 en español.
    Necesita ELEVENLABS_API_KEY en el archivo .env de la raíz (nunca se sube a git).
    Las respuestas se guardan en una caché local para no gastar créditos dos veces.
  - piper: voz neuronal local y gratuita (peor calidad). pip install piper-tts

Es idempotente: solo genera lo que falta o lo que ha cambiado (texto, motor,
voz o ajustes). Al terminar escribe audio/manifest.json, que el juego usa para
saber qué audios existen; la «huella» de cada audio es un resumen de su
contenido, así el navegador solo vuelve a descargar los que cambian.

Uso:
    python tools/generar_audios.py                    # genera lo que falte
    python tools/generar_audios.py --lista            # solo muestra los textos
    python tools/generar_audios.py --rehacer ma xi    # vuelve a pedir esos textos (otra toma)
    python tools/generar_audios.py --forzar           # lo regenera todo (usa la caché)
    python tools/generar_audios.py --limpiar          # borra MP3 que ya no se usan
    python tools/generar_audios.py --motor piper      # usar Piper en lugar de ElevenLabs

Requisitos: ffmpeg en el PATH; para Piper, pip install -r tools/requirements.txt
"""
import argparse
import array
import hashlib
import math
import json
import os
import random
import re
import shutil
import subprocess
import sys
import tempfile
import time
import unicodedata
import urllib.error
import urllib.request
import wave
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
AUDIO = ROOT / "audio"
MANIFEST = AUDIO / "manifest.json"
CACHE = Path(os.environ.get("AUDIO_CACHE", Path.home() / ".cache/juego-lectura"))

# ElevenLabs: elegida a ciegas entre 6 voces (la que sonaba más nativa en las sílabas)
EL_VOZ = "EXAVITQu4vr4xnSDxMaL"  # Sarah (voz de serie, permitida en el plan gratuito)
EL_MODELO = "eleven_v3"
EL_IDIOMA = "es"
EL_FORMATO = "mp3_44100_64"

# Piper
VOCES_DIR = Path(os.environ.get("PIPER_VOCES", Path.home() / ".local/share/piper-voces"))
PIPER_VOZ = "es_ES-davefx-medium"
LENGTH_SCALE = 1.15  # algo más lento que lo normal: es para un niño de 4-5 años
FONEMA_CONTINUO = {"m": "m", "l": "l", "s": "s", "n": "n", "f": "f", "z": "θ", "j": "x"}

# Recorta silencios al principio y al final (deja 40 ms de margen al final).
RECORTE = (
    "silenceremove=start_periods=1:start_threshold=-45dB,areverse,"
    "silenceremove=start_periods=1:start_threshold=-45dB,afade=t=in:d=0.03,areverse"
)
# Piper no sabe alargar un sonido: los continuos se estiran x4 sin cambiar el tono.
ESTIRA = "atempo=0.5,atempo=0.5,areverse,afade=t=in:d=0.25,areverse"


# ---------------------------------------------------------------- análisis de audio

VENTANA = 0.02  # segundos por ventana de volumen


def envolvente(path):
    """Volumen (dB) de cada ventana de 20 ms."""
    sr = 16000
    pcm = subprocess.run(["ffmpeg", "-v", "error", "-i", str(path), "-ac", "1", "-ar", str(sr), "-f", "s16le", "-"],
                         capture_output=True, check=True).stdout
    a = array.array("h")
    a.frombytes(pcm[: len(pcm) // 2 * 2])
    n = int(sr * VENTANA)
    out = []
    for i in range(0, len(a), n):
        w = a[i:i + n]
        rms = math.sqrt(sum(x * x for x in w) / max(1, len(w))) / 32768
        out.append(20 * math.log10(rms) if rms > 0 else -120.0)
    return out


def tiene_voz(path):
    """Hay voz de verdad: un pico claro y al menos 0,12 s de sonido (no un clic suelto)."""
    env = envolvente(path)
    return bool(env) and max(env) > -30 and sum(1 for x in env if x > -40) >= 6


def zona_de_voz(path):
    """(inicio, fin) en segundos de la voz, sin el silencio ni los ruidos sueltos
    (respiraciones, clics) que a veces añade ElevenLabs tras la frase.

    Se agrupan las ventanas con sonido (> -45 dB) en tramos separados por pausas
    de 250 ms o más, y se conservan desde el primer tramo hasta el último que sea
    voz de verdad (su pico está a menos de 20 dB del pico máximo)."""
    env = envolvente(path)
    if not env:
        return None
    pico = max(env)
    tramos, ini, silencio = [], None, 0
    hueco = int(0.25 / VENTANA)
    for i, db in enumerate(env + [-120.0] * (hueco + 1)):
        if db > -45:
            if ini is None:
                ini = i
            fin, silencio = i, 0
        elif ini is not None:
            silencio += 1
            if silencio >= hueco:
                tramos.append((ini, fin))
                ini, silencio = None, 0
    buenos = [t for t in tramos if max(env[t[0]:t[1] + 1]) > pico - 20]
    if not buenos:
        return None
    a, b = buenos[0][0], buenos[-1][1]
    return max(0.0, a * VENTANA - 0.03), (b + 1) * VENTANA + 0.05


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


def leer_env(nombre):
    if os.environ.get(nombre):
        return os.environ[nombre]
    env = ROOT / ".env"
    if env.exists():
        m = re.search(rf"^\s*{nombre}\s*=\s*(\S+)", env.read_text(encoding="utf-8-sig"), re.M)
        if m:
            return m.group(1).strip("\"'")
    return None


# ---------------------------------------------------------------- motores

class ElevenLabs:
    nombre = "elevenlabs"

    def __init__(self):
        self.key = leer_env("ELEVENLABS_API_KEY")
        if not self.key:
            sys.exit("Falta ELEVENLABS_API_KEY en el archivo .env de la raíz del proyecto.")
        self.cache = CACHE / "elevenlabs"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.gastado = 0

    def ajustes(self):
        return {"motor": self.nombre, "voz": EL_VOZ, "modelo": EL_MODELO, "idioma": EL_IDIOMA, "formato": EL_FORMATO}

    def entrada(self, texto, continuos):
        return unicodedata.normalize("NFC", texto.lower())

    def _cache(self, entrada):
        h = hashlib.sha1(json.dumps([entrada, self.ajustes()], ensure_ascii=False).encode()).hexdigest()[:16]
        return self.cache / f"{h}.mp3"

    def olvidar(self, entrada):
        self._cache(entrada).unlink(missing_ok=True)

    def _pedir(self, texto, modelo=EL_MODELO):
        body = {"text": texto, "model_id": modelo, "seed": random.randint(0, 2**31 - 1)}
        if modelo != "eleven_multilingual_v2":
            body["language_code"] = EL_IDIOMA
        url = f"https://api.elevenlabs.io/v1/text-to-speech/{EL_VOZ}?output_format={EL_FORMATO}"
        for intento in range(6):
            req = urllib.request.Request(url, data=json.dumps(body).encode(),
                                         headers={"xi-api-key": self.key, "Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=120) as f:
                    datos = f.read()
                self.gastado += len(texto)
                return datos
            except urllib.error.HTTPError as e:
                detalle = e.read().decode(errors="replace")[:300]
                if e.code in (429, 500, 502, 503, 504) and intento < 5:
                    time.sleep(2 * 2 ** intento)
                    continue
                sys.exit(f"ElevenLabs respondió {e.code}: {detalle}")

    def sintetizar(self, entrada, salida, continuo):
        c = self._cache(entrada)
        if c.exists() and not tiene_voz(c):
            c.unlink()  # respuesta vacía o en silencio guardada antes
        if not c.exists():
            # con textos muy cortos («o», «lll») el modelo a veces devuelve silencio:
            # se reintenta con otra semilla, luego con variantes del texto y, como
            # último recurso, con el modelo multilingüe v2 de la misma voz
            tmp = c.with_suffix(".tmp")
            intentos = [(entrada, EL_MODELO), (entrada, EL_MODELO), (entrada + ".", EL_MODELO), ("¡" + entrada + "!", EL_MODELO)]
            if continuo:
                intentos.insert(2, (entrada + entrada[0] * 4, EL_MODELO))
            intentos += [(entrada, "eleven_multilingual_v2"), (entrada + entrada[0] * 4, "eleven_multilingual_v2")]
            for texto, modelo in intentos:
                tmp.write_bytes(self._pedir(texto, modelo))
                if tmp.stat().st_size >= 1500 and tiene_voz(tmp):
                    break
            else:
                tmp.unlink(missing_ok=True)
                sys.exit(f"ElevenLabs devuelve silencio para «{entrada}» una y otra vez.")
            tmp.replace(c)
        return c  # MP3 tal cual lo devuelve ElevenLabs


class Piper:
    nombre = "piper"

    def __init__(self, voz, hablante):
        from piper import PiperVoice

        VOCES_DIR.mkdir(parents=True, exist_ok=True)
        modelo = VOCES_DIR / f"{voz}.onnx"
        if not modelo.exists():
            print(f"Descargando la voz {voz}…")
            subprocess.run([sys.executable, "-m", "piper.download_voices", "--download-dir", str(VOCES_DIR), voz], check=True)
        self.voz_nombre, self.hablante = voz, hablante
        self.voz = PiperVoice.load(str(modelo))
        self.cfg = {"length_scale": LENGTH_SCALE}
        if hablante is not None:
            mapa = self.voz.config.speaker_id_map or {}
            if hablante in mapa:
                self.cfg["speaker_id"] = mapa[hablante]
            elif hablante.isdigit():
                self.cfg["speaker_id"] = int(hablante)
            else:
                sys.exit(f"Hablante «{hablante}» no existe en esta voz. Opciones: {list(mapa) or 'ninguna'}")
        self.gastado = 0

    def ajustes(self):
        return {"motor": self.nombre, "voz": self.voz_nombre, "hablante": self.hablante, **self.cfg}

    def entrada(self, texto, continuos):
        """Piper (espeak) deletrea algunas sílabas sueltas: «rra» -> «erre erre a»,
        «xi» -> «once» (número romano), «mmm» -> «eme eme eme». Para esas se le
        pasan los fonemas [[...]] directamente."""
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

    def olvidar(self, entrada):
        pass

    def sintetizar(self, entrada, salida, continuo):
        from piper import SynthesisConfig

        wav = salida.with_suffix(".wav")
        with wave.open(str(wav), "wb") as w:
            self.voz.synthesize_wav(entrada, w, syn_config=SynthesisConfig(**self.cfg))
        return wav


def postprocesar(origen, destino, continuo, estirar):
    if estirar:  # Piper: audio limpio, basta con recortar los silencios
        filtro = RECORTE + ("," + ESTIRA if continuo else "") + ",apad=pad_dur=0.04"
    else:  # ElevenLabs: se corta justo la zona de voz
        z = zona_de_voz(origen)
        if z is None:
            sys.exit(f"Sin voz en {origen}")
        filtro = f"atrim=start={z[0]:.3f}:end={z[1]:.3f},asetpts=PTS-STARTPTS,afade=t=in:d=0.01,areverse,afade=t=in:d=0.04,areverse"
    with tempfile.TemporaryDirectory() as tmp:
        out = Path(tmp) / "a.mp3"
        subprocess.run(
            ["ffmpeg", "-v", "error", "-y", "-i", str(origen), "-af", filtro,
             "-ac", "1", "-ar", "44100", "-codec:a", "libmp3lame", "-b:a", "56k", str(out)],
            check=True,
        )
        shutil.move(str(out), destino)


# ---------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--motor", choices=["elevenlabs", "piper"], default="elevenlabs")
    ap.add_argument("--voz", default=PIPER_VOZ, help=f"voz de Piper (por defecto {PIPER_VOZ})")
    ap.add_argument("--hablante", help="hablante de Piper en voces con varios (p. ej. F en es_ES-sharvard-medium)")
    ap.add_argument("--rehacer", nargs="+", metavar="TEXTO", help="volver a pedir estos textos (otra toma)")
    ap.add_argument("--forzar", action="store_true", help="regenerar todos los audios")
    ap.add_argument("--limpiar", action="store_true", help="borrar MP3 que ya no corresponden a ningún texto")
    ap.add_argument("--lista", action="store_true", help="mostrar los textos y salir")
    a = ap.parse_args()

    d = cargar_datos()
    continuos = {v.lower() for v in d["CONTINUANT"].values()}
    lista = textos(d)

    if a.lista:
        for t in lista:
            print(f"{clave(t):28s} {t}")
        print(f"\n{len(lista)} audios, {sum(len(t) for t in lista)} caracteres")
        return

    if not shutil.which("ffmpeg"):
        sys.exit("Falta ffmpeg (sudo apt install ffmpeg).")
    motor = ElevenLabs() if a.motor == "elevenlabs" else Piper(a.voz, a.hablante)
    estirar = motor.nombre == "piper"
    ajustes = motor.ajustes()

    # clave -> (texto, entrada del motor); dos textos con la misma clave deben sonar igual
    plan = {}
    for t in lista:
        k, e = clave(t), motor.entrada(t, continuos)
        if k in plan and plan[k][1] != e:
            sys.exit(f"Choque de nombres: «{plan[k][0]}» y «{t}» darían {k}.mp3")
        plan.setdefault(k, (t, e))

    rehacer = {clave(t) for t in (a.rehacer or [])}
    desconocidos = rehacer - set(plan)
    if desconocidos:
        sys.exit(f"No existen estos textos: {', '.join(sorted(desconocidos))}")

    AUDIO.mkdir(exist_ok=True)
    viejo = json.loads(MANIFEST.read_text(encoding="utf-8")) if MANIFEST.exists() else {}
    recetas_viejas, huellas_viejas = viejo.get("recetas", {}), viejo.get("huellas", {})

    recetas, huellas, nuevos = {}, {}, 0
    try:
        for i, (k, (t, e)) in enumerate(plan.items(), 1):
            continuo = t.lower() in continuos
            receta = hashlib.sha1(json.dumps([e, ajustes, RECORTE if estirar else "zona_de_voz-v2", ESTIRA if estirar and continuo else ""],
                                             ensure_ascii=False).encode()).hexdigest()[:12]
            recetas[k] = receta
            destino = AUDIO / f"{k}.mp3"
            if (not a.forzar and k not in rehacer and destino.exists()
                    and recetas_viejas.get(k) == receta and huellas_viejas.get(k)):
                huellas[k] = huellas_viejas[k]
                continue
            if k in rehacer:
                motor.olvidar(e)
            print(f"[{i}/{len(plan)}] {t} -> {k}.mp3")
            with tempfile.TemporaryDirectory() as tmp:
                origen = motor.sintetizar(e, Path(tmp) / "a", continuo)
                postprocesar(origen, destino, continuo, estirar)
            huellas[k] = hashlib.sha1(destino.read_bytes()).hexdigest()[:12]
            nuevos += 1
    finally:
        # se guarda aunque se interrumpa, para no repetir lo ya hecho
        hechos = sorted(k for k in plan if k in huellas)
        MANIFEST.write_text(
            json.dumps({"ajustes": ajustes, "files": hechos, "huellas": huellas, "recetas": {k: recetas[k] for k in hechos}},
                       ensure_ascii=False, indent=1) + "\n",
            encoding="utf-8",
        )

    sobran = sorted(p.name for p in AUDIO.glob("*.mp3") if p.stem not in plan)
    if a.limpiar:
        for n in sobran:
            (AUDIO / n).unlink()
    elif sobran:
        print(f"Aviso: {len(sobran)} MP3 que ya no se usan (bórralos con --limpiar): {', '.join(sobran[:10])}")
    gasto = f" Caracteres enviados a ElevenLabs: {motor.gastado}." if motor.nombre == "elevenlabs" else ""
    print(f"Listo: {nuevos} generados, {len(plan) - nuevos} ya estaban. Total {len(plan)} audios.{gasto}")


if __name__ == "__main__":
    main()
