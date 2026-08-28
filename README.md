# SiftForge

Reusable Python data extraction pipeline with validation, fallback strategies,
and cost-aware AI routing.

The first real application is scanned-book/PDF → structured book → EPUB.

## Development baseline

SiftForge currently targets **Python 3.12.x**, with **Python 3.12.3** as the
official local-development and CI baseline.

## Design rules

1. Domain code must not depend on a specific AI/OCR provider.
2. Mechanism and routing policy are separate.
3. Prefer the cheapest capable extraction method.
4. Important stages produce inspectable artifacts.
5. `extraction` works with generic tasks/results, not `Book`/`Chapter`/`EPUB`.
6. Add abstractions from real use cases; do not build a framework in advance.
7. Python code uses complete type annotations and clear docstrings.
8. Prompts and structured-output schemas are named and versioned artifacts.

## Milestone 1D - One-page Gemini smoke run

The first executable vertical slice is now available:

```text
vFlat PDF
  ↓
PDFSource
  ↓
SourceRef
  ↓
PDFPageMaterializer
  ↓
original JPEG MaterializedAsset
  ↓
versioned ebook prompt + JSON Schema
  ↓
GeminiProvider
  ↓
ExtractionResult
  ↓
filesystem artifacts
```

The ebook application owns the page-transcription prompt/schema. Gemini remains
a generic extraction provider and does not import ebook-domain code.

### Install

```bash
pip install -e ".[dev,gemini]"
```

### Authentication

Use a Gemini Developer API key through an environment variable. Do not put the
key in the repository or command history.

```bash
export GEMINI_API_KEY='...'
```

The Google SDK also supports `GOOGLE_API_KEY`; set only one when possible.

### Run one real page

For example:

```bash
siftforge ebook extract-page \
  --pdf /path/to/18-nam-kim-cuong.pdf \
  --page 18 \
  --model gemini-3.6-flash
```

`--model` is intentionally explicit. Model selection belongs to routing/config
policy, not ebook-domain code.

By default the run is written under:

```text
runs/<pdf-stem>/page-0018/
├── assets/
│   └── page-0018.jpg
├── manifest.json
├── normalized/
│   └── page.json
└── raw/
    └── provider-response.json
```

No batch processing is enabled yet. Milestone 1D is deliberately limited to a
single page so prompt/schema behavior can be inspected before spending quota on
the complete document.
