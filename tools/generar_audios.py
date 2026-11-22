#!/usr/bin/env python3
"""Genera los audios del juego.

Lee data.js y crea un MP3 por cada texto que el juego puede decir:
vocales, sílabas de todas las consonantes, palabras y sus sílabas,
nombres de las letras (eme, ele...) y frases fijas.

Motores:
  - google (por defecto): voz «es-ES-Chirp3-HD-Aoede» de Google Cloud Text-to-Speech,
    nativa de España. Necesita GOOGLE_TTS_API_KEY en el archivo .env de la raíz.
  - elevenlabs: voz «Sarah» con el modelo eleven_v3 (acento inglés). ELEVENLABS_API_KEY en .env.
    Las respuestas de los motores en la nube se guardan en una caché local
    (~/.cache/juego-lectura) para no gastar dos veces.
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
    python tools/generar_audios.py --motor piper      # usar Piper (local) o --motor elevenlabs

Requisitos: ffmpeg en el PATH; para Piper, pip install -r tools/requirements.txt
"""
import argparse
import array
import base64
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

# Google Cloud Text-to-Speech: voz por defecto. Elegida a ciegas entre 11 voces nativas
# de España de Google y la de ElevenLabs (que sonaba a acento inglés).
GG_VOZ = "es-ES-Chirp3-HD-Aoede"
GG_IDIOMA = "es-ES"

# ElevenLabs (alternativa): Sarah es una voz de origen inglés; las nativas de España
# de la biblioteca no se pueden usar por API en el plan gratuito.
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
    out.extend(d["LETTER_NAMES"].values())
    out.extend(d["PHRASES"].values())
    vistos, res = set(), []
    for t in out:
        if t.lower() not in vistos:
            vistos.add(t.lower())
            res.append(t)
    return res


def quitar_tildes(t):
    t = unicodedata.normalize("NFD", t)
    return unicodedata.normalize("NFC", "".join(c for c in t if unicodedata.category(c) != "Mn" or c == "\u0303"))


def es_silaba(t):
    """Una sola palabra con un solo grupo de vocales (MA, PAN, FUE, ÓN)."""
    return bool(re.fullmatch(r"[a-zñáéíóúü]+", t)) and len(re.findall(r"[aeiouáéíóúü]+", t)) == 1


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

