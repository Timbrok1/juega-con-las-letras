# Juega con las letras

Web para que un niño de Infantil practique lectoescritura en casa, siguiendo el ritmo del método Cokitos del colegio. Se usa en el móvil (iPhone), con el dedo.

## Repositorio y publicación
- GitHub (público): https://github.com/Timbrok1/juega-con-las-letras
- Web (GitHub Pages, rama `main`, raíz): https://timbrok1.github.io/juega-con-las-letras/
- En GitHub Pages `window.claude` no existe: el progreso solo se guarda en `localStorage`.

## Estado actual

Sin build ni dependencias y sin nada cargado de fuera:
- `index.html`: HTML + CSS + JS del juego.
- `data.js`: letras, palabras y frases, en JSON dentro de `window.DATA=`.
- `audio/`: MP3 pregenerados y `manifest.json`.
- `fonts/`: Andika 700 y Nunito (variable) en woff2, alojadas aquí con sus licencias OFL.
- `icons/` y `manifest.webmanifest`: app instalable. Los iconos se dibujan con `tools/generar_iconos.py` (Pillow).
- `sw.js`: service worker para usarla sin conexión.

### Juegos
- **Instrucciones habladas** (`PHRASES.instr*`): suenan la primera vez que entra en cada juego en la visita (`introSeen`) y con el botón ❓ de la cabecera. En Tren, Lee y Amigos no suenan si ya ha tocado algo (`tappedSince()`), para no cortarle. En Caza y Construye van seguidas de la sílaba o palabra.
- **Tren de sílabas**: elige consonante + vocal, pulsa «Juntar» y suena la sílaba. 1 ⭐ cada 3 sílabas *distintas* (en `tSeen`, se reinicia al recargar la web). Con QU se desactivan A, O y U.
- **Caza la sílaba**: suena una sílaba y toca la burbuja correcta 2 opciones; 3 tras 3 aciertos a la primera seguidos y 4 tras 6 (`cStreak`; un fallo baja un nivel). ⭐ solo si acierta a la primera. No repite la misma sílaba dos veces seguidas.
- **Construye la palabra**: dibujo (emoji) + palabra hablada; toca las sílabas en orden. Incluye 1–2 sílabas distractoras, y una más tras 3 palabras seguidas sin fallos (`pStreak`). ⭐ si la completa con 1 fallo como mucho.
- **Lee y elige**: palabra escrita SIN audio, elige el dibujo entre 3 (4 tras 4 aciertos seguidos, `lStreak`). Tras 2 fallos lee las sílabas despacio (nunca la palabra entera). ⭐ solo si acierta a la primera.
- Si acierta tras fallar: «¡Muy bien!» y animación verde, pero sin estrella ni confeti.
- **Mis amigos**: cada 5 ⭐ se desbloquea un personaje (emoji genérico).

Descartados por decisión del padre: trazar letras (difícil en móvil) y Memory (no le gustó).

### Panel de padres
Se abre manteniendo pulsado ⚙️ 1,5 s. Permite:
- Activar consonantes (todas, incluidas CH, LL, Ñ, RR, Q). Las vocales siempre están activas.
- «Activar hasta la letra…»: activa todas las letras hasta esa en el orden `ORDER` de `data.js`. Es un orden habitual de cartilla, no el oficial de Cokitos; ajustarlo si el cuaderno sigue otro. La última letra activada queda en `S.newest`.
- Tipos de sílaba permitidos en las palabras (`S.sylTypes`): las directas siempre; opcionalmente con letra al final, trabadas y dos vocales juntas. Por defecto solo directas.
- «Lo que más le cuesta» (según el historial) y botón para borrar el historial.
- Mayúsculas / minúsculas.
- Fuente: Andika (por defecto), Nunito o la del sistema.
- Velocidad de la voz, voz del sistema de respaldo y cuántos audios hay grabados.
- Reiniciar el progreso.

