# Showing evidence

## Show the document, do not retell it

Every claim that rests on a source gets three layers. The surface states the
claim in plain language. The popup explains it, shows the source, and says what
is and is not verified. One underlined link opens the authoritative original.
A source link never bypasses the explanation, and the popup never merely
repeats the surface.

The whole semantically named card, row, node, mark, or underlined phrase is the
disclosure control. Do not add a generic `Evidence` or `View evidence` label,
raw citation, URL, repeated `Source:` link, count badge, or source carousel. A
data figure may need one compact plain-text provenance note in its footer; it
names the record and scope without becoming a link. The only original-source
link lives at the end of its popup.

Choose the popup by purpose. A `source` popup presents the specific record,
supporting passage, locator, status, and provenance that matter. An `explainer`
popup explains a mechanism in plain language without forcing citation chrome.
A `detail` popup gives the consequence, qualification, or drill-down promised
by one surface element and adds source material only when needed. Each new v4
popup contains an editable title, optional lede, and one or more structured
sections; a source popup ends with one underlined original-source link or an
explicit unavailable state. When capture is authorized and possible, a matched
source clip may supplement the relevant section. Provenance and currentness
remain structured data, never copy the editor can upgrade.

In Edit mode, every rendered substantive popup field is editable: `popup.title`,
optional `popup.lede`, and each `popup.sections[n].heading` and
`popup.sections[n].body`. Each popup retains its `data-evidence-id`; each
editable node declares its `data-evidence-field`. Compatibility fields such as
`cite`, `locator`, `detail`, and `excerpt` remain in portable evidence data but
do not impose a universal visible layout on new v4 output.
Commit edits to portable state on blur or the corresponding field action,
mirror them to recovery storage, and restore them after page navigation,
Save, and reopen. Status remains structured, is not free text, and
cannot be upgraded by an edit. Treat the result as a lawyer edit to the
presentation; it never upgrades support, coverage, or currentness. Re-run the
source-fidelity gate after any substantive evidence edit.

## Capture real source excerpts

When a source passage is central to an issue slide, place the shared
`sourcePreview` evidence unit in the right support column as well as keeping its
popup. It displays the same permitted clip or explicit exact excerpt, with a
caption and one source-detail target. A graphic may sit above it when it explains
a different relationship. Keep a short excerpt readable at its native size;
never enlarge a few words into a fake full-page document. If no exact excerpt or
capture is available, do not fill this slot with an invented source quotation.

When an authorized source is available, prefer a clip rendered from that source's
actual bytes or live page. It shows typography and context that a retyped quote
cannot. Never generate an image to imitate a document. If no source rendering is
available, show an exact text excerpt and an honest unavailable-image note.
When the user requests source clips, attempt the real capture workflow and
include the permitted matched clips in the relevant popups. Do not silently
substitute paraphrases or source links. Report any capture or permission gap.

The optional `scripts/exhibit.py` helper locates and highlights a unique passage,
crops its real rendering, and writes the PNG plus a provenance sidecar. Run from
the installed skill directory, with an available Python environment:

```sh
python scripts/exhibit.py pdf --pdf source.pdf --page 4 --start "First unique words" --end "Last unique words." --out clip.png --pdf-out clip.pdf
python scripts/exhibit.py web --url https://example.org/source --contains "Unique source passage" --out clip.png
python scripts/exhibit.py attach --png clip.png --locator "Source p. 4, cited paragraph" --alt "Highlighted source passage" --out clip.exhibit.json
```

`--pdf-out` is optional. Its PDF contains exactly the PNG's rendered pixels, not
hidden surrounding page text: a **highlighted raster excerpt companion**, not
the original PDF or a newly typeset quotation. `attach` checks the source, PNG,
any companion, and receipt before writing the direct JSON object to assign to
`evidence[].exhibit`. It does not change evidence status. Keep companions and
their receipts beside the delivered artifact; PDF attachment links are not part
of the current popup schema. Do not replace the authoritative-original link
with a local PDF path or a PDF data URI.

For an authorized downloaded HTML source, first print its actual bytes locally:

```sh
python scripts/exhibit.py html --html source.html --source-url https://example.org/filing --out source.browser.pdf --browser /path/to/chromium
python scripts/exhibit.py pdf --pdf source.browser.pdf --page 4 --start "First unique words" --end "Last unique words." --out clip.png --pdf-out clip.pdf
python scripts/exhibit.py attach --png clip.png --locator "Printed filing p. 3; browser PDF page 4" --alt "Highlighted filing passage" --out clip.exhibit.json
```

