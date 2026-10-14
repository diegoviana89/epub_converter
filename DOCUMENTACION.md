# EpubTailor (pdf2epub): documentación técnica

EpubTailor convierte PDF a EPUB 3 pensando en Kindle. No copia el texto línea a línea: **reconstruye la estructura del documento** (párrafos, títulos, figuras, tablas, notas al pie, columnas e índice). Así el lector puede justificar, separar sílabas y aplicar la fuente y el tamaño que elija el usuario.

El proyecto tiene dos partes:

| Parte | Carpeta | Qué es |
|---|---|---|
| Motor de conversión | `pdf2epub/` | Biblioteca de Python y línea de comandos (`python -m pdf2epub`). Funciona sin conexión. |
| Servicio web | `web/` | API Flask y página de inicio estática: el usuario sube un PDF y descarga el EPUB. |

---

## Cómo funciona, en sencillo

Un PDF no guarda párrafos ni capítulos. Solo guarda instrucciones de dibujo: «pon esta palabra, con esta
fuente y este tamaño, en esta posición de la página». El conversor lee esas piezas sueltas con PyMuPDF y
**deduce la estructura** del libro. Cuando el PDF tiene texto digital no hace falta OCR: el texto ya está
dentro del archivo (el OCR es solo para escaneos, ver [§5](#5-ocr)).

Los pasos (el detalle técnico está en [§3](#3-arquitectura-del-motor)):

1. **Leer cada página**: cada línea con su texto, posición, tamaño de letra y si va en negrita, cursiva o
   es código. Con eso la página se clasifica como texto, escaneo, ilegible o en blanco.
2. **Aprender cómo es el libro**: el tamaño de letra más común es el del texto normal (lo más grande serán
   títulos; lo más pequeño, notas), la separación habitual entre líneas y el vocabulario, que sirve para
   saber si un guion a final de línea parte una palabra o es de una palabra compuesta.
3. **Quitar lo que se repite**: lo que aparece arriba o abajo en muchas páginas (título del libro,
   capítulo, número de página) es cabecera o pie, y se elimina.
4. **Separar lo que no es texto corrido**: tablas y gráficas se guardan como imágenes nítidas (y el texto
   que hay dentro no se cuela en los párrafos); se detectan las dos columnas para leer primero la
   izquierda y luego la derecha; las notas al pie se colocan tras el párrafo que las cita.
5. **Unir líneas en párrafos**: para cada línea decide si sigue el párrafo anterior o empieza otro,
   mirando la sangría, el espacio entre líneas, si la anterior acaba en punto y si llega al margen. Quita
   los guiones de partición («conver- / sión» → «conversión»), une los párrafos cortados por un cambio
   de página y reconoce títulos, listas, citas y código.
6. **Limpiar caracteres**: ligaduras (`ﬁ` → `fi`), acentos separados, espacios raros y códigos basura
   como `(cid:12)`.
7. **Armar el libro**: detecta el idioma, divide en capítulos (con el índice del PDF, los títulos
   detectados o, si no hay nada, bloques de unas 25 páginas), genera el índice navegable y la portada, y
   escribe el EPUB.

Ejemplo. Lo que trae el PDF:

```
"Capítulo 3"            (24 pt, negrita)
"La conversión de do-"  (11 pt)
"cumentos es un proce-" (11 pt)
"so complejo."          (11 pt)
"Mi libro — 47"         (9 pt, abajo, repetido en cada página)
```

Lo que sale en el EPUB:

```html
<h1>Capítulo 3</h1>
<p>La conversión de documentos es un proceso complejo.</p>
```

La cabecera desaparece y el texto queda como un párrafo real, sin estilo fijo: el Kindle lo justifica, lo
parte en sílabas y lo muestra con la fuente y el tamaño que elija el lector.

Son decisiones sobre cada línea de cada página más el renderizado de figuras a alta resolución: es lo que
más CPU consume, unos 130 ms por página (ver [RENDIMIENTO.md](RENDIMIENTO.md)). Si una página trae el texto
dañado, se mete entera como imagen para no producir basura.

---

## 1. Stack tecnológico

| Capa | Tecnología | Para qué se usa |
|---|---|---|
| Lenguaje | Python 3 (la imagen Docker usa 3.12) | Todo el backend |
| Lectura de PDF | **PyMuPDF** (`pymupdf>=1.24`, motor MuPDF) | Texto con fuentes y posiciones, imágenes incrustadas, dibujos vectoriales, detección de tablas (`find_tables`), índice del PDF (`get_toc`), renderizado de regiones y páginas, y OCR |
| Imágenes | **Pillow** (`>=10`) | Redimensionado Lanczos, detección de grises, cuantización y codificación JPEG/PNG |
| OCR | **Tesseract OCR**, invocado desde PyMuPDF (`Page.get_textpage_ocr`) | Extraer texto de páginas escaneadas (ver §5) |
| Web | **Flask** (`>=3.0`) | API REST y archivos estáticos |
| Servidor de aplicación | **Gunicorn** (`>=22`) | 2 workers y 600 s de timeout para conversiones largas |
| Frontend | HTML, CSS y JavaScript sin frameworks; Google Fonts (Newsreader, Figtree); logo en SVG | Página de inicio y formulario de subida |
| Contenedor | Docker (`python:3.12-slim` + `tesseract-ocr`, `-spa`, `-eng`) | Despliegue |
| Pruebas | pytest; **EPUBCheck** (paquete `epubcheck`, opcional) | Pruebas de extremo a extremo y validación del EPUB |

El motor solo depende de `pymupdf` y `Pillow` (`requirements.txt`). La web añade `flask` y `gunicorn` (`requirements-web.txt`). El EPUB se escribe a mano con `zipfile`, sin bibliotecas de EPUB.

---

## 2. Estructura del repositorio

```
pdf2epub/
  __main__.py     entrada de `python -m pdf2epub`
  cli.py          argumentos de línea de comandos → Opts
  convert.py      convert(pdf, epub, opts): orquesta el proceso completo
  analyze.py      núcleo: PDF → lista de bloques (párrafos, títulos, figuras…)
  textfix.py      limpieza de caracteres (ligaduras, cid, acentos sueltos…)
  images.py       renderizado y codificación de figuras, páginas y portada
  epub.py         posproceso, idioma, capítulos, índice y escritura del EPUB 3
  model.py        tipos compartidos: Opts, Asset, Block
web/
  app.py          API Flask
  static/         index.html (página de inicio), config.js (dónde está la API) e img/ (logos SVG)
tests/
  make_sample_pdf.py   genera un PDF difícil de convertir
  test_convert.py      pruebas del conversor
  test_web.py          pruebas del servicio web (descarga por partes, temporales, CORS)
deploy/
  config.env           configuración del despliegue
  cloudrun.sh          publica la API en Google Cloud Run
  cloudflare-pages.sh  publica la página en Cloudflare Pages
ejemplo/          PDF de muestra y su EPUB, para comprobaciones manuales
Dockerfile, .dockerignore, .gcloudignore, requirements.txt, requirements-web.txt
```

---

## 3. Arquitectura del motor

```
PDF ──► analyze() ──► list[Block] + Ctx(assets, estadísticas)
            │  pasada 1: extracción y clasificación de páginas (+ OCR)
            │  cabeceras y pies repetidos
            │  pasada 2: columnas, figuras, tablas, notas, párrafos (Flow)
            ▼
        finalize_blocks() ──► detect_lang() ──► plan_book() ──► write_epub() ──► .epub
                                                (capítulos e índice)  (zip EPUB 3)
```

`convert.py::convert()` abre el PDF y rechaza los que tienen contraseña. Después:

- Toma título y autor de las opciones o de los metadatos. Si el título es basura (`.docx`, "Microsoft Word", "Untitled"), lo genera a partir del nombre del archivo.
- Ejecuta el proceso de conversión y renderiza la página 1 como portada.

### 3.1 `analyze.py`: de PDF a bloques

**Pasada 1: extracción.** Para cada página, `extract_lines` obtiene líneas con su texto, fuente, tamaño, negrita, cursiva, superíndice, monoespaciado y enlaces. Después la página se **clasifica**:

| Tipo | Condición | Resultado |
|---|---|---|
| `text` | Caso normal | Se reconstruye el texto |
| escaneada | Menos de 25 caracteres fuera de cabecera y pie, y una imagen que cubre al menos el 80 % de la página | Con `--ocr`: OCR. Sin `--ocr`: imagen de página |
| ilegible | Más del 8 % de "basura" (`textfix.garble_count`: caracteres de uso privado, `�`, `(cid:NN)`) | Imagen de página (salvo con `--no-fallback`) |
| `blank` | Sin texto, sin imágenes y sin dibujos | Se omite |

Esta pasada también reúne **estadísticas globales**, que sirven de referencia a las demás heurísticas:

- tamaño del cuerpo de texto (el tamaño más frecuente),
- interlineado típico (`ctx.lead`, la mediana),
- proporción de texto monoespaciado y de negrita,
- vocabulario del documento, que decide si un guion a final de línea se conserva ("long-term") o se elimina,
- uso de guiones suaves como guiones visibles.

**Cabeceras y pies repetidos.** Se examinan las franjas del 12 % superior e inferior de cada página. Una línea es cabecera o pie si su texto, con los números normalizados (`#`), aparece en al menos el 25 % de las páginas (mínimo 3). También se eliminan los títulos corridos que cambian en cada capítulo pero siempre están a la misma altura junto al número de página, y los números de página sueltos (`PAGE_NUM_RE`). `--keep-headers` desactiva este paso.

**Pasada 2: flujo.** Para cada página de texto:

1. **Tablas.** `page.find_tables()` encuentra las tablas con rejilla. `rule_tables()` encuentra las de estilo *booktabs* (solo filetes horizontales). Se descartan los falsos positivos: recuadros alrededor de prosa y rejillas casi vacías de gráficas.
2. **Regiones gráficas.** `find_regions()` agrupa imágenes incrustadas y dibujos vectoriales (gráficas, diagramas, iconos al margen) en regiones que se renderizan como imagen. **Las líneas de texto dentro de una región se excluyen**, para que las etiquetas de una gráfica no se cuelen en el texto.
3. **Columnas.** `detect_gutter()` encuentra el canal entre dos columnas. Cada línea se asigna a la columna izquierda, a la derecha o a ninguna (cuando cruza el canal). El orden de lectura es columna izquierda, después derecha, y en cada elemento a todo lo ancho se hace un corte.
4. **Notas al pie.** Las líneas pequeñas al final de la página (como mucho el 90 % del cuerpo y por debajo del 55 % de la altura) se separan y se insertan como bloques `fn` **después del párrafo** que las cita.
5. **`Flow`**: une las líneas en párrafos usando sangría, interlineado, puntuación final y márgenes de la columna. También:
   - elimina los guiones de fin de línea,
   - une párrafos que cruzan de página o de columna,
   - detecta títulos por tamaño y negrita, listas, citas, bloques de código, texto centrado y entradas de índice con puntos guía.

Casi todos los umbrales heurísticos están en `Flow` y `find_regions`. Si un libro concreto se convierte mal, ajústalos ahí. `-v` muestra en el registro lo que se detectó.

### 3.2 `textfix.py`: limpieza de caracteres

- Expande ligaduras (`ﬁ → fi`).
- Elimina `(cid:NN)`, caracteres de uso privado y caracteres ilegales en XML o de ancho cero.
- Normaliza los espacios raros.
- Recompone los acentos sueltos de PDFs de LaTeX (`´a → á`).
- Normaliza a **NFC** (no NFKC, para conservar `ª º ²`).

### 3.3 `images.py`: imágenes

- **Figuras** (`render_clip`):
  - Se renderizan a **220 ppp** (hasta 300 si el original tiene más) con un lado máximo de 1800 px (`--max-image-px`).
  - Si la región es una única imagen incrustada, se usan sus píxeles originales.
  - Si no, se renderiza al doble de resolución y se reduce con Lanczos. Así se evita el escalado dentado de MuPDF.
- **Formato:**
  - **JPEG** para fotos (calidad mínima 90 en figuras).
  - **PNG** para dibujos con pocos colores (paleta de 256 si cabe).
  - Escala de grises automática cuando la imagen no tiene color.
- **Páginas como imagen** (`render_page`): 200 ppp. Las páginas sin fotos se guardan como PNG de **16 grises**, los que muestra un Kindle E-Ink: nítido y ligero.
- **Portada:** página 1, hasta 1600 px de alto, en JPEG.
- **Iconos al margen** (TIP, NOTE…): 400 ppp. En el EPUB flotan a la izquierda del párrafo.

### 3.4 `epub.py`: libro final

- **`finalize_blocks`**:
  - Asigna niveles de título (h1–h4) según el tamaño.
  - Asocia cada pie de figura o tabla ("Figura 3.2…") a su imagen. Si el pie va encima o debajo se decide por mayoría en el libro.
  - Quita la sangría del primer párrafo tras un título o una figura.
- **`detect_lang`**: cuenta palabras vacías (*stopwords*) en es, en, pt, fr, de e it. Se puede forzar con `--lang`.
- **`plan_book`**: decide capítulos e índice.
  1. Usa el **índice del PDF** (`doc.get_toc`), asociado a los bloques mediante `resolve_outline`.
  2. Si no lo hay, usa los títulos detectados.
  3. Parte los capítulos de más de unos 220 kB.
  4. Si no hay ninguna estructura, parte en grupos de unas 25 páginas ("Páginas 1–25").
- **`write_epub`**: escribe el zip EPUB 3 con `zipfile`:
  - `mimetype` va **primero y sin comprimir** (lo exige el estándar).
  - Después `META-INF/container.xml`, `OEBPS/content.opf`, `nav.xhtml` (EPUB 3), `toc.ncx` (compatibilidad con lectores antiguos), `styles.css`, `text/ch_NNN.xhtml` e `images/`.

**Restricción de diseño de la CSS:** `body` no define `font-family` ni `font-size`, para que el Kindle use la fuente y el tamaño del lector. La justificación y la separación silábica vienen de `text-align: justify`, `hyphens: auto` y el `lang` detectado, no de la maquetación original.

### 3.5 `model.py`: tipos compartidos

- **`Opts`**: opciones de conversión, una por cada opción de línea de comandos.
- **`Asset`**: imagen ya codificada (nombre, bytes, tipo MIME y tamaño).
- **`Block`**: unidad del libro. `kind` es uno de estos:
  - `p`: párrafo
  - `h`: título
  - `img`: figura
  - `table`: tabla
  - `pageimg`: página como imagen
  - `fn`: nota al pie

  Los bloques con imagen apuntan a `ctx.assets` mediante el índice `asset`.

---

## 4. Funcionalidades

### Problemas que resuelve

| Problema habitual de otros conversores | Qué hace EpubTailor |
|---|---|
| Texto sin justificar, saltos de línea en mitad de la frase | Reconstruye párrafos reales y quita los guiones de fin de línea. Respeta los guiones de palabras compuestas. |
| Caracteres raros (ligaduras, `(cid:NN)`, acentos sueltos) | Limpieza en `textfix`. Las páginas ilegibles pasan a imagen. |
| Cabeceras, pies y números de página en mitad del texto | Se detectan por repetición y se eliminan. |
| Dos columnas mezcladas | Detecta el canal y conserva el orden de lectura. |
| Notas al pie en medio de un párrafo | Se mueven al final del párrafo. |
| Gráficas vectoriales rotas o etiquetas sueltas | La gráfica completa se convierte en una imagen nítida, con sus etiquetas. |
| Imágenes borrosas o dentadas | Renderizado de 220 a 300 ppp con suavizado Lanczos. |
| Sin índice | Usa el índice del PDF o, si no lo hay, los títulos detectados. Cada capítulo va en un archivo. |
| Tablas descolocadas | Imagen nítida por defecto, o tabla HTML con `--tables html`. |
| PDF escaneado | OCR con Tesseract (`--ocr`) o página como imagen. |

### Modos y opciones (CLI y `Opts`)

| Opción | Valor por defecto | Efecto |
|---|---|---|
| `--mode reflow \| pages` | `reflow` | `reflow`: el texto se adapta a la pantalla. `pages`: cada página es una imagen (cómics, partituras, mucha matemática). |
| `--tables image \| html` | `image` | Tablas como imagen ampliable o como HTML |
| `--ocr` | desactivado | OCR en páginas escaneadas |
| `--ocr-lang` | `spa+eng` | Idiomas de Tesseract |
| `--no-fallback` | — | No convierte en imagen las páginas ilegibles |
| `--keep-headers` | — | Conserva cabeceras y pies |
| `--lang`, `--title`, `--author` | se detectan | Metadatos |
| `--jpeg-quality` | 85 | Calidad JPEG |
| `--max-image-px` | 1800 | Lado máximo de las imágenes |
| `-o` | junto al PDF | Archivo o carpeta de salida (admite una carpeta de PDFs) |
| `-v` | — | Registra lo detectado: cuerpo de texto, páginas escaneadas, guiones… |

```bash
python -m pdf2epub libro.pdf -v                 # crea libro.epub junto al PDF
python -m pdf2epub carpeta/ -o epubs/           # conversión por lotes
python -m pdf2epub escaneado.pdf --ocr --ocr-lang spa
```

---

## 5. OCR

| Aspecto | Detalle |
|---|---|
| Motor | **Tesseract OCR**, motor OCR de código abierto |
| Integración | PyMuPDF, `page.get_textpage_ocr(language=opts.ocr_lang, dpi=300, full=True)`: rasteriza la página entera a **300 ppp**, se la pasa a Tesseract y recibe una capa de texto con posiciones, que se procesa igual que el texto nativo del PDF |
| Idiomas | `spa+eng` por defecto (`--ocr-lang`, con la sintaxis de Tesseract: `spa`, `eng`, `por`, `fra`…). Cada idioma necesita su paquete `tesseract-ocr-<idioma>`. |
| Cuándo se aplica | Hace falta **activarlo** (viene desactivado): `--ocr` en la línea de comandos, o la casilla «Es un escaneo» en la web cuando el servicio tiene el OCR activado (ahora no lo tiene; ver la fila «En la web»). Aun así, solo actúa en las páginas clasificadas como **escaneadas**: menos de 25 caracteres de texto fuera de cabecera y pie, y una imagen que cubre al menos el 80 % de la página. Las páginas con texto nativo nunca pasan por OCR. |
| Si falla | Por ejemplo, porque Tesseract no está instalado: se registra un aviso y la página se incluye **como imagen**, nunca como texto basura. |
| Diferencias en páginas con OCR | La imagen de fondo es el propio escaneo, así que no se recortan figuras de ella. Solo se excluyen las tablas detectadas. |
| Instalación local | `sudo apt install tesseract-ocr tesseract-ocr-spa` |
| En Docker | La imagen instala `tesseract-ocr`, `tesseract-ocr-spa` y `tesseract-ocr-eng` |
| En la web | **Desactivado por ahora** (decisión del 13/10/2026: cuesta unos 4 s por página y los escaneos se esperan poco frecuentes). Se activa con la variable `OCR=1`; además, `tesseract` tiene que estar en el `PATH`. Sin las dos cosas, `/api/config` devuelve `ocr: false`, la página oculta la casilla y los textos sobre el OCR, y la API rechaza las peticiones con OCR. Los escaneos se convierten igual, como imágenes de página. |
| Limitación | La calidad depende del escaneo y de la versión de Tesseract instalada |

### ¿Qué es un PDF escaneado?

Un PDF en el que cada página es una foto del papel. Para el conversor hay tres casos distintos:

| Tipo de PDF | Qué contiene | Qué hace el conversor |
|---|---|---|
| Escaneado (solo imágenes) | Una imagen por página, sin texto digital | Con OCR, saca el texto de la imagen; sin OCR, mete la página como imagen |
| Escaneado «con búsqueda» | La imagen más una capa de texto invisible que añadió el escáner o un programa como Adobe | Usa esa capa de texto directamente; el OCR no actúa |
| Digital con fotos | Texto digital normal y algunas imágenes dentro de la página | Convierte el texto y saca las fotos como figuras; no es un escaneo |

Para saberlo, abre el PDF e intenta seleccionar una palabra o buscarla con Ctrl+F. Si no puedes, es un
escaneo de solo imágenes y el OCR sirve; si puedes, ya tiene texto y el OCR no hace nada.

| Caso | ¿Usa OCR? |
|---|---|
| Libro digital | Nunca, aunque se active: sus páginas tienen texto |
| Escaneo con el OCR activado | Sí, en cada página escaneada |
| Escaneo sin activarlo | No: cada página va como imagen y el registro sugiere usar `--ocr` |
| PDF mixto (texto y algunas páginas escaneadas) con el OCR activado | Solo en las páginas escaneadas |
| Página con texto dañado (más del 8 % de caracteres basura) | No: va como imagen. El OCR no se usa para rescatar texto dañado |

El OCR cuesta unos 4 s de CPU por página (unas 30 veces más que un libro digital) y reconoce el 90–94 % de las palabras en un escaneo limpio; con el timeout actual de 600 s, un escaneo de más de ~140 páginas no termina (ver [RENDIMIENTO.md](RENDIMIENTO.md), §5).

### ¿Y si el PDF tiene imágenes? ¿Se activa el OCR?

No. Una imagen dentro de una página con texto **nunca activa el OCR**. El OCR solo actúa si el usuario lo
activa y, además, la página es prácticamente una sola imagen sin texto (ver la tabla anterior). El resto
de imágenes se tratan así (`find_regions` en `analyze.py`, ver [§3.1](#31-analyzepy-de-pdf-a-bloques)):

| Qué hay en la página | Qué sale en el EPUB |
|---|---|
| Foto, ilustración o captura de pantalla junto al texto | Una figura, recortada a 220–300 ppp, con su pie («Figura 3.2…») si lo tiene |
| Gráfica o diagrama vectorial (dibujado con líneas, no una foto) | Una figura con sus etiquetas incluidas; esas etiquetas se quitan del texto para que no se cuelen en los párrafos |
| Texto dentro de una imagen (una captura, un esquema escaneado) | Se queda dentro de la imagen: se ve, pero no se puede buscar ni cambia de tamaño con la fuente del Kindle |
| Iconos pequeños al margen (TIP, NOTE…) | Un icono pequeño a la izquierda del párrafo |
| Decoración: fondos lisos, degradados, sombras, imágenes de menos de 20 pt, logotipos pequeños repetidos en muchas páginas | Se descarta |
| Imagen de fondo que ocupa casi toda la página, con texto encima (p. ej., la portadilla de un capítulo) | Se convierte el texto y el fondo se descarta |
| Imagen a página completa casi sin texto (una lámina, un mapa, un escaneo) | Se clasifica como **escaneada**: sin OCR, la página entera va como imagen; con OCR, se reconoce su texto |

**Láminas sin texto con el OCR activado.** Una ilustración a página completa también se clasifica como
escaneada, así que con el OCR activado pasa por Tesseract, que solo saca restos sueltos («a 1 p E :»). Si
en el resultado no hay palabras de verdad (menos de 10 letras en palabras de 3 o más letras, o menos de la
mitad del texto), la página va **como imagen**, igual que sin OCR. Lo cubre la prueba
`test_ocr_keeps_full_page_plate_as_image`.

En una página escaneada que sí tiene texto, el OCR conserva solo el texto: una foto dentro de esa misma
página no se recorta como figura.

---

## 6. Servicio web

### API (`web/app.py`)

| Método y ruta | Descripción |
|---|---|
| `GET /` | Sirve `static/index.html` |
| `GET /api/config` | `{"max_mb": 50, "max_pages": 800, "ocr": true}`: límites y si hay OCR |
| `POST /api/convert` | `multipart/form-data` que devuelve el EPUB (`application/epub+zip`, como adjunto). Se envía por partes (`Transfer-Encoding: chunked`), sin cargarlo entero en memoria; así Cloud Run no le aplica su límite de 32 MiB por respuesta |

Campos de `POST /api/convert`:

| Campo | Valores |
|---|---|
| `pdf` | El archivo (obligatorio) |
| `mode` | `reflow` o `pages` |
| `tables` | `image` o `html` |
| `ocr` | `"1"` para activarlo |
| `keep_headers` | `"1"` para activarlo |
| `title`, `author` | Texto, máximo 200 caracteres |

Errores: devuelven JSON `{"error": "..."}` con estos códigos.

| Código | Cuándo |
|---|---|
| `400` | Falta el archivo, opciones no válidas, no es un PDF, PDF con contraseña, demasiadas páginas u OCR no disponible |
| `413` | El archivo supera `MAX_MB` |
| `422` | El conversor no pudo extraer contenido |
| `500` | Error interno (se registra con traza) |

**Privacidad y seguridad:**

- Cada conversión se hace en un directorio temporal que **se borra siempre**: al terminar de enviar el EPUB (`call_on_close`) o en cuanto hay un error. No se guarda nada.
- El nombre del archivo se sanea (ASCII, máximo 80 caracteres).
- El contenedor se ejecuta con un usuario sin privilegios (`app`).
- CORS: solo los orígenes de `ALLOWED_ORIGINS` pueden llamar a `/api/*` desde otro dominio (la página publicada en Cloudflare Pages). La respuesta expone `Content-Disposition` para que la página lea el nombre del EPUB.

Variables de entorno:

| Variable | Valor por defecto | Uso |
|---|---|---|
| `PORT` | `8000` | Puerto de escucha |
| `MAX_MB` | `50` | Tamaño máximo del PDF (en Cloud Run, `30`: no admite peticiones de más de 32 MiB) |
| `MAX_PAGES` | `800` | Páginas máximas |
| `WORKERS` | `2` | Procesos de Gunicorn |
| `OCR` | `0` | `1` activa el OCR en la web (desactivado por ahora) |
| `ALLOWED_ORIGINS` | vacío | Orígenes con permiso CORS, separados por comas (p. ej. `https://epubtailor.pages.dev`). Vacío: solo el mismo origen |

### Página de inicio (`web/static/index.html`)

Es un único archivo estático, sin compilación ni frameworks.

- **Marca:** EpubTailor, con logo SVG vectorizado (`img/epubtailor-logo.svg`, y la versión con fondo `epubtailor-logo-fondo.svg`). El rojo de "Epub" es el rojo de Adobe (`#FA0F00`).
- **Diseño:** paleta verde EPUB y melocotón PDF con tokens `oklch` en `:root`. Tipografías Newsreader (serif) y Figtree (sans).
- **Formulario:**
  - Arrastrar y soltar o elegir un archivo.
  - Opciones plegables: modo, tablas, cabeceras, título y autor (y OCR, solo si el servicio lo tiene activado).
  - Subida por `XMLHttpRequest` con barra de progreso.
  - Descarga del resultado y su tamaño (en KB por debajo de 1 MB; en MB a partir de ahí).
  - Consejo sobre la vía de envío al Kindle según el tamaño.
- **Secciones:**
  - Cómo funciona: es un servicio en línea y no hay que instalar nada.
  - Carrusel de ejemplos de antes y después, con SVG en línea y `inert` en las diapositivas ocultas.
  - Lista de problemas que resuelve.
  - Límites y vías de Amazon:

    | Vía | Límite |
    |---|---|
    | Web Enviar a Kindle | 200 MB |
    | App y correo | 50 MB |
    | Gmail | 25 MB |
    | Outlook | 20 MB |

  - Privacidad.
  - Preguntas frecuentes (acordeón con un solo elemento abierto).
  - Pie.
- Se adapta a móvil.

---

## 7. Despliegue

```bash
# Local (motor)
python3 -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt

# Local (web, modo desarrollo)
pip install -r requirements-web.txt
python -m web.app                          # http://localhost:8000

# Docker
docker build -t pdf2epub-web:latest .
docker rm -f pdf2epub                      # si ya existía
docker run -d --name pdf2epub --restart unless-stopped -p 8000:8000 pdf2epub-web:latest
```

En producción, el contenedor ejecuta `exec gunicorn -w ${WORKERS:-2} -t 600 --max-requests 20 --max-requests-jitter 5 -b 0.0.0.0:${PORT} web.app:app`. `exec` hace que Gunicorn reciba las señales de parada; `--max-requests` recicla cada worker tras unas 20 conversiones para que devuelva la memoria (RENDIMIENTO.md §4). `.dockerignore` deja fuera `tests/`, `ejemplo/`, `deploy/`, `.git` y `.venv`.

**Producción: API en Google Cloud Run y página en Cloudflare Pages.** Pasos, configuración y costes en [DESPLIEGUE.md](DESPLIEGUE.md).

La página lee `static/config.js`. Vacío (`window.EPUBTAILOR = {}`), llama a la API en su mismo servidor, como en local o en un VPS. `deploy/cloudflare-pages.sh` genera otro con la URL de Cloud Run y los límites (`api`, `limits`), así que la página no necesita llamar a `/api/config`.

---

## 8. Pruebas

```bash
pip install pytest epubcheck
pytest -q tests
pytest -q tests/test_convert.py::test_toc_has_three_chapters   # una sola prueba
```

`tests/make_sample_pdf.py` genera durante la prueba un PDF deliberadamente difícil, con estos elementos:

- guiones de fin de línea,
- cabeceras y números de página repetidos,
- una foto, una gráfica vectorial y una tabla,
- dos columnas,
- tres capítulos.

Un *fixture* de ámbito de módulo lo convierte una sola vez. Cada prueba inspecciona el zip resultante.

| Prueba | Qué comprueba |
|---|---|
| `test_mimetype_first_and_stored` | `mimetype` es la primera entrada y va sin comprimir |
| `test_no_soft_hyphens_or_broken_words` | No quedan guiones suaves ni palabras partidas |
| `test_headers_and_page_numbers_removed` | Se eliminan las cabeceras y los números de página |
| `test_figures_have_captions_and_images` | Las figuras tienen imagen y pie |
| `test_chart_labels_not_leaked_as_text` | Las etiquetas de la gráfica no aparecen como texto |
| `test_two_columns_read_in_order` | El orden de lectura en dos columnas es correcto |
| `test_toc_has_three_chapters` | El índice tiene tres capítulos |
| `test_epubcheck` | El EPUB es válido según EPUBCheck (se omite si no está instalado) |
| `test_compound_hyphen_kept_at_line_end` | Se conserva el guion de las palabras compuestas al final de línea |
| `test_bullet_glyph_duplicates_and_loose_markers` | Viñetas duplicadas y marcadores de lista sueltos |
| `test_margin_icon_kept` | Se conservan los iconos al margen |
| `test_low_res_figure_is_smoothed_not_blocky` | Las figuras de baja resolución salen suavizadas, no dentadas |
| `test_stacked_figures_keep_their_captions_and_header_dropped` | Las figuras apiladas conservan su pie |
| `test_booktabs_table_kept_as_table` | Las tablas *booktabs* se detectan como tabla |
| `test_web.py` (6 pruebas) | El EPUB se envía por partes y sin `Content-Length`; el temporal se borra al terminar y tras un error; CORS para orígenes permitidos, *preflight* y no permitidos; 413 legible desde otro origen. Se omiten si Flask no está instalado |
| `test_ocr_keeps_full_page_plate_as_image` | Con OCR, una página escaneada de texto se reconoce y una lámina sin texto se conserva como imagen (se omite si no hay Tesseract) |

---

## 9. Limitaciones conocidas

- Matemáticas complejas, partituras o maquetación muy artística: usa `--mode pages`.
- Las heurísticas de párrafos y títulos pueden fallar en libros atípicos. Revisa con `-v` y ajusta los umbrales en `analyze.py`.
- La calidad del OCR depende de Tesseract y del escaneo.
- En las páginas escaneadas que pasan por el OCR solo se conserva el texto: las fotos o figuras que haya en esa misma página se pierden (ver [§5](#y-si-el-pdf-tiene-imágenes-se-activa-el-ocr)).
- Los PDF con contraseña no se admiten.
- Convenciones del proyecto: el código, los comentarios, los mensajes y los textos para el usuario están en español.
