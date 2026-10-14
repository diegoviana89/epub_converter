// Textos de la página en inglés. El español está en index.html: los elementos con data-i18n="clave"
// cambian su contenido por EN[clave] y data-i18n-attr="atributo:clave,…" cambia esos atributos.
// MSG tiene los mensajes que escribe el script (estado, avisos, límites) en los dos idiomas.
window.I18N = {
  EN: {
    pageTitle: "EpubTailor · PDF to EPUB for Kindle",
    pageDesc: "Turn your PDFs into EPUBs that read well on Kindle: justified text, no headers or page numbers, with a table of contents and sharp images.",
    langGroup: "Language",

    navComo: "How it works",
    navEj: "Examples",
    navKindle: "Send to Kindle",
    navFaq: "FAQ",

    h1: "Turn your PDFs into books",
    h1Em: "that flow",
    lead: "Upload a PDF and download an EPUB that reads well on Kindle: real paragraphs, no running headers or page numbers, with a table of contents, sharp images and tables.",
    badgesAria: "Highlights",
    badges: "<li>Free</li><li>No sign-up</li><li>No watermarks</li><li>Deleted when done</li>",
    opts: "Options",
    mode: "Document type",
    modeReflow: "Book with text (recommended)",
    modePages: "Comic, sheet music or formulas (pages as images)",
    tables: "Tables",
    tablesImage: "As a sharp image",
    tablesHtml: "As text",
    title: "Title (optional)",
    author: "Author (optional)",
    ocr: "It’s a scan<small>Recognize the text with OCR (slower)</small>",
    keep: "Keep headers and footers<small>They are removed by default</small>",
    go: "Convert to EPUB",

    intro: "Nothing to install: the conversion runs on our server, not on your device. It works from the browser on your computer, tablet or phone, whenever and wherever you need it.",
    step1: "Upload your PDF",
    step1d: "Drag it in or pick it from your device.",
    step2: "Convert it",
    step2d: "It takes from a few seconds to a couple of minutes.",
    step3: "Download the EPUB",
    step3d: "It downloads automatically when it’s done.",
    step4: "Send it to your Kindle",
    step4d: "With the <em>Send to Kindle</em> website or by email.",

    carousel: "carousel",
    example: "example",
    ejTitle: "What other converters break",
    ejIntro: "A PDF describes where each letter goes on a fixed-size page, not what a paragraph, a header or a figure caption is. Many converters copy the text as is, and the book fills up with page numbers, broken words and stray images. This one rebuilds the book.",
    prev: "Previous",
    next: "Next",
    ex1: "Example 1 of 3",
    ex2: "Example 2 of 3",
    ex3: "Example 3 of 3",
    dot1: "Go to example 1",
    dot2: "Go to example 2",
    dot3: "Go to example 3",
    ex1Title: "Book with figures and footnotes",
    ex2Title: "Two-column article",
    ex3Title: "Manual with tables and charts",
    capPdf: "A page from the original",
    capEpub: "The same page on Kindle",
    capEpub2: "The same article on Kindle",
    svg1: "Original PDF page with a running header, page number, hyphenated words and a footnote",
    svg2: "The same content on Kindle: continuous text, figures with their captions and no headers",
    svg3: "Two-column article in the PDF: the reading order gets mixed up and every line ends in a line break",
    svg4: "The same article on Kindle: a single column in order and continuous paragraphs",
    svg5: "A manual page in the PDF with a table and a bar chart",
    svg6: "The same page on Kindle: the table and the chart as sharp images with their captions",
    legend1: "<li>Header and page number</li><li>Figures and captions stacked</li><li>Words split with a hyphen</li><li>Footnote in the middle</li>",
    legend2: "<li>No headers or page numbers</li><li>Continuous, justified text</li><li>Every figure with its caption</li>",
    legend3: "<li>Columns read out of order</li><li>A line break at the end of every line</li>",
    legend4: "<li>Correct reading order</li><li>Real paragraphs</li>",
    legend5: "<li>Tables turned into jumbled text</li><li>Charts pixelated or lost</li>",
    legend6: "<li>Tables as a sharp image or as text</li><li>Images at a good resolution</li>",
    fixes: `
    <li><s>Headers and page numbers in the middle of the text</s><b>Removed</b></li>
    <li><s>Words split with a hyphen: “auto- matic”</s><b>Joined back together</b></li>
    <li><s>Figure captions separated from their image</s><b>Every figure with its caption</b></li>
    <li><s>Footnotes in the middle of a paragraph</s><b>Placed after their paragraph</b></li>
    <li><s>Two columns read out of order</s><b>Correct reading order</b></li>
    <li><s>Tables and charts turned into jumbled text</s><b>Sharp tables and images</b></li>
  `,

    send: `
      <li><span>Download the <b>.epub</b> file from this page.</span></li>
      <li><span>Upload it at <a href="https://www.amazon.com/sendtokindle" rel="noopener">Send to Kindle</a> (Amazon’s website). It’s the most reliable option and takes the largest files.</span></li>
      <li><span>Small files can also be emailed to your <b>@kindle.com</b> address.</span></li>
    `,
    note: "If it’s your first time sending by email, add your sender address to the approved email list in your Amazon account settings.",
    limTitle: "Limits of this service",
    limMBdd: "Maximum PDF size.",
    limPagesdd: "Maximum number of pages.",
    limTime: "How long a 600-page book takes.<span class=\"con-ocr\" hidden> With OCR it can take much longer.</span>",
    limPass: "No passwords",
    limPassdd: "Password-protected PDFs can’t be converted.",
    amzTitle: "Amazon’s limits for sending the EPUB",
    amz: `
        <div><dt><em>Send to Kindle</em> website</dt><dd class="ok">200 MB per file</dd></div>
        <div><dt><em>Send to Kindle</em> app (PC or phone)</dt><dd>50 MB</dd></div>
        <div><dt>Email to @kindle.com</dt><dd>50 MB per email</dd></div>
        <div><dt>Email from Gmail or Outlook</dt><dd class="warn">25 MB / 20 MB per attachment</dd></div>
      `,
    amzNote: "Above 25 MB, Gmail doesn’t attach the file: it replaces it with a Google Drive link, which Amazon doesn’t accept. For those books, use the <em>Send to Kindle</em> website. The EPUB can be as large as the PDF, or larger if it has many images. Amazon may change these limits.",

    privTitle: "Your files are yours",
    feats: `
      <div><h3>Deleted when done</h3><p>The PDF and the EPUB only exist while the conversion runs. No copy is kept.</p></div>
      <div><h3>No sign-up</h3><p>We don’t ask for an account, an email address or any personal data.</p></div>
      <div><h3>No watermarks</h3><p>The EPUB is yours, complete and with nothing added.</p></div>
      <div><h3>Free</h3><p>No paid version and no hidden limits: the limits are the ones above.</p></div>
    `,

    faqTitle: "Frequently asked questions",
    q1: "Does it work with my Kindle?",
    a1: "Yes. Since 2022 Amazon accepts EPUB through <em>Send to Kindle</em> (website, app or email) and converts it to its own format when it arrives. Note: an EPUB copied over a USB cable won’t open on the Kindle; to use the cable, convert it to AZW3 with Calibre first.",
    q2: "Does it work for Kobo, Apple Books or Google Play Books?",
    a2: "Yes. EPUB is the standard e-book format and they all open it.",
    q3: "Which PDFs give the best results?",
    a3: "Those with digital text, that is, where you can select the text: books, manuals, articles. <span class=\"con-ocr\" hidden>If it’s a scan, turn on OCR in the options.</span><span class=\"sin-ocr\">Scans (pages that are just a photo) come out as page images, with no recognized text.</span> For comics, sheet music or lots of math, choose “pages as images”.",
    q4: "Why is the EPUB so large?",
    a4: "Because of the images: they’re kept at a resolution high enough to zoom in on the Kindle. A book with many figures can be as large as the PDF or larger. If it’s over 25 MB, send it with the <em>Send to Kindle</em> website.",
    q5: "Is the PDF’s typography kept?",
    a5: "No, on purpose. The EPUB doesn’t set a font or a size, so the Kindle uses the ones you choose. Headings, bold, italics, lists, images and tables are kept.",
    q6: "Some pages of a text book come out as images",
    a6: "Those pages had no readable text in the PDF (they were scanned or the text was damaged), so they’re included as images rather than showing wrong text.<span class=\"con-ocr\" hidden> If it’s a scan, convert it again with OCR turned on.</span>",
    q7: "The layout comes out jumbled",
    a7: "It happens with very artistic designs, magazines or pages full of formulas. Convert it again with the “pages as images” document type.",
    q8: "What if my PDF has a password?",
    a8: "It can’t be converted. Remove the password first, if you have the right to do so.",

    foot1: "EpubTailor · PDF to EPUB for Kindle",
    foot2: "Your files are deleted from the server as soon as the conversion finishes.",
  },

  MSG: {
    es: {
      dropTitle: "Elige un PDF o arrástralo aquí",
      dropHint: (mb, pages) => `Hasta ${mb} MB y ${pages} páginas`,
      picked: size => `${size} · pulsa para cambiarlo`,
      pages: n => `${n} páginas`,
      notPdf: "Ese archivo no es un PDF.",
      tooBig: mb => `El archivo supera el máximo de ${mb} MB.`,
      uploading: "Subiendo…",
      converting: "Convirtiendo… puede tardar un par de minutos en libros largos.",
      download: name => `Descargar ${name}`,
      defaultName: "libro.epub",
      failed: "No se pudo convertir el PDF.",
      lost: "Se perdió la conexión con el servidor. Inténtalo de nuevo.",
      send200: "Pesa más de 200 MB: supera incluso el límite de la web Enviar a Kindle. Prueba a convertirlo con menos imágenes o cópialo al Kindle por USB.",
      send50: "Pesa más de 50 MB: envíalo con la web Enviar a Kindle (hasta 200 MB). No llegará por correo ni con la app.",
      send25: "Pesa más de 25 MB: Gmail no lo adjuntará. Usa la web Enviar a Kindle.",
      send: "Puedes enviarlo con la web Enviar a Kindle o por correo a tu dirección @kindle.com.",
    },
    en: {
      dropTitle: "Choose a PDF or drag it here",
      dropHint: (mb, pages) => `Up to ${mb} MB and ${pages} pages`,
      picked: size => `${size} · click to change it`,
      pages: n => `${n} pages`,
      notPdf: "That file isn’t a PDF.",
      tooBig: mb => `The file is over the ${mb} MB limit.`,
      uploading: "Uploading…",
      converting: "Converting… long books can take a couple of minutes.",
      download: name => `Download ${name}`,
      defaultName: "book.epub",
      failed: "The PDF couldn’t be converted.",
      lost: "The connection to the server was lost. Please try again.",
      send200: "It’s over 200 MB: that’s more than even the Send to Kindle website accepts. Try converting it with fewer images or copy it to the Kindle over USB.",
      send50: "It’s over 50 MB: send it with the Send to Kindle website (up to 200 MB). It won’t get through by email or with the app.",
      send25: "It’s over 25 MB: Gmail won’t attach it. Use the Send to Kindle website.",
      send: "You can send it with the Send to Kindle website or by email to your @kindle.com address.",
    },
  },
};
