# Rendimiento del servicio: memoria, CPU y tiempo de conversión

Prueba del 13/10/2026 con tres libros reales, usando la imagen Docker del servicio (`pdf2epub-web:latest`,
la misma que está en producción en el puerto 8000).

## Resumen

| Libro | PDF | Páginas | Tiempo | CPU | Memoria pico | EPUB |
|---|---:|---:|---:|---:|---:|---:|
| Generative AI and LLMs for Dummies | 2,0 MB | 52 | **6,4 s** | 1 núcleo al 100 % | **128 MiB** | 1,5 MB |
| Robotics (Springer, 2009) | 9,1 MB | 644 | **86,8 s** | 1 núcleo al 100 % | **227 MiB** | 10,1 MB |
| JavaScript on Things | 37,9 MB | 628 | **82,0 s** | 1 núcleo al 100 % | **449 MiB** | 37,0 MB |

- **El tiempo depende de las páginas, no del peso del PDF**: unos **125–135 ms por página** en esta máquina.
  Robotics pesa la cuarta parte que JavaScript on Things y tarda lo mismo.
- **La conversión usa un solo núcleo**. Más núcleos no la aceleran; solo permiten atender más
  conversiones a la vez. Lo que acorta el tiempo es la velocidad de cada núcleo.
- **La memoria depende sobre todo de las imágenes**: JavaScript on Things (muchas fotos) llega a 449 MiB;
  Robotics, con más páginas pero imágenes ligeras, a 227 MiB.
- **Los workers de Gunicorn no devuelven la memoria al terminar** (ver §4).

## 1. Entorno de la prueba

| | |
|---|---|
| Máquina | Intel Core i5-12500H (12.ª gen., 16 hilos), 22 GiB de RAM, Linux 7.0 |
| Docker | 29.9.0, motor del sistema (contexto `default`) |
| Imagen | `pdf2epub-web:latest` (Python 3.12.15, PyMuPDF 1.28.2, Pillow 12.3.0, Tesseract 5.5.0) |
| Opciones | Las de por defecto: `reflow`, tablas como imagen, sin OCR |
| Servicio | Gunicorn con 2 workers, timeout de 600 s, `MAX_MB=50`, `MAX_PAGES=800` |

Ninguno de los tres PDF es escaneado, así que **no se midió el OCR**.

## 2. Conversión aislada (3 repeticiones por libro)

Cada conversión se ejecutó con `python -m pdf2epub` en un proceso aparte, dentro de un contenedor
nuevo de la misma imagen. La CPU y la memoria pico salen de `getrusage` del proceso; la memoria media,
de muestrear `VmRSS` cada 50 ms. Valores: mediana de 3 repeticiones.

| Libro | Tiempo (3 rep.) | CPU usuario | CPU sistema | Uso de CPU | RSS pico | RSS medio | ms/página |
|---|---|---:|---:|---:|---:|---:|---:|
| Generative AI for Dummies | 7,1 · 6,4 · 6,3 s | 6,2 s | 0,11 s | 100 % | 128 MiB | 102 MiB | 123 |
| Robotics | 86,5 · 86,8 · 87,9 s | 86,3 s | 0,42 s | 100 % | 227 MiB | 187 MiB | 135 |
| JavaScript on Things | 82,0 · 81,6 · 82,2 s | 81,3 s | 0,62 s | 100 % | 449 MiB | 344 MiB | 131 |

Las repeticiones varían menos de un 2 %, salvo la primera de Dummies (arranque en frío de la imagen).
"100 %" equivale a un núcleo entero ocupado durante toda la conversión.

Resultado de cada conversión:

| Libro | Capítulos | Imágenes | EPUB |
|---|---:|---:|---:|
| Generative AI for Dummies | 12 | 40 | 1,5 MB |
| Robotics | 22 | 456 | 10,1 MB |
| JavaScript on Things | 26 | 392 | 37,0 MB |

## 3. De punta a punta, contra el servicio (`POST /api/convert`)

