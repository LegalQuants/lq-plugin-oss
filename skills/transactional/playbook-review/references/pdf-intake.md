# PDF intake and document reading paths

## Digital fast-path rule

If a document is a native digital `.docx`, `.md`, or `.txt` file, or a `.pdf` with searchable text extracted via native text methods with zero extraction errors, DO NOT convert to PDF and DO NOT rasterize page images. Mark pages as `native-text` with readability `readable` immediately.

Visual page rendering and PNG generation are strictly restricted to:
1. Genuine unsearchable scanned PDFs (OCR required).
2. Image-only signature pages or wet-ink execution blocks.

For native digital `.docx` documents, parse the structured paragraphs, tables, and tracked changes directly without external conversion. For digital `.pdf` documents with selectable text layers, extract the text stream directly.

## Reading paths for PDFs

PDF support has two reading paths:

1. **Digital fast-path (native text):** Use reliable native text when it exists. If searchable text is extracted with zero extraction errors, record each page as `native-text` with readability `readable`.
2. **Visual inspection path:** Render and visually read image-only, scanned, or uncertain pages with the host's document-vision capability.

Do not describe visual reading as guaranteed OCR. For every page, record one of `native-text`, `vision`, `mixed`, `pending-vision`, or `unreadable`, plus the readability result and any uncertainty.

The deterministic script hashes the PDF and extracts native text if a text layer or reader is available. If native text cannot be read deterministically, it marks the document for host reading. The host then records the page count, applies native text where available, and renders/inspects only scanned or uncertain pages, adding source elements with stable IDs. If that capability is not available, keep the document pending and do not claim complete coverage.

Before using visually read text as provenance, an exact quotation, or a markup anchor, reconcile it against the rendered page. If exactness remains uncertain, mark the page partial, park the affected element for manual review, and keep it out of any completeness claim.

Encrypted PDFs, illegible pages, missing pages, and unsupported embedded objects stay visible in the source census. Do not silently omit or repair them.
