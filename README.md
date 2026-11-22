# Juega con las letras

Web para que un niño de Infantil practique lectoescritura en casa, desde el móvil y con el dedo.

## Juegos
- **Tren de sílabas**: junta consonante + vocal y escucha la sílaba.
- **Caza la sílaba**: escucha una sílaba y toca la burbuja correcta.
- **Construye la palabra**: ordena las sílabas de la palabra que suena.
- **Lee y elige**: lee la palabra (sin audio) y elige el dibujo.
- **Mis amigos**: cada 5 ⭐ se desbloquea un amigo.

Panel de padres: mantener pulsado ⚙️ 1,5 s (letras activas, mayúsculas/minúsculas, fuente, voz y progreso).

## Uso
Es un único `index.html` sin dependencias: basta con abrirlo en el navegador o servirlo con cualquier servidor estático (por ejemplo GitHub Pages).

```bash
python3 -m http.server 8000
# abrir http://localhost:8000
```

El progreso se guarda en `localStorage` del navegador.