class Google:
    nombre = "google"

    def __init__(self):
        self.key = leer_env("GOOGLE_TTS_API_KEY")
        if not self.key:
            sys.exit("Falta GOOGLE_TTS_API_KEY en el archivo .env de la raíz del proyecto.")
        self.cache = CACHE / "google"
        self.cache.mkdir(parents=True, exist_ok=True)
        self.gastado = 0

    def ajustes(self):
        return {"motor": self.nombre, "voz": GG_VOZ, "idioma": GG_IDIOMA, "silabas": "Mayuscula-punto-v1", "continuos": "recorte-silaba-v4"}

    def entrada(self, texto, continuos):
        """Texto que se le pide a Google.

        Chirp 3 HD lee como siglas muchas sílabas sueltas («ga» -> «ge a», «ón» ->
        «o con acento agudo ene», «rra» -> «erre erre a»). Con mayúscula inicial,
        sin tilde y con punto («Ga.», «On.») las lee como una palabra. La R inicial
        ya es fuerte en español, así que RRA se pide como «Ra.»."""
        t = unicodedata.normalize("NFC", texto.lower())
        if t in continuos:
            return t  # se construyen aparte (ver _continuo)
        t = re.sub(r"^rr", "r", t)
        if es_silaba(t):
            return quitar_tildes(t).capitalize() + "."
        return t

    def _cache(self, entrada):
        # solo lo que cambia la respuesta de Google (no los ajustes de postproceso)
        h = hashlib.sha1(json.dumps([entrada, GG_VOZ, GG_IDIOMA], ensure_ascii=False).encode()).hexdigest()[:16]
        return self.cache / f"{h}.mp3"

    def olvidar(self, entrada):
        self._cache(entrada).unlink(missing_ok=True)

    def _pedir(self, texto):
        body = {"input": {"text": texto}, "voice": {"languageCode": GG_IDIOMA, "name": GG_VOZ},
                "audioConfig": {"audioEncoding": "MP3", "sampleRateHertz": 44100}}
        url = "https://texttospeech.googleapis.com/v1/text:synthesize?key=" + self.key
        for intento in range(6):
            req = urllib.request.Request(url, data=json.dumps(body).encode(), headers={"Content-Type": "application/json"})
            try:
                with urllib.request.urlopen(req, timeout=120) as f:
                    datos = base64.b64decode(json.load(f)["audioContent"])
                self.gastado += len(texto)
                return datos
            except urllib.error.HTTPError as e:
                detalle = e.read().decode(errors="replace")[:300]
                if e.code in (429, 500, 502, 503, 504) and intento < 5:
                    time.sleep(2 * 2 ** intento)
                    continue
                sys.exit(f"Google respondió {e.code}: {detalle}")

    def _obtener(self, entrada):
        """MP3 de la caché o pedido a Google, comprobando que tiene voz y que una
        sílaba no ha salido deletreada (una sílaba dura < 0,8 s; deletreada, más)."""
        c = self._cache(entrada)
        silaba = entrada.endswith(".") and es_silaba(entrada[:-1].lower())
        def vale(p):
            if not tiene_voz(p):
                return False
            if silaba:
                z = zona_de_voz(p)
                return z is not None and z[1] - z[0] < 0.8
            return True
        if c.exists() and not vale(c):
            c.unlink()
        if not c.exists():
            base = entrada[:-1] if silaba else entrada
            # Google a veces devuelve silencio o deletrea: se prueba con variantes que
            # suenan igual, y la serie se repite porque la misma petición no siempre
            # da el mismo resultado
            variantes = [entrada, "¡" + base + "!", '"' + base.lower() + '"', base.lower() + "."]
            if re.fullmatch(r"[aeiou]", base.lower()):
                variantes.append(base + "h.")
            tmp = c.with_suffix(".part.mp3")
            for texto in variantes * 3:
                tmp.write_bytes(self._pedir(texto))
                if vale(tmp):
                    break
            else:
                tmp.unlink(missing_ok=True)
                sys.exit(f"Google no da un audio válido para «{entrada}».")
            tmp.replace(c)
        return c

    def _continuo(self, entrada, salida):
        """Sonidos largos (mmm, sss…). M y N salen bien pidiendo «Mmmmmm.»; el resto
        Google lo deletrea, así que se recorta la consonante del principio de la
        sílaba («Sa.») y se alarga sin cambiar el tono."""
        letra = entrada[0]
        if letra in "mn":
            # el zumbido sale bien pidiéndolo tal cual; solo se alarga hasta ~0,9 s
            src = self._obtener(letra.upper() + letra * 5 + ".")
            z = zona_de_voz(src)
            a, b = z
            ganancia = 0.0
            return self._estirar(src, a, b, ganancia, salida)
        silaba = self._obtener(letra.upper() + "a.")
        env = envolvente(silaba)
        z = zona_de_voz(silaba)
        pico = max(env)
        # la vocal empieza donde el volumen llega a 6 dB del pico
        voc = next((i for i in range(len(env)) if env[i] >= pico - 6), len(env))
        # la consonante, desde que hay algo de sonido (> -55 dB, hasta 0,2 s antes)
        ini = voc - 1
        while ini > 0 and voc - ini < int(0.2 / VENTANA) and env[ini - 1] > -55:
            ini -= 1
        a, b = ini * VENTANA, voc * VENTANA
        largo = b - a
        # suelta, la consonante suena flojita: se sube hasta 6 dB por debajo de la vocal
        seg = env[int(a / VENTANA):int(b / VENTANA)] or [pico]
        ganancia = max(0.0, min(24.0, (pico - 6) - max(seg)))
        return self._estirar(silaba, a, b, ganancia, salida)

    def _estirar(self, src, a, b, ganancia, salida):
        """Recorta [a, b] de src y lo alarga hasta unos 0,9 s sin cambiar el tono."""
        factor = max(0.03, min(1.0, (b - a) / 0.9))
        cadena = []
        while factor < 0.5:
            cadena.append("atempo=0.5")
            factor /= 0.5
        cadena.append(f"atempo={factor:.3f}")
        wav = salida.with_suffix(".wav")
        subprocess.run(["ffmpeg", "-v", "error", "-y", "-i", str(src), "-af",
                        f"atrim=start={a:.3f}:end={b:.3f},asetpts=PTS-STARTPTS,volume={ganancia:.1f}dB," + ",".join(cadena) +
                        ",afade=t=in:d=0.08,areverse,afade=t=in:d=0.2,areverse", str(wav)], check=True)
        return wav

    def sintetizar(self, entrada, salida, continuo):
        return self._continuo(entrada, salida) if continuo else self._obtener(entrada)


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
            tmp = c.with_suffix(".part.mp3")
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
    elif continuo and origen.suffix == ".wav":  # sonido largo ya recortado (Google)
        filtro = "anull"
    else:  # nube: se corta justo la zona de voz
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
    ap.add_argument("--motor", choices=["google", "elevenlabs", "piper"], default="google")
    ap.add_argument("--voz", default=PIPER_VOZ, help=f"voz de Piper (por defecto {PIPER_VOZ})")
    ap.add_argument("--hablante", help="hablante de Piper en voces con varios (p. ej. F en es_ES-sharvard-medium)")
    ap.add_argument("--rehacer", nargs="+", metavar="TEXTO", help="volver a pedir estos textos (otra toma)")
    ap.add_argument("--forzar", action="store_true", help="regenerar todos los audios")
    ap.add_argument("--limpiar", action="store_true", help="borrar MP3 que ya no corresponden a ningún texto")
    ap.add_argument("--lista", action="store_true", help="mostrar los textos y salir")
    a = ap.parse_args()

    d = cargar_datos()
    continuos = {v.lower() for v in d.get("CONTINUANT", {}).values()}  # sonidos largos (ya no se usan)
    lista = textos(d)

    if a.lista:
        for t in lista:
            print(f"{clave(t):28s} {t}")
        print(f"\n{len(lista)} audios, {sum(len(t) for t in lista)} caracteres")
        return

    if not shutil.which("ffmpeg"):
        sys.exit("Falta ffmpeg (sudo apt install ffmpeg).")
    motor = {"google": Google, "elevenlabs": ElevenLabs}[a.motor]() if a.motor != "piper" else Piper(a.voz, a.hablante)
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
    gasto = f" Caracteres enviados a {motor.nombre}: {motor.gastado}." if motor.nombre != "piper" else ""
    print(f"Listo: {nuevos} generados, {len(plan) - nuevos} ya estaban. Total {len(plan)} audios.{gasto}")


if __name__ == "__main__":
    main()
