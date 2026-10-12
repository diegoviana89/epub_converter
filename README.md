# pdf2epub — PDF a EPUB fiel, pensado para Kindle

Conversor local (sin subir nada a internet) que reconstruye el documento en lugar de "pegar" el texto línea a línea.

## Qué arregla frente a los conversores gratuitos

| Problema habitual | Qué hace este programa |
|---|---|
| Texto no justificado / espacios enormes | Reconstruye párrafos reales (une las líneas, quita guiones de fin de línea) y deja que el Kindle justifique e hifene (`text-align: justify`, `hyphens: auto`, idioma detectado). No fuerza fuente ni tamaño: usa los tuyos. |
| Caracteres extraños | Limpia ligaduras (ﬁ→fi), caracteres de uso privado, `(cid:NN)`, acentos sueltos, espacios raros. Si una página sale ilegible, la incluye como imagen en vez de basura. |
| Cabeceras, pies y nº de página en medio del texto | Se detectan por repetición y se eliminan. |
| Dos columnas desordenadas | Detecta columnas y mantiene el orden de lectura. |
| Notas al pie en medio de un párrafo | Se mueven al final del párrafo; los párrafos que cruzan de página se unen. |
| Imágenes borrosas | Se renderizan a 150–300 dpi (máx. 1800 px), fotos en JPEG, dibujos en PNG. Los **gráficos vectoriales** y las **tablas** se convierten en imagen nítida con sus etiquetas. |
| Zoom en imágenes | Cada imagen va en su propio bloque con resolución suficiente: en Kindle se amplía con pulsación larga / doble toque (nativo del lector). |
| Índice | Usa los marcadores del PDF; si no hay, los títulos detectados. Capítulos separados. |

## Instalación

```bash
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
```

## Uso

```bash
python -m pdf2epub libro.pdf                 # crea libro.epub al lado
python -m pdf2epub libro.pdf -o salida.epub -v
python -m pdf2epub carpeta_con_pdfs/ -o epubs/
```

Opciones útiles:

- `--mode pages` — cada página como imagen (fidelidad visual total, sin reflujo; para cómics, partituras, libros con mucha matemática).
- `--tables html` — tablas como texto HTML en vez de imagen.
- `--ocr` — PDFs escaneados (necesita Tesseract: `sudo apt install tesseract-ocr tesseract-ocr-spa`). `--ocr-lang spa+eng`.
- `--keep-headers` — no eliminar cabeceras/pies. `--no-fallback` — no sustituir páginas ilegibles por imagen.
- `--lang es`, `--title`, `--author`, `--max-image-px`, `--jpeg-quality`.

## Enviar al Kindle

Usa **Enviar a Kindle** con el `.epub`, o cópialo por USB con Calibre. Límites de Amazon (pueden cambiar):

| Vía | Tamaño máximo |
|---|---|
| Web [Enviar a Kindle](https://www.amazon.com/sendtokindle) | 200 MB por archivo |
| App *Send to Kindle* (PC o móvil) | 50 MB |
| Correo a tu dirección `@kindle.com` | 50 MB por correo |

Gmail no adjunta archivos de más de 25 MB (los convierte en un enlace de Drive, que Amazon no acepta), y Outlook se queda en 20 MB: para EPUB grandes usa la web.

## Pruebas

```bash
pip install pytest epubcheck && pytest -q tests
```

Genera un PDF difícil (guiones, cabeceras, foto, gráfico, tabla, dos columnas), lo convierte y valida el EPUB con EPUBCheck.

## Limitaciones conocidas

- PDFs con matemáticas complejas, partituras o maquetación muy artística: usa `--mode pages` o revisa el resultado.
- Los umbrales de detección de párrafos/títulos son heurísticos; si un libro concreto sale mal, el modo `-v` muestra lo que se detectó y es fácil ajustarlos en `pdf2epub/analyze.py`.
- OCR: calidad limitada a la del Tesseract instalado.
