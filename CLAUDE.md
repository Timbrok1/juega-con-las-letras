# Juega con las letras

Web para que un niño de Infantil practique lectoescritura en casa, siguiendo el ritmo del método Cokitos del colegio. Se usa en el móvil (iPhone), con el dedo.

## Estado actual

Todo está en un único `index.html` (HTML + CSS + JS, sin build ni dependencias). Solo carga de fuera las fuentes Andika y Nunito desde Google Fonts.

### Juegos
- **Tren de sílabas**: elige consonante + vocal, pulsa «Juntar» y suena la sílaba. 1 ⭐ cada 3 uniones.
- **Caza la sílaba**: suena una sílaba y toca la burbuja correcta (2 opciones las 5 primeras rondas, luego 3).
- **Construye la palabra**: dibujo (emoji) + palabra hablada; toca las sílabas en orden. Incluye 1–2 sílabas distractoras.
- **Lee y elige**: palabra escrita SIN audio, elige el dibujo entre 3. Tras 2 fallos lee las sílabas despacio (nunca la palabra entera).
- **Mis amigos**: cada 5 ⭐ se desbloquea un personaje (emoji genérico).

Descartados por decisión del padre: trazar letras (difícil en móvil) y Memory (no le gustó).

### Panel de padres
Se abre manteniendo pulsado ⚙️ 1,5 s. Permite:
- Activar consonantes (todas, incluidas CH, LL, Ñ, RR, Q). Las vocales siempre están activas.
- Mayúsculas / minúsculas.
- Fuente: Andika (por defecto), Nunito o la del sistema.
- Voz en español y velocidad.
- Reiniciar el progreso.

### Lógica clave
- `WORDS`: lista de palabras `{w, s:[sílabas], e:emoji}`. Una palabra solo aparece si todas sus letras están activas.
- `tokens()`: trata CH, LL y RR como letras propias; QU cuenta como Q, y GU delante de E/I cuenta como G.
- `strip()`: quita las tildes pero conserva la Ñ.
- `syl(c, v)`: Q solo forma QUE/QUI.
- `say()`: Web Speech API (`speechSynthesis`), prefiere voces es-ES "mejoradas". Lleva una pausa de 150 ms tras `cancel()` porque iOS se come la frase.
- `modalOn`: mientras se muestra un amigo nuevo, el juego no habla; al cerrar, se repite el sonido pendiente.

### Persistencia
- Siempre se guarda en `localStorage` (clave `lecturaCasa`).
- Cuando se sirve como artefacto de claude.ai, además usa la capacidad `db` (`claude.use('db')`, documento `data/users/<id>/progreso`). Fuera de claude.ai `window.claude` no existe y solo queda `localStorage`, que en local funciona bien.
- Si se aloja en otro sitio (GitHub Pages, etc.) y se quiere sincronizar entre dispositivos, hay que sustituir `initRemote()` por otro backend.

## Problema pendiente: la voz

En iOS (Safari y la app de Claude), `speechSynthesis.getVoices()` solo expone voces básicas (por ejemplo Mónica compacta). Las voces "Mejoradas/Premium" descargadas (Jorge) y Siri NO están disponibles para webs. Suena robótico, sobre todo en sílabas sueltas.

Solución prevista: pregenerar todos los audios con una voz neuronal y reproducirlos como archivos.
1. Hacer un script que recorra todas las sílabas (`sylPool` con todas las consonantes) y todas las palabras de `WORDS`, más las frases fijas («¡Muy bien!», «¡Tienes un nuevo amigo!», «¡Bien!») y los sonidos continuos (`CONTINUANT`). Debe generar un archivo por texto, p. ej. `audio/<texto-normalizado>.mp3`.
2. Motor: Piper en local (voces es_ES, gratis) o una API en la nube (Google Cloud TTS, ElevenLabs, Azure) si se quiere más calidad.
3. En `say()`: si existe el audio para ese texto, reproducirlo con `Audio`; si no, usar `speechSynthesis` como respaldo.
4. Hacer el script idempotente, para que al añadir palabras solo genere lo que falte.

Ojo con «¡Muy bien! pa»: hoy se dice en una sola frase. Con audios hay que reproducir dos archivos seguidos.

## Restricciones de diseño
- Público: niño de 4–5 años que aún no lee instrucciones. Todo debe entenderse con audio e iconos.
- Botones grandes, solo toques (nada de arrastrar ni trazar).
- El error no se castiga: vibra y se repite el sonido.
- No usar personajes, dibujos ni la tipografía de Cokitos ni de otras marcas (Pokémon, etc.); solo emojis genéricos o personajes propios.
- La fuente es configurable porque la de Cokitos no es pública. Cuando pasen a minúsculas o letra ligada, comparar con el cuaderno.

## Ideas de juegos no implementadas
- ¿Con qué empieza?: dibujo + palabra, elegir la primera sílaba.
- La sílaba que falta: PA __ con el dibujo del pato.
- Palmas: contar las sílabas de una palabra.
