# SiftForge

Reusable Python data extraction pipeline with validation, fallback strategies,
and cost-aware AI routing.

The first real application is scanned-book/PDF → structured book → EPUB.

## Development baseline

SiftForge targets **Python 3.12.x**, with **Python 3.12.3** as the official
local-development and CI baseline.

## Milestone 1E-r1 - Explicit typography state

A real page-18 smoke test showed why an empty formatting-mark list is ambiguous:

```text
marks = []
```

could mean either:

```text
the text is confidently roman
```

or:

```text
the model did not detect a style
```

SiftForge now models mutually exclusive typography states explicitly.

```json
{
  "text": "Nguyên văn bản tiếng Anh:",
  "typography": {
    "posture": "roman",
    "weight": "normal",
    "vertical_position": "baseline",
    "caps_style": "normal",
    "decorations": []
  }
}
```

Italic with superscript is represented independently:

```json
{
  "text": "th",
  "typography": {
    "posture": "italic",
    "weight": "normal",
    "vertical_position": "superscript",
    "caps_style": "normal",
    "decorations": []
  }
}
```

The explicit states are:

```text
posture:
  roman
  italic
  unknown

weight:
  normal
  bold
  unknown

vertical_position:
  baseline
  superscript
  subscript
  unknown

caps_style:
  normal
  small_caps
  unknown

decorations:
  underline
```

Letter case remains encoded directly in `text`. `small_caps` is separate because
it is a typographic style rather than merely uppercase text.

`unknown` is a first-class result. The extraction prompt tells the model to use
it instead of guessing when a style is visually uncertain.

## Current vertical slice

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
ebook prompt + JSON Schema v4
  ↓
GeminiProvider
  ↓
raw provider JSON
  ↓
EbookPageNormalizer
  ↓
typed PageContent
  ↓
normalized/page.json + manifest.json
```

### Current smoke test

```bash
siftforge ebook extract-page \
  --pdf 18-nam-kim-cuong.pdf \
  --page 18 \
  --model gemini-3.6-flash
```

The page-18 acceptance check is especially useful because it contains:

- Vietnamese and English blocks
- roman and italic text
- superscript text
- a printed page number
- a running footer