### Lógica clave
- `WORDS` (en `data.js`): lista de palabras `{w, s:[sílabas], e:emoji}`. Una palabra solo aparece si todas sus letras están activas.
- `tokens()`: trata CH, LL y RR como letras propias; QU cuenta como Q, y GU delante de E/I cuenta como G.
- `strip()`: quita las tildes pero conserva la Ñ.
- `syl(c, v)`: Q solo forma QUE/QUI.
- `sound()`: clave fonética. Dos sílabas con la misma clave suenan igual (BA/VA, CA/KA, QUE/KE, GE/JE, GI/JI, CE/ZE, LLA/YA, HA/A, RA/RRA). Ni «Caza» ni las distractoras de «Construye» muestran nunca dos opciones con la misma clave.
- `sylType()`: clasifica una sílaba en directa (MA, QUE, LLU, A), cerrada (SOL, ÓN), trabada (FRE) o diptongo (FUE, HUE, VIA). `wordTypes()` da los tipos no directos de una palabra. Hoy: 71 palabras solo directas, 14 con cerradas, 4 con diptongo y 2 trabadas.
- **Repaso adaptativo**: `rec(clave, acierto)` guarda en `S.stats[clave]={e,n}`, donde `e = e*0.7 + (fallo?1:0)` (los fallos se van olvidando). Claves: `s:MA` (Caza, acierto a la primera), `w:PATO` (Construye, sin fallos) y `l:PATO` (Lee, a la primera). `pickW()` elige con peso `weight()`: 1+3e (máximo 6); lo nunca visto, 1,5; y ×2 si contiene `S.newest`.
- `say()` / `sayAll()`: reproducen los MP3 de `audio/` y, si falta alguno, usan `speechSynthesis` (prefiere voces es-ES "mejoradas"). Pausa de 150 ms tras `cancel()` porque iOS se come la frase. Ver «Voz: audios pregenerados».
- `modalOn`: mientras se muestra un amigo nuevo, el juego no habla; al cerrar, se repite el sonido pendiente.

### Persistencia
- Siempre se guarda en `localStorage` (clave `lecturaCasa`).
- `resetAt`: fecha del último reinicio. Al juntar el progreso local con el remoto, gana el lado reiniciado más tarde; si coinciden, el que tenga más estrellas.
- Cuando se sirve como artefacto de claude.ai, además usa la capacidad `db` (`claude.use('db')`, documento `data/users/<id>/progreso`). Fuera de claude.ai `window.claude` no existe y solo queda `localStorage`, que en local funciona bien.
- Si se aloja en otro sitio (GitHub Pages, etc.) y se quiere sincronizar entre dispositivos, hay que sustituir `initRemote()` por otro backend.

## Voz: audios pregenerados
En iOS, `speechSynthesis` solo ofrece a las webs voces básicas (las Mejoradas/Premium y Siri no están disponibles), así que todo lo que dice el juego está grabado en `audio/*.mp3` con Piper (voz neuronal local).

- **Generador**: `tools/generar_audios.py`. Lee `data.js` y crea un MP3 por texto: vocales, sílabas de todas las consonantes, palabras y sus sílabas, `CONTINUANT` y `PHRASES`. Es idempotente: solo regenera lo que falta o cambia (texto, fonemas, voz o ajustes). Escribe `audio/manifest.json` con `files` y `huellas`.
- **Instalación** (una vez): `python3 -m venv ~/.venvs/juego-lectura && ~/.venvs/juego-lectura/bin/pip install -r tools/requirements.txt`. Hace falta `ffmpeg`. Las voces se descargan solas en `~/.local/share/piper-voces` (o en `$PIPER_VOCES`).
- **Uso**: `~/.venvs/juego-lectura/bin/python tools/generar_audios.py` (opciones `--lista`, `--forzar`, `--limpiar`, `--voz`, `--hablante`). Voz por defecto `es_ES-davefx-medium` (masculina); alternativa `--voz es_ES-sharvard-medium --hablante F` (femenina).
- **Al añadir palabras o frases a `data.js`, hay que ejecutar el generador** y subir los MP3 nuevos y el manifest.
- **Fonemas forzados** (`entrada_piper()`): Piper deletrea algunas sílabas sueltas («rra» → «erre erre a», «xi» → «once», «mmm» → «eme eme eme»). Para esas se le pasan fonemas `[[...]]`. Los sonidos continuos se generan cortos y se estiran ×4 con `atempo` de ffmpeg (sin cambiar el tono). Si se añade una sílaba rara, revisar con `--lista` y con `PiperVoice.phonemize()`.
- **Nombres de archivo**: `clave()` en Python y `akey()` en `index.html` deben dar lo mismo (minúsculas, `ñ`→`ny`, vocal con tilde → vocal + `_`, el resto de signos → `-`). Ej.: `MAMÁ` → `mama_.mp3`, `¡Muy bien!` → `muy-bien.mp3`.
- **En el juego**: `say(t)` / `sayAll([partes], rate, force, gap)`. Usan un único elemento `<audio>` reutilizado, que se desbloquea en iOS con el primer toque (silencio). Si no hay MP3 para un texto o falla la reproducción, se usa `speechSynthesis`. La velocidad del panel se aplica con `playbackRate` (0,8 = normal), conservando el tono. `stopVoice()` corta lo que suene; `sayGen` invalida las colas anteriores. Al arrancar se precargan los audios de las letras activas.
- «¡Muy bien!» + sílaba/palabra y la ayuda de «Lee y elige» (sílabas despacio) se dicen con `sayAll` como archivos seguidos.
- La voz del sistema elegida en el panel de padres solo se usa como respaldo.

