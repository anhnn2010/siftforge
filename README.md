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

## Initial architecture

```text
src/siftforge/
├── extraction/
│   ├── artifacts/
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

## Milestone 0

This repository currently contains only the architectural skeleton and
contract tests. The first vertical slice will use a real vFlat-exported PDF:

```text
PDFSource
  ↓
ExtractionTask
  ↓
Extractor / Provider
  ↓
Normalizer
  ↓
Validator
  ↓
Book model
  ↓
EPUB renderer
```
