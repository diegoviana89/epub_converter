// Configuración de la página.
// Vacía: la API está en el mismo servidor que la página (python -m web.app, Docker o un VPS).
// deploy/cloudflare-pages.sh genera otra versión con la URL de Cloud Run y los límites del servicio:
//   window.EPUBTAILOR = { api: "https://…run.app", limits: { max_mb: 30, max_pages: 800, ocr: false } };
window.EPUBTAILOR = {};
