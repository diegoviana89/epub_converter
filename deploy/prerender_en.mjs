// Genera la versión en inglés como HTML estático (dist/pages/en/index.html) a partir de index.html
// y de EN en i18n.js, aplicando lo mismo que hace setLang() en el navegador. Así Google ve el inglés
// sin ejecutar JavaScript. Uso: node deploy/prerender_en.mjs <index.html de entrada> <salida>
import { readFileSync, writeFileSync, mkdirSync } from "node:fs";
import { dirname } from "node:path";
import vm from "node:vm";

const [src, dst] = process.argv.slice(2);
const win = {};
vm.runInNewContext(readFileSync(new URL("../web/static/i18n.js", import.meta.url), "utf8"), { window: win });
const EN = win.I18N.EN;
let html = readFileSync(src, "utf8");

const esc = s => s.replace(/&/g, "&amp;").replace(/"/g, "&quot;");
const need = k => { if (!(k in EN)) throw new Error(`Falta la clave EN.${k}`); return EN[k]; };

// Sustituye el contenido de cada elemento con data-i18n="clave" (se busca su cierre contando anidados).
function replaceContent(h) {
  const open = /<([a-z0-9]+)\b[^>]*?\sdata-i18n="([^"]+)"[^>]*>/g;
  let out = "", last = 0, m;
  while ((m = open.exec(h))) {
    const [tag, name, key] = m;
    const start = m.index + tag.length;
    const re = new RegExp(`<(/?)${name}\\b[^>]*>`, "g");
    re.lastIndex = start;
    let depth = 1, c;
    while ((c = re.exec(h))) {
      depth += c[1] ? -1 : 1;
      if (depth === 0) break;
    }
    if (!c) throw new Error(`Sin cierre para <${name} data-i18n="${key}">`);
    out += h.slice(last, start) + need(key);
    last = c.index;
    open.lastIndex = c.index;
  }
  return out + h.slice(last);
}
html = replaceContent(html);

// data-i18n-attr="atributo:clave,…": cambia (o añade) esos atributos en la etiqueta.
html = html.replace(/<[a-z0-9]+\b[^>]*?\sdata-i18n-attr="([^"]+)"[^>]*>/g, (tag, spec) => {
  for (const pair of spec.split(",")) {
    const [a, k] = pair.split(":");
    const val = esc(need(k));
    const re = new RegExp(`(\\s${a}=)"[^"]*"`);
    tag = re.test(tag) ? tag.replace(re, `$1"${val}"`) : tag.replace(/\s*\/?>$/, m => ` ${a}="${val}"${m}`);
  }
  return tag;
});

html = html.replace(/(<em class="fluyen" id="fluyen">)[^<]*/, `$1${need("h1Em")}`);

// Cabecera: idioma, título, descripción y etiquetas sociales.
html = html.replace('<html lang="es">', '<html lang="en" data-page-lang="en">');
html = html.replace(/<title>[^<]*<\/title>/, `<title>${need("pageTitle")}</title>`);
html = html.replace(/(<meta name="description" content=)"[^"]*"/, `$1"${esc(need("pageDesc"))}"`);
html = html.replace(/(<meta property="og:title" content=)"[^"]*"/, `$1"${esc(need("pageTitle"))}"`);
html = html.replace(/(<meta property="og:description" content=)"[^"]*"/, `$1"${esc(need("pageDesc"))}"`);
html = html.replace('content="es_ES"', 'content="en_US"').replace('og:locale:alternate" content="en_US"', 'og:locale:alternate" content="es_ES"');
html = html.replace(/(<meta property="og:url" content="[^"]*?)\/">/, '$1/en/">');
html = html.replace(/(<link rel="canonical" href="[^"]*?)\/">/, '$1/en/">');
html = html.replace(/("url":"[^"]*?)\/"/, '$1/en/"').replace(/"description":"[^"]*"/, `"description":${JSON.stringify(need("pageDesc"))}`);

// Rutas relativas -> absolutas, porque ahora la página está en /en/.
html = html.replace(/(src=")(config\.js|i18n\.js|img\/)/g, "$1/$2");

writeFileSync(dst, html);
