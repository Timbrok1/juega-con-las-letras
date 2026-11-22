# Juega con las letras

Web para que un niño de Infantil practique lectoescritura en casa, desde el móvil y con el dedo.

**Jugar:** https://timbrok1.github.io/juega-con-las-letras/

## Juegos
- **Tren de sílabas**: junta consonante + vocal y escucha la sílaba.
- **Caza la sílaba**: escucha una sílaba y toca la burbuja correcta.
- **Construye la palabra**: ordena las sílabas de la palabra que suena.
- **Lee y elige**: lee la palabra (sin audio) y elige el dibujo.
- **Mis amigos**: cada 5 ⭐ se desbloquea un amigo.

Panel de padres: mantener pulsado ⚙️ 1,5 s (letras activas, mayúsculas/minúsculas, fuente, voz y progreso).

## Uso
Es una web estática sin dependencias (`index.html`, `data.js` y la carpeta `audio/`). Hay que servirla con un servidor estático (por ejemplo GitHub Pages): abriendo el archivo directamente, los audios no cargan y se usa la voz del sistema.

```bash
python3 -m http.server 8000
# abrir http://localhost:8000
```

El progreso se guarda en `localStorage` del navegador.

## Audios
Todo lo que dice el juego está pregrabado en `audio/` con [Piper](https://github.com/OHF-Voice/piper1-gpl) (voz neuronal local y gratuita). Al añadir palabras o frases en `data.js`, regenera lo que falte:

```bash
python3 -m venv ~/.venvs/juego-lectura
~/.venvs/juego-lectura/bin/pip install -r tools/requirements.txt   # una vez (requiere ffmpeg)
~/.venvs/juego-lectura/bin/python tools/generar_audios.py          # solo genera lo nuevo
```

## Publicación
Se publica con GitHub Pages desde la rama `main` (carpeta raíz). Cada `git push` actualiza la web en uno o dos minutos.