Cada PDF se subió con `curl` al servicio en `localhost:8000`, como lo haría la página web. Mientras
tanto se leyó el cgroup del contenedor cada 0,25 s: memoria anónima de todos sus procesos (`memory.stat`)
y CPU acumulada (`cpu.stat`).

| Prueba | Respuesta | Tiempo total | Memoria del contenedor antes → pico | CPU media |
|---|---|---:|---:|---:|
| Generative AI for Dummies | 200 | 6,1 s | 157 → 208 MiB | 98 % |
| Robotics | 200 | 86,1 s | 195 → 346 MiB | 100 % |
| JavaScript on Things | 200 | 82,3 s | 318 → 569 MiB | 100 % |
| **Robotics + JavaScript a la vez** | 200 · 200 | 87,7 s (las dos) | 515 → 673 MiB | **193 %** (2 núcleos) |

- Subir y descargar en local añade menos de medio segundo; casi todo el tiempo es conversión. En un
  servidor real hay que sumar la subida del usuario (38 MB con 10 Mbit/s de subida son unos 30 s más).
- Dos conversiones a la vez tardan lo mismo que una sola, porque cada una usa su propio núcleo.
  Con 2 workers, una tercera petición espera a que termine una de las dos.

## 4. La memoria en reposo crece y no baja

Antes de cada prueba la memoria del contenedor era mayor que en la anterior (157 → 195 → 318 → 515 MiB).
Al terminar todas las pruebas, cada worker conservaba:

| Proceso | RSS |
|---|---:|
| Gunicorn (maestro) | 30 MiB |
| Worker 1 | 409 MiB |
| Worker 2 | 223 MiB |

Python y MuPDF guardan la memoria ya usada para reutilizarla en vez de devolverla al sistema, así que
**cada worker se queda con el pico del libro más pesado que haya convertido**. No es una fuga que crezca
sin fin, pero en un servidor pequeño cuenta como memoria ocupada de forma permanente.

Arreglo sencillo: reciclar los workers con `--max-requests 20 --max-requests-jitter 5` en el `CMD` del
`Dockerfile`; Gunicorn los reinicia cada ~20 conversiones y la memoria vuelve a la de un worker recién arrancado.
(No se ha aplicado ni medido todavía.)

## 5. Qué implica para elegir servidor

| Recurso | Necesidad medida | Recomendación |
|---|---|---|
| CPU | 1 núcleo por conversión en curso; ~130 ms/página en un i5-12500H | 2 vCPU para los 2 workers. Un vCPU de VPS suele ser más lento que este portátil; como estimación (no medida), **1,5–2× más tiempo** (unos 2–3 min para un libro de 600 páginas). |
| Memoria | Hasta ~450 MiB por conversión con libros llenos de fotos; ~700 MiB con 2 a la vez | **2 GB bastan**; 4 GB dan margen para OCR, libros más grandes o un tercer worker. |
| Tiempo por petición | Hasta ~90 s aquí, 2–3 min en un VPS | Descarta proxies con corte a 100 s (Cloudflare con proxy activo) o 60 s (Firebase Hosting → Cloud Run). |
| Tamaño de petición y respuesta | PDF de 38 MB y EPUB de 37 MB | Supera el límite de 32 MiB de Cloud Run en la subida **y** en la descarga. |

Con estos datos, el Hetzner CAX11 (2 vCPU, 4 GB) que se propuso cubre el uso previsto con margen de memoria;
la CPU es lo que marcará el tiempo de espera de los usuarios.

## Cómo repetir la prueba

Los scripts están en el scratchpad de la sesión (no en el repositorio):

- `mide.py`: conversión aislada. Se ejecuta dentro de un contenedor de la imagen montando los PDF:
  `docker run --rm -v <bench>:/bench -v <pdf>:/pdfs/<pdf>:ro pdf2epub-web:latest python /bench/mide.py /pdfs/*.pdf`
- `api.py`: prueba de punta a punta contra el contenedor `pdf2epub` en el puerto 8000.
