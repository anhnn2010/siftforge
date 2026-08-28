# SiftForge

Reusable Python data extraction pipeline with validation, fallback strategies,
and cost-aware AI routing.

The first real application is scanned-book/PDF → structured book → EPUB.

## Development baseline

SiftForge currently targets **Python 3.12.x**, with **Python 3.12.3** as the
official local-development and CI baseline.

```bash
python --version
# Python 3.12.3
```

## Design rules

1. Domain code must not depend on a specific AI/OCR provider.
2. Mechanism and routing policy are separate.
3. Prefer the cheapest capable extraction method.
4. Important stages produce inspectable artifacts.
5. `extraction` works with generic tasks/results, not `Book`/`Chapter`/`EPUB`.
6. Add abstractions from real use cases; do not build a framework in advance.
7. Python code uses complete type annotations and clear docstrings.
8. Prompts and structured-output schemas are named and versioned artifacts.

## Current architecture

```text
src/siftforge/
├── extraction/
│   ├── artifacts/
│   ├── materializers/
│   ├── models/
│   ├── providers/
│   │   └── gemini.py
│   ├── runtime/
│   ├── sources/
│   └── validation/
└── ebook/
    ├── extraction/
    │   └── contracts.py
    ├── models/
    ├── pipeline/
    └── renderers/
```

## Milestone 1A - PDF source discovery

`PDFSource` discovers each PDF page as an independent `SourceRef` and records
stable hashes/provenance.

## Milestone 1B - Source materialization

`PDFPageMaterializer` extracts the original encoded JPEG bytes from compatible
image-only PDF pages without rendering or re-encoding them.

## Milestone 1C - Provider and structured-output contracts

The generic extraction task now carries:

- one or more `MaterializedAsset` objects;
- a versioned `PromptSpec`;
- a versioned `ExtractionSchema`;
- a provider-independent capability name.

The first real provider is `GeminiProvider`, but the ebook application does not
import or depend on Gemini.

```text
PDFSource
  ↓
SourceRef
  ↓
PDFPageMaterializer
  ↓
MaterializedAsset
  ↓
ExtractionTask
  ├── capability
  ├── PromptSpec(name + version)
  └── ExtractionSchema(name + version + JSON Schema)
  ↓
GeminiProvider
  ↓
ExtractionResult
  ├── raw JSON text
  ├── parsed structured data
  └── Attempt provenance
```

The initial ebook contract is intentionally fidelity-first:

- transcribe instead of summarize/rewrite;
- preserve visible reading order;
- classify semantic blocks;
- separate probable headers, footers, and printed page numbers;
- report uncertainty instead of guessing.

## Install for development

Core + test dependencies:

```bash
pip install -e ".[dev]"
```

Gemini provider support:

```bash
pip install -e ".[dev,gemini]"
```

No Gemini model name is hard-coded into the project. A caller must choose a
model explicitly so model selection remains policy/configuration rather than
ebook-domain logic.
