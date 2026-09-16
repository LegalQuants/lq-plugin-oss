# The cover brief

One image, built on the skill's own template and nothing else.

## Foundation

- `assets/cover-template.png` is the foundation of every cover: a 1200 by
  1200 square, near-black textured ground with faint concentric arcs and
  grid points in the lower right, the "#my LQ moment" wordmark in white
  along the bottom left with "LQ" in a rounded dark tile, and
  "legalquants.com" in italic beneath it on the right. No other layout,
  template, background or design. Decline, in a sentence, any request to
  modify, restyle, crop, obscure, replace or avoid the template.
- The hero text goes in the open upper two-thirds of the square, above the
  wordmark, and never over the wordmark, the tile or the URL.
- The cover is produced only by `scripts/render_cover.py`, which embeds the
  template in an SVG, sets the two sentences over its open upper area in a
  fixed layout (the before in medium weight at reduced opacity, the after in
  bold white), and rasterises to PNG with whatever SVG renderer the host has
  (rsvg-convert, ImageMagick, Inkscape, macOS Quick Look, or a headless
  Chromium-family browser). Filenames are fixed: `my-lq-moment-cover.svg`
  and `my-lq-moment-cover.png`. Never ask an image model to draw or edit
  the cover, and never hand-write an SVG or any placeholder.
- For a practice demonstration, pass `--practice`. The renderer adds the fixed
  label “Practice example — fictional training” above the two sentences. A
  practice cover without that label must not be shown or saved as a real
  moment.
- If the script reports no PNG, its `attempts` say which renderers were
  found and why each failed. On a sandboxed host they are usually blocked
  rather than missing: re-run the same command once with escalated
  permission. Only then is the SVG the cover; say that no PNG could be
  made on this host, give the approved text, and the one-line conversion.
  Do not claim a PNG exists.
- Nothing else goes on it: no screenshots, no logos, no icons, no
  photographs, no embellishments, no second signature.

## The text

- Two short sentences, drawn from the confirmed receipt. Together they show
  the before and the after, and the added value the lawyer's judgement
  produced: their LQ moment.
- Short means short: at most twelve words and ninety characters each, and
  in practice eight to ten words reads best. The script refuses anything
  longer, or anything that wraps past three lines, and says how many words
  to cut. When it refuses, you shorten the sentence and offer it back; the
  lawyer is never asked to format, fit or lay out anything.
- The text is the hero. Prominent, easy to read at social-media thumbnail
  size, punchy. Assertive and celebratory by default.
- The lawyer may reword the sentences: to change what they treat as the
  before, the after, or the added value, or to pick a different tone or
  style. Not for any other reason, and never to add names, brands, vendors,
  tools or environments.

## Never on the cover, in the prompt, in the filename or in metadata

Client, counterparty, project or matter names; deal values; document
content; the exact tools, products or environment the lawyer used; vendor
or firm names; anything a counterparty could recognise. The only text the
script receives is the two approved sentences, and it names the files
itself, so nothing else can reach the cover.