This is a **browser-rendered PDF of supplied HTML**, never a publisher-original
PDF. Scripts and service workers are disabled; only files under the HTML's
folder are served, with external/escaping requests blocked. The `.pdf.json`
receipt lists loaded local resource hashes and missing/blocked resources.
Inspect it and the rendered pages before clipping; missing fonts, images or
other material content can make a rendering unsuitable. The helper records but
does not fetch `--source-url`. It uses print CSS, Letter paper by default
(`--paper A4` is available), source CSS page sizes when present, and no browser
headers/footers. Browser page indices need not match printed filing numbers.
Keep the HTML, resource files and render receipt: subsequent captures bind the
original HTML → browser PDF → PNG/companion PDF hash chain, and `attach` retains
the distinction in the popup's capture record.

PDF capture requires PyMuPDF; web/HTML capture requires Playwright and an installed
Chromium (optional `--browser PATH`). Dependencies are optional, never silently
installed. Prefer a host's native screenshot/crop capability if those are absent.
A licensed source is user/firm-selected; the open-source helper is the default.

Build a source/locator list once. Reuse one clip wherever the same source passage
supports the explanation. PDF/HTML capture reuses output only when the source,
request, resource and paired-output checksums match. A different request, missing
companion, changed resource or altered existing output requires new output paths,
not a silent overwrite. Failed paired writes remove only their own new files.
Repeated/ambiguous text fails closed: supply a
longer unique passage or use exact host selection. Do not keep retrying a guessed
page or start/end string.

The PDF matcher selects one page and expects each boundary phrase within one
printed line. For a passage spanning pages, capture each required page separately
and preserve their order and qualifications; do not silently drop the continuation.
For an explicitly requested short phrase, add `--tight --context 0`: it crops to
that phrase's highlight bounds and refuses multiline selections. Inspect the
crop for legibility and sufficient context, and keep the full source available.

Check each clip visually. Record source identity, locator, captured passage,
source/output hashes and sizes where available, renderer, timestamp, crop and
highlight coordinates. PDF hashes bind exact input bytes; a web DOM hash is only
a capture-integrity marker, not proof that the live page is an authenticated
original. Source files are never edited. The client keeps permitted clips;
template export removes their bytes and identifying metadata.

In a v4 build plan, attach a permitted clip as `evidence[].exhibit` with a PNG/JPEG base64 `data` URI, image `sha256`, `sourceSha256`, `locator`, `captureMethod`, `capturedAt`, and descriptive `alt`. The decoded image is limited to 4 MiB. `sourceSha256` identifies the immediate capture input (the PDF for PDF capture); the HTML origin remains separately identified in its receipt and capture method. For live web capture, this field carries the explicitly labelled DOM capture-integrity hash, not an authenticated source-file hash. A supplied excerpt remains `supplied-unverified` in the image record even when its bytes and checksum match; neither a hash nor a functioning popup proves authenticity. Preserve the originating evidence status separately. An optional `excerpt` must reproduce exact source words. If a supplied narrative and its attached clip differ, state which source supports which assertion; never silently repair or present a narrative quotation as text visible in the clip.

## In each export

The client export keeps the purposeful popups and their permitted clips. The template export replaces every popup title, lede, section heading, section body, clip, link, and provenance value with descriptive placeholders suited to that popup's purpose; it also sanitizes compatibility citation, locator, detail, and excerpt fields. A template therefore carries no matter and still teaches what each popup is for.

## Grounding data contract

A preferred item contains:

- a stable item ID and the version or scope in which it is stable;
- exact citation or record label and the proposition it supports;
- source ID and canonical link, if supplied;
- pinpoint or locator and exact supporting excerpt;
- matched supplied-source image or exhibit, when available and permitted;
- source type, identity, retrieval or capture date, and provenance;
- separate support, coverage, severity, and currentness fields; and
- every limitation or unresolved issue supplied by the originating workflow.

Preserve those fields in the artifact or its accessible evidence layer. Do not
convert “supplied,” “retrieved,” “source exists,” or “green” into “verified.” If
a source is inaccessible, show a short disclosure instead of a placeholder
image. Keep recommended changes as advice; never apply them silently.

## Cite-check handoffs

For a cite-check v2 aggregate and manifest, read [cite-check-adapter.md](cite-check-adapter.md) before mapping support, coverage, currentness, paths or matched-source images. Its fail-closed provenance rules are required for that handoff; they are not a second general design workflow.