## App instalable y sin conexión (PWA)
- En el iPhone: Safari → Compartir → «Añadir a pantalla de inicio». Abre a pantalla completa. **La app instalada tiene su propio `localStorage`, distinto del de Safari**: el progreso no pasa de uno a otro.
- `sw.js`:
  - Archivos de la app (`index.html`, `data.js`, manifest…): primero la red, con 3 s de margen; si no, la caché. Los cambios publicados llegan solos sin tocar `VERSION`.
  - Audios: primero la caché `media`. La URL lleva `?v=<huella>`, así que un audio regenerado se descarga de nuevo.
  - Fuentes e iconos: primero la caché.
  - Al arrancar, la página manda `'sync'` al service worker, que descarga los audios que falten (6 a la vez) y borra los que ya no estén en el manifest. Va informando del progreso con `postMessage({type:'audio',done,total})`.
  - Safari pide los audios por trozos (`Range`): `media()` responde con 206. Si se toca, no romper esto o los audios no sonarán sin conexión en iOS.
  - **Subir `VERSION` en `sw.js` si cambia el propio `sw.js` o la lista `APP`** (por ejemplo, al añadir un archivo nuevo a la app).
- El panel de padres muestra cómo instalarla y si ya está lista para usar sin conexión (cuenta lo que hay en la caché `media`).
- Se pide `navigator.storage.persist()` para que el navegador no borre el progreso ni los audios.
- Sincronizar entre dispositivos sigue pendiente: habría que sustituir `initRemote()` por un servicio externo (Firebase, Supabase…).

## Pruebas
- `tools/test_e2e.py`: prueba de punta a punta en Chromium sin interfaz (Playwright). Comprueba el service worker, que se guarden los 253 audios, las fuentes locales, las peticiones Range, el sonido en todos los juegos y el panel de padres, y luego repite todo sin conexión. Instalación en el propio script. Ejecutarla tras cada cambio: `~/.venvs/juego-lectura/bin/python tools/test_e2e.py`.
- En las capturas, los emojis salen como cuadros porque el Chromium de WSL no tiene fuente de emojis; en el iPhone se ven bien.
- Andika solo se descarga cuando hay en pantalla algo con la clase `.L`; para comprobarla hay que usar `document.fonts.load()`, no `check()`.

## Restricciones de diseño
- Público: niño de 4–5 años que aún no lee instrucciones. Todo debe entenderse con audio e iconos.
- Botones grandes, solo toques (nada de arrastrar ni trazar).
- El error no se castiga: el botón tiembla y se repite el sonido. (iOS no permite vibrar desde una web.)
- No usar personajes, dibujos ni la tipografía de Cokitos ni de otras marcas (Pokémon, etc.); solo emojis genéricos o personajes propios.
- La fuente es configurable porque la de Cokitos no es pública. Cuando pasen a minúsculas o letra ligada, comparar con el cuaderno.

## Ideas de juegos no implementadas
- ¿Con qué empieza?: dibujo + palabra, elegir la primera sílaba.
- La sílaba que falta: PA __ con el dibujo del pato.
- Palmas: contar las sílabas de una palabra.
