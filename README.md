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
Es una web estática sin dependencias ni recursos externos (`index.html`, `data.js`, `audio/`, `fonts/`, `icons/` y el service worker `sw.js`). Hay que servirla con un servidor estático (por ejemplo GitHub Pages): abriendo el archivo directamente, los audios no cargan y se usa la voz del sistema.

```bash
python3 -m http.server 8000
# abrir http://localhost:8000
```

El progreso se guarda en `localStorage` del navegador.

### Instalar en el iPhone
Abre la web en Safari → **Compartir** → **Añadir a pantalla de inicio**. Se abre a pantalla completa y, tras la primera carga con internet, funciona sin conexión (guarda los audios en el móvil). La app instalada lleva su propio progreso, distinto del de Safari.

## Audios
Todo lo que dice el juego está pregrabado en `audio/` con la voz «Sarah» de [ElevenLabs](https://elevenlabs.io) (modelo v3, en español). Al añadir palabras o frases en `data.js`, regenera lo que falte:

```bash
# una vez: crea .env en la raíz con la línea  ELEVENLABS_API_KEY=sk_...
python3 tools/generar_audios.py                 # solo genera lo nuevo (requiere ffmpeg)
python3 tools/generar_audios.py --rehacer ma    # otra toma de un audio que suene mal
```

Alternativa gratuita y local (peor calidad): `--motor piper` (ver `tools/requirements.txt`).

## Publicación
Se publica con GitHub Pages desde la rama `main` (carpeta raíz). Cada `git push` actualiza la web en uno o dos minutos.
