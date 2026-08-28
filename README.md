# SiftForge

Reusable Python data extraction pipeline with validation, fallback
strategies, and cost-aware AI routing.

The first real application is scanned-book/PDF → structured book → EPUB.

## Design rules

1. Domain code must not depend on a specific AI/OCR provider.
2. Mechanism and routing policy are separate.
3. Prefer the cheapest capable extraction method.
4. Important stages produce inspectable artifacts.
5. `extraction` works with generic tasks/results, not `Book`/`Chapter`/`EPUB`.
6. Add abstractions from real use cases; do not build a framework in advance.
7. Python code uses complete type annotations and clear docstrings.

## Current architecture

```text
src/siftforge/
├── extraction/
│   ├── artifacts/
│   ├── materializers/
│   ├── models/
│   ├── providers/
│   ├── runtime/
│   ├── sources/
│   └── validation/
└── ebook/
    ├── models/
    ├── pipeline/
    └── renderers/
```

## Milestone 1A - PDF source discovery

`PDFSource`:

- analyzes a PDF without ebook-specific assumptions;
- exposes every page as an independent `SourceRef`;
- records document/page hashes and provenance metadata;
- distinguishes native-text, image-only, mixed, and blank pages;
- inspects embedded image streams without rendering the page.

The first real vFlat fixture contains 432 image-only pages, with exactly one
`/DCTDecode` JPEG image stream per page.

## Milestone 1B - Source materialization

`PDFPageMaterializer` converts a logical PDF-page `SourceRef` into a local
`MaterializedAsset`.

For the current vFlat fixture it extracts the original encoded JPEG bytes directly
from the PDF instead of rendering the page or using a higher-level image helper
that may decode/re-encode the image.

```text
PDFSource
  ↓
SourceRef
  ↓
PDFPageMaterializer
  ↓
MaterializedAsset (original JPEG)
  ↓
ExtractionTask
  ↓
Provider / OCR / AI
```

The materializer is PDF-specific while the resulting asset is generic. Downstream
providers therefore do not need to know that the image originally lived in a PDF.
