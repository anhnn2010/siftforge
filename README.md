# SiftForge

Reusable Python data extraction pipeline with validation, fallback strategies,
and cost-aware AI routing.

The first real application is scanned-book/PDF → structured book → EPUB.

## Development baseline

SiftForge targets **Python 3.12.x**, with **Python 3.12.3** as the official
local-development and CI baseline.


## Quick workflow: scanned PDF to final human-proofed EPUB

This is the recommended end-to-end workflow for a real book. The detailed
milestone sections later in this README explain each command and artifact; use
this section as the day-to-day cheat sheet.

```text
PDF
 ↓
extract-book                         machine extraction
 ↓
runs/<book>/page-NNNN/normalized/page.json
 ↓
extract-metadata                     metadata + cover
 ↓
review-text                          Gemini text ↔ local OCR
 ↓
review/report.html                   HUMAN REVIEW #1: suspicious findings
 ↓
export siftforge-review-resolutions.json
 ↓
import-review                        creates page-local corrections.json
 ↓
review-status                        optional audit / strict review check
 ↓
build-epub                           applies corrections, builds structure/XHTML
 ↓
<book>-build/epub-ready/             machine-owned / regeneratable
 ↓
prepare-proof                        freeze generated XHTML once
 ↓
<book>-build/proof/                  HUMAN REVIEW #2: final proofreading
 ↓
backup-book                          sync durable book sources to Git workspace
 ↓
package-epub --proof                 package the human-edited master
 ↓
dist/<book>.epub                     final distribution copy
```

### 1. Extract the whole book

```bash
siftforge ebook extract-book \
  --pdf 18-nam-kim-cuong.pdf \
  --model gemini-3.6-flash \
  --runs-root runs/18-nam-kim-cuong \
  --routing-policy free-then-paid
```

The run is resumable. Existing valid page extractions are reused. When Gemini
stops a page with `RECITATION`, the default recovery path uses local Tesseract
OCR and marks that page `needs_review=true`; these recovered pages deserve extra
human attention.

To audit pages that still have no normalized extraction:

```bash
PDF="18-nam-kim-cuong.pdf"
RUN="runs/18-nam-kim-cuong"
TOTAL=$(pdfinfo "$PDF" | awk '/^Pages:/ {print $2}')
for n in $(seq 1 "$TOTAL"); do
  page_dir=$(printf "%s/page-%04d" "$RUN" "$n")
  [ -f "$page_dir/normalized/page.json" ] || printf "page-%04d\n" "$n"
done
```

### 2. Extract and review book metadata / cover

```bash
siftforge ebook extract-metadata \
  --pdf 18-nam-kim-cuong.pdf \
  --model gemini-3.6-flash \
  --routing-policy free-then-paid
```

Review or edit:

```text
runs/18-nam-kim-cuong/metadata.json
runs/18-nam-kim-cuong/cover.jpg
```

`metadata.json` is intentionally human-editable.

### 3. Compare extracted text with local OCR

Use a Tesseract language that is installed locally. For a Vietnamese-only
installation:

```bash
siftforge ebook review-text \
  --runs-root runs/18-nam-kim-cuong \
  --ocr-language vie
```

The command prints live progress. When it finishes, open:

```bash
xdg-open runs/18-nam-kim-cuong/review/report.html
```

`report.html` is HUMAN REVIEW #1. Resolve actionable findings with **Keep
source**, **Use OCR**, **Use suggestion**, or **Manual**, then export
`siftforge-review-resolutions.json` from the report.

### 4. Import the review decisions

```bash
siftforge ebook import-review \
  --runs-root runs/18-nam-kim-cuong \
  --resolutions ~/Downloads/siftforge-review-resolutions.json
```

This creates page-local artifacts such as:

```text
page-NNNN/review/resolutions.json
page-NNNN/review/corrections.json
```

`corrections.json` is an internal build overlay. Normally do not edit or manage
it by hand. `build-epub` automatically applies it on top of immutable
`normalized/page.json`.

Optional review audit:

```bash
siftforge ebook review-status \
  --runs-root runs/18-nam-kim-cuong
```

### 5. Build the generated EPUB/XHTML

```bash
siftforge ebook build-epub \
  --runs-root runs/18-nam-kim-cuong \
  --output dist/18-nam-kim-cuong.epub
```

If the scanned PDF contains printed pages that should not appear in the final
EPUB, such as a legacy printed table of contents, exclude them by their
**one-based physical PDF page numbers**:

```bash
siftforge ebook build-epub \
  --runs-root runs/18-nam-kim-cuong \
  --exclude-pages 7-10,14 \
  --output dist/18-nam-kim-cuong.epub
```

Exclusion is non-destructive: the corresponding `page-NNNN/` extraction and
review artifacts remain under `runs/`. They are simply omitted from book
assembly, XHTML, and the packaged EPUB. SiftForge also refuses unknown page
numbers instead of silently accepting a typo. Cross-page continuation analysis
still uses physical PDF page provenance, so excluding a gap cannot accidentally
join text across nonconsecutive pages.

This consumes normalized extraction + imported corrections + metadata, performs
book-level structure analysis, semantic projection, and EPUB rendering. The
important generated workspace is:

```text
runs/18-nam-kim-cuong-build/epub-ready/
```

`epub-ready/` is machine-owned and safe to regenerate. Do not treat manual edits
there as permanent.

For a release-quality build that must have a complete review state, add:

```text
--require-reviewed
```

### 6. Create the human proofreading master

After the generated XHTML looks structurally correct, create the proof workspace
once:

```bash
siftforge ebook prepare-proof \
  --epub-ready runs/18-nam-kim-cuong-build/epub-ready \
  --output runs/18-nam-kim-cuong-build/proof
```

From this point, HUMAN REVIEW #2 happens in:

```text
runs/18-nam-kim-cuong-build/proof/text/chapter-XXXX.xhtml
```

This is the official final editable text layer. Use it for typos or formatting
problems discovered while reading the book that were not caught by OCR compare.
The proof directory is human-owned and is not overwritten unless
`prepare-proof --force` is explicitly requested.

### 7. Back up the human book master for Git

Once a proof workspace exists, synchronize the durable human work into a compact
Git-friendly directory:

```bash
siftforge ebook backup-book \
  --runs-root runs/18-nam-kim-cuong \
  --proof runs/18-nam-kim-cuong-build/proof \
  --output ~/projects/siftforge-books/18-nam-kim-cuong
```

The destination can already be a Git working tree. Re-running the command updates
only SiftForge-managed backup artifacts and preserves `.git` plus unrelated files
such as personal notes. The backup contains:

```text
18-nam-kim-cuong/
├── proof/                    # complete human-owned, packageable master
├── metadata.json             # when present in runs root
├── review/
│   └── resolutions.json      # when review decisions were imported
├── build-info.json           # portable build facts such as excluded pages
└── backup-manifest.json      # compact backup inventory + edited XHTML list
```

Extraction caches, provider responses, local OCR caches, page diagnostics, and
`epub-ready/` are intentionally not copied. They are either large or
regeneratable and do not belong in the human-history Git repository. The final
`.epub` is also omitted because Git tracks the XHTML sources much more usefully
than repeated ZIP-format EPUB binaries.

A typical history workflow is therefore:

```bash
cd ~/projects/siftforge-books/18-nam-kim-cuong
git status
git add .
git commit -m "proof: update 18 nam kim cuong"
git push
```

Run `backup-book` again after another proofreading session, then review the Git
diff before committing.

### 8. Package the final EPUB from proof

Once proof editing has started, do **not** use `build-epub` as the source of the
final distribution copy. Package directly from the human-edited proof workspace:

```bash
siftforge ebook package-epub \
  --proof runs/18-nam-kim-cuong-build/proof \
  --output dist/18-nam-kim-cuong.epub
```

The source-of-truth distinction is:

```text
--runs-root  → machine pipeline; regenerates derived XHTML
--proof      → human-final pipeline; packages final proofreading edits
```

### Files a normal user should care about

| File / directory | Purpose | Edit by hand? |
|---|---|---|
| `review/report.html` | Review machine-detected text concerns | Yes, through the HTML UI |
| `metadata.json` | Title, author, publisher, ISBN, cover reference, etc. | Yes |
| `proof/text/*.xhtml` | Final human proofreading master | Yes |
| Git backup from `backup-book` | Durable history of proof + metadata + review decisions | Commit/push |
| `normalized/page.json` | Canonical extraction evidence | No |
| `review/corrections.json` | Imported machine-readable correction overlay | No |
| `epub-ready/` | Generated XHTML/package workspace | No; regenerate instead |
| `dist/*.epub` | Final distribution artifact | No |

In short: **review in `report.html`, edit metadata in `metadata.json`, and do final
free-form proofreading in `proof/text/*.xhtml`.** Everything else is primarily a
machine artifact or diagnostic trail.

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
ebook page-evidence prompt 5.2 + JSON Schema v5
  ↓
GeminiProvider
  ↓
raw provider JSON
  ↓
EbookPageEvidenceNormalizer
  ↓
typed PageExtraction
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


## Milestone 1F-2 - Staged page-evidence contract v5

Milestone 1F-2 adds a new **v5 prompt/schema contract in parallel** with the
working v4 runtime. The CLI still uses v4 until the dedicated v5 normalizer is
implemented in Milestone 1F-3.

The staged v5 contract is designed from the real-page regression round and adds:

- page-local role hints instead of treating extraction as final book semantics
- one `list_item` block per locally apparent list item
- `verse` blocks with explicit semantic line breaks
- source typography explicitly separated from semantic EPUB emphasis
- language at text-span level
- visual marker evidence separated from readable text
- graphic markers that must not be replaced by arbitrary Unicode glyphs/emoji
- heading role hints separated from heading-level hints
- normalized image regions for later figure cropping
- local attribution evidence

Stable block/span IDs are intentionally **not generated by the AI**. Downstream
normalization assigns deterministic IDs from the source-page identity and array
order, keeping repeated runs auditable and diff-friendly.

The active compatibility aliases remain:

```text
EBOOK_PAGE_PROMPT -> v4
EBOOK_PAGE_SCHEMA -> v4
```

The staged contract is available explicitly as:

```text
EBOOK_PAGE_PROMPT_V5
EBOOK_PAGE_SCHEMA_V5
```

## Milestone 1F-3 - Strict v5 page-evidence normalizer

Milestone 1F-3 adds `EbookPageEvidenceNormalizer`, which converts provider JSON
matching the staged v5 contract into immutable `PageExtraction` evidence.

The normalizer is intentionally strict and page-local. It:

- assigns deterministic block/span IDs from `page_id` and array order
- preserves span-level language and semantic line-break evidence
- validates source typography without mapping it to EPUB emphasis
- validates heading hints and rejects heading-only hints on non-heading blocks
- preserves marker evidence without inferring final list semantics
- validates normalized source regions, including cross-field page bounds
- rejects duplicate text decorations and silent type coercion
- rejects unknown/missing contract properties when called directly
- serializes normalized evidence with source provenance and generated IDs

Stable evidence IDs are shared with the v4 compatibility adapter through the
same identity helpers, so migration does not introduce a second ID convention.

The proven CLI runtime still uses the v4 aliases in this milestone:

```text
EBOOK_PAGE_PROMPT -> v4
EBOOK_PAGE_SCHEMA -> v4
```

The v5 contract and normalizer can now be exercised explicitly. Runtime
integration and golden-page execution are deferred to the next milestone so
this commit does not change the existing `extract-page` behavior.


## Milestone 1F-4 - Active v5 extraction path

Milestone 1F-4 promotes the page-evidence contract to the canonical runtime path.
The unchanged smoke command now uses **v5** by default:

```bash
siftforge ebook extract-page \
  --pdf 18-nam-kim-cuong.pdf \
  --page 18 \
  --model gemini-3.6-flash
```

The active path is now:

```text
PDF page
  ↓
original embedded JPEG
  ↓
EBOOK_PAGE_PROMPT_V5 + EBOOK_PAGE_SCHEMA_V5
  ↓
GeminiProvider
  ↓
EbookPageEvidenceNormalizer
  ↓
PageExtraction
  ↓
normalized/page.json + manifest.json
```

`normalized/page.json` now contains deterministic block/span IDs plus the
page-local evidence needed by the future book structural pass: span language,
source typography, semantic verse line breaks, marker evidence, heading-role
hints, and image regions.

The old v4 path remains available for controlled regression/A-B comparisons:

```bash
siftforge ebook extract-page \
  --pdf 18-nam-kim-cuong.pdf \
  --page 18 \
  --model gemini-3.6-flash \
  --contract-version 4 \
  --run-dir runs/v4/page-0018
```

For a comparable v5 artifact, use a separate run directory:

```bash
siftforge ebook extract-page \
  --pdf 18-nam-kim-cuong.pdf \
  --page 18 \
  --model gemini-3.6-flash \
  --run-dir runs/v5/page-0018
```

The compatibility aliases now point to the active contract:

```text
EBOOK_PAGE_PROMPT -> v5
EBOOK_PAGE_SCHEMA -> v5
```

Explicit `EBOOK_PAGE_PROMPT_V4` and `EBOOK_PAGE_SCHEMA_V4` names are retained so
historical v4 extraction remains reproducible while the golden-page comparison
round is performed.

## Milestone 1F-4r1 - Regression-tuned v5 prompt revision

A nine-page v5 regression round validated the core evidence design on pages 18,
68, 116, 152, 378, 397, 398, 402, and 412. The schema and strict normalizer remain
unchanged; this milestone introduces prompt revision **5.1** so historical prompt
v5 artifacts stay reproducible.

The revision tightens three behaviors observed in those real pages:

- typography boundaries: classify short labels and transition lines from their own
  visible glyphs instead of inheriting roman/italic styling from neighbors
- semantic line breaks: preserve verse lines, collapse ordinary heading/prose wraps,
  and require the final verse line to end with `semantic_line_break_after=false`
- heading roles: recurring `TÌNH HUỐNG` labels remain `scenario_label` whether or not
  a separate scenario title is present on the same page

It also explicitly tells the extractor not to create separate spans solely because a
heading or prose line wraps physically. This prevents a false semantic break from
leaving two adjacent spans that would concatenate without the source word boundary.

The active pairing is now:

```text
prompt: ebook_page_evidence 5.1
schema: ebook_page_evidence 5
```

The historical prompt remains available as `EBOOK_PAGE_PROMPT_V5`; the active
revision is `EBOOK_PAGE_PROMPT_V5_R1`. The normal smoke command is unchanged.

Recommended post-change regression pages:

```text
18   typography boundary: roman label between italic regions
68   verse line boundaries and final-line convention
152  verse vs physical heading wrap
398  italic transition line between roman paragraphs
402  scenario label + separate scenario title
412  scenario label without a separate title
```

## Milestone 1F-5 - Deterministic book structural analyzer skeleton

Milestone 1F-5 introduces the first book-level pass over ordered
`PageExtraction` evidence. It deliberately remains deterministic and
conservative: page evidence is interpreted only where the v5 contract already
provides strong signals, and uncertain cross-page reconstruction is kept as
scored candidate relationships rather than silently merged.

The new `BookStructuralAnalyzer` currently provides three core capabilities:

- **running furniture normalization**: `page_header`, `page_footer`, and
  `page_number` evidence is removed from logical body flow; duplicated printed
  page numbers at footer/header edges are stripped for comparison; repeated
  normalized furniture text is marked across pages
- **explicit list grouping**: contiguous v5 `list_item` evidence is grouped into
  `ListNode` containers, including across directly adjacent physical pages;
  numeric/alphabetic markers produce ordered lists and explicit ordinals are
  checked for sequence compatibility
- **continuation candidate detection**: only adjacent physical pages are
  considered, and likely continuations are emitted as scored
  `CONTINUES_TO` relationships using conservative evidence such as missing
  terminal punctuation, lowercase continuation, language agreement, and
  compatible boundary typography

The analyzer does **not** parse list markers out of arbitrary text. This keeps
real regression contrasts intact:

```text
page 378: explicit numeric marker evidence -> ordered list items
page 397: dash-prefixed dialogue -> paragraphs, not a list
page 412: graphic-marked dialogue -> paragraphs with visual marker evidence
```

Continuation detection and resolution remain separate. Lower-confidence
candidates stay as relationships for later review, while only the strongest
well-defined boundary shapes are consumed automatically by the structural
resolver.

The first pass also preserves already-explicit local structure where doing so is
lossless: headings become provisional `HeadingNode` values, quote evidence is
wrapped as a one-block `QuotationNode`, verse semantic line breaks become
`VerseNode`/`VerseLineNode`, and footnote/attribution evidence maps to the
matching logical leaf type. Unsupported evidence such as images/captions is
reported in `StructuralAnalysisResult.unresolved_blocks` instead of being
silently dropped; figure asset/caption resolution remains a later milestone.

Source typography is copied into logical spans but still produces **no semantic
`EMPHASIS` or `STRONG` marks**. Every logical span and node keeps deterministic
provenance back to the exact page/block/span evidence that produced it.

The existing `ebook extract-page` CLI is unchanged in this milestone. 1F-5 adds
book-level library behavior and tests only; a multi-page structural CLI/artifact
path can be added after the resolver behavior is proven.

## Milestone 1F-6 - Explicit structural container resolution

Milestone 1F-6 extends the deterministic book pass to resolve containers that
are already explicit in v5 page evidence. It deliberately does not add a new AI
call and does not infer hidden semantic boundaries from language-specific text.

The analyzer now resolves:

- **quotation runs**: adjacent same-page `quote` blocks become one
  `QuotationNode` containing paragraph children; a physical page boundary is
  kept unresolved unless continuation evidence supports a later merge
- **verse runs**: adjacent same-page `verse` blocks become one `VerseNode` while
  keeping each semantic `VerseLineNode` and its source provenance
- **figures**: an `image` block with a normalized source region becomes a
  `FigureNode`; an immediately following same-page `caption` is nested inside
  the figure, allowing page-116-style `image/caption/image/caption` evidence to
  become two independent figures

`ImageNode` now stores the normalized `source_region` directly. Its `asset_id`
is optional because this milestone resolves logical figure membership but does
not yet crop/materialize the derived image file. A later asset step can use the
region to produce the actual figure asset without changing the structural
association.

The resolver remains intentionally conservative when evidence is incomplete:

- an image without a source region is not given invented crop geometry; the
  image and immediately following caption remain in `unresolved_blocks`
- an orphan caption remains unresolved rather than attaching to a distant image
- a cross-page quotation is not silently merged; it may remain as two logical
  quotation containers connected by a scored `CONTINUES_TO` candidate

Embedded content needs a different treatment. Page 348 provides strong local
opening evidence through a `genre_label`, but the current page contract does not
reliably expose where that fable ends. Pages 397-398 are even more important:
the embedded excerpt is recognizable from meaning and author voice, not from a
stable visual role. The deterministic analyzer therefore records a
`ContainerResolutionCandidate` for strong genre-label openings while refusing
to consume following body paragraphs or add Vietnamese phrase-matching rules.
Unstyled embedded excerpts remain ordinary flow until a later semantic
container resolver can establish their boundaries.

This preserves the core boundary:

```text
page evidence says what was observed
        ↓
deterministic structural pass resolves explicit structure
        ↓
semantic resolver handles genuinely contextual boundaries
```

The `ebook extract-page` CLI remains unchanged.

## Milestone 1F-7 - Evidence-backed semantic relationships

Milestone 1F-7 extends the deterministic structural pass with semantic
relationships that can be resolved from explicit page-local evidence without a
new AI call. Relationships remain conservative: exact matches may be emitted
with confidence `1.0`, while contextual bilingual-pair inference stays a scored
candidate rather than silently rewriting document structure.

The analyzer now resolves three relationship families:

- **footnote references**: a label-shaped superscript span such as `1`, `2`,
  `*`, `†`, or `‡` links to a unique same-page `FootnoteNode` whose visible
  opening superscript label matches exactly. The relationship source is the
  exact source span ID, so an inline reference inside a paragraph or heading can
  point directly to the footnote body. Ambiguous duplicate labels remain
  unlinked. Superscript suffixes such as the `th` in `13th` are not treated as
  footnotes.
- **attributions**: an explicit `attribution` evidence block links to one
  unambiguous adjacent same-page quotation, verse, or inset container. If both
  neighbors are plausible targets, no relation is guessed.
- **translation candidates**: adjacent same-page quotation blocks with different
  known languages remain separate `QuotationNode` values and may receive a
  scored `TRANSLATION_OF` relationship. The later quotation is the candidate
  translation of the immediately preceding quotation. Adjacent attribution
  context raises confidence, but the result remains an evidence-backed
  candidate rather than a language-specific hard-coded rule.

Quotation grouping is now language-aware. Same-language adjacent quote blocks
still group into one multi-paragraph quotation, preserving page-87-style
behavior. A known language change splits the run so page-271-style bilingual
original/translation pairs remain addressable as separate logical containers.
Unknown language does not force a split.

Footnote labels are also stored on `FootnoteNode`. This was validated against
real historical extraction artifacts from pages 13 and 118: page 13 resolves
both labels `1` and `2`, while page 118 resolves the superscript `1` embedded in
a heading to its same-page footnote body.

The resolver intentionally does **not** parse author names, dates, affiliation
text, or translation semantics from prose. If v5 page evidence does not expose
an explicit attribution or quote role, the structural pass leaves that content
unchanged for a later semantic resolver.

### High-confidence cross-page prose continuation resolution

The structural analyzer consumes only the strongest `CONTINUES_TO` candidates.
Ordinary paragraph-to-paragraph boundaries resolve at the current maximum
confidence (`0.99`). They may also resolve at `0.95` when the lexical boundary
and language signals are all strong and the only missing signal is matching
source typography. This covers mixed-style paragraphs whose page-level
extraction flattened one side of the physical page break to a single posture.
A final list item may also continue as an unmarked paragraph at the top of the
next page; that stricter shape still requires `0.99` confidence and folds the
text into the existing `ListItemNode`, preserving the surrounding list rather
than flattening it. Lower-confidence prose, list, and quotation boundaries
remain unresolved candidates.

Running page furniture is removed before continuation detection. Bottom-of-page
footnotes are also treated as side content when locating the body boundary, so a
footnote after a still-open paragraph does not hide that paragraph from the next
page continuation. Headings, captions, and other structural blocks remain hard
boundaries and are never jumped over speculatively.

Resolved text keeps all source fragments in provenance. If normal inter-word
whitespace disappeared at the physical page break, the logical merge inserts a
synthetic unprovenanced space while leaving all source spans intact. The consumed
relationship is retained in `StructuralAnalysisResult.resolved_continuations`
for diagnostics and omitted from `BookDocument.relationships`, avoiding a
dangling unresolved link later in semantic projection.

The regression case from physical pages 15-16 of *18 Năm Kim Cương* now joins
`"...mẹ luôn cảm nhận và thấu"` with
`"hiểu con trong xúc động sâu sắc..."` into one logical paragraph containing
`"...mẹ luôn cảm nhận và thấu hiểu con..."`. Additional real-book regressions
cover a trailing footnote on pages 118-119, a list item continuing as an
unmarked paragraph on pages 127-128, and a mixed-style paragraph on pages
142-143 where the extracted posture differs across the boundary even though the
visible sentence continues.

## Milestone 1F-8 - Real-run golden regression fixture harness

Milestone 1F-8 turns the accepted v5 extraction pages into a checked-in,
data-driven regression suite. The fixtures are copied from real
`gemini-3.6-flash` runs rather than synthetic examples, while local filesystem
paths and unrelated source metadata are sanitized before they enter the
repository. Page images and raw provider responses are deliberately excluded;
the suite stores only normalized page evidence plus small provenance metadata.

The first golden set covers pages 18, 68, 116, 152, 378, 397, 398, 402, and
412. Together they protect the most important positive and negative cases found
through manual book testing:

- local roman/italic typography boundaries and superscript evidence
- semantic verse lines and final-line break convention
- multiple source-backed figures with normalized crop regions and captions
- physical heading wrapping versus semantic verse line breaks
- graphic list-marker evidence separated from readable item text
- ordered-list recovery for items 10-17
- dash-prefixed dialogue that must not become a list
- italic author-transition text between narrative regions
- scenario label/title roles with graphic markers
- graphic-marked dialogue that is visually list-like but semantically prose

`GoldenPageFixtureLoader` revalidates every stored normalized page through the
strict v5 normalizer. It also verifies deterministic page/block/span IDs before
a fixture can be used. This makes fixture corruption or normalized-artifact
drift fail early instead of silently changing structural expectations.

The suite intentionally asserts semantic facts rather than byte-for-byte
snapshots of every derived object. For example, page 116 asserts two figures
and their source regions, while page 397 asserts that dash dialogue produces no
`ListNode`. This keeps the goldens sensitive to meaningful regressions without
making harmless internal refactors unnecessarily expensive.

The current fixtures retain their actual extraction provenance: pages 18, 68,
152, 398, 402, and 412 came from prompt 5.1, while pages 116, 378, and 397 came
from prompt 5. All use schema v5 and `gemini-3.6-flash`.

## Milestone 1F-9 - Golden evaluation and regression report

Milestone 1F-9 turns the checked-in golden fixtures into a named evaluation
surface that can be read by a developer or archived by CI. Pytest remains the
hard regression gate, while the report explains *which capability* failed and
reports the token usage of the real extraction runs behind the fixtures.

Run the accepted v5 suite with:

```bash
siftforge ebook evaluate-golden \
  --fixtures tests/fixtures/ebook/golden/v5
```

For a machine-readable CI artifact:

```bash
siftforge ebook evaluate-golden \
  --fixtures tests/fixtures/ebook/golden/v5 \
  --format json \
  --output artifacts/golden-evaluation.json
```

The first report contains 22 named checks across nine real pages. Checks are
grouped into stable quality dimensions such as language, typography, structure,
marker handling, figure reconstruction, and semantic roles. A failed check
returns a focused detail such as an unexpected heading role, verse break,
figure count, or list interpretation rather than only a generic snapshot diff.

Each `case.json` now also stores the provider token usage copied from the real
run manifest. The evaluator aggregates prompt, candidate, thinking, total, and
cached-content token counts. It intentionally does not convert token counts to
currency yet: provider/model prices are external and time-varying, while token
usage is stable provenance suitable for later cost comparison.

The accepted fixture set currently totals:

```text
prompt tokens:     23,177
candidate tokens:  19,379
thinking tokens:   20,036
total tokens:      62,592
```

This establishes the evaluation boundary needed for later A/B work:

```text
real extraction artifact
        ↓
strict golden fixture
        ↓
named quality checks + structural analysis
        ↓
quality report + token usage
        ↓
future provider / prompt / routing comparison
```

The current report is deliberately feature-based rather than claiming OCR
character accuracy. Exact OCR/CER/WER scoring requires a separate trusted text
reference corpus; it should be added only when such ground truth is available.

## Milestone 1G-1 - Multi-page book assembly and figure assets

Milestone 1G-1 is the first provider-free step that consumes persisted v5 page
runs and turns them into a logical multi-page book segment.

```text
page-* extraction runs
        ↓
canonical PageExtraction reload
        ↓
BookStructuralAnalyzer
        ↓
BookDocument
        ↓
figure region materialization
        ↓
structure/book.json + derived assets
```

Existing page runs can be assembled without calling Gemini again:

```bash
siftforge ebook assemble-book \
  --runs-root runs/18-nam-kim-cuong \
  --output runs/18-nam-kim-cuong-book
```

The assembler discovers direct child page-run directories, validates their
normalized v5 evidence and deterministic IDs, orders them by physical PDF page
number, and writes:

```text
runs/18-nam-kim-cuong-book/
├── manifest.json
├── structure/
│   ├── book.json
│   └── analysis.json
└── assets/
    └── figures/
        └── figure-<stable-hash>.png
```

Figure crops use normalized image regions from page evidence. Derived figures
are written as PNG so cropping does not add another lossy JPEG generation. The
logical `ImageNode.asset_id` points to the resulting relative asset path.

Cross-page structural inference now requires **known consecutive physical PDF
pages**. A sparse test set such as pages 10 and 12 will not accidentally create
continuations or one cross-page list merely because those runs happen to be
adjacent in a directory listing.

Physical pages remain provenance. The assembled `BookDocument` is the first
artifact intended to become input to semantic cleanup and EPUB rendering.

## Milestone 1G-2 - EPUB-ready semantic projection and XHTML skeleton

Milestone 1G-2 introduces the boundary between logical book structure and
renderable EPUB semantics. The renderer no longer consumes page evidence or
source typography directly:

```text
BookDocument
        ↓
EbookSemanticProjector
        ↓
SemanticBookDocument
        ↓
EpubReadyXhtmlRenderer
        ↓
semantic/document.json
text/content.xhtml
styles/book.css
assets/figures/*
```

An existing 1G-1 assembly can be rendered without Gemini or any other provider:

```bash
siftforge ebook render-xhtml \
  --assembly runs/18-nam-kim-cuong-book \
  --output runs/18-nam-kim-cuong-xhtml \
  --title "18 Năm Kim Cương" \
  --language vi
```

The output is intentionally **EPUB-ready XHTML**, not a `.epub` archive yet:

```text
runs/18-nam-kim-cuong-xhtml/
├── manifest.json
├── semantic/
│   └── document.json
├── text/
│   └── content.xhtml
├── styles/
│   └── book.css
└── assets/
    └── figures/
        └── figure-*.png
```

The semantic projector keeps source appearance separate from semantic markup.
Italic source glyphs are preserved as a non-semantic presentation hint and
rendered with `.source-italic { font-style: italic; }`; they do **not** become
`<em>`. Likewise, semantic `<em>`/`<strong>` markup is emitted only when a prior
semantic pass explicitly populated `SemanticMark`. This preserves the conclusion
from real pages 162 and 348: visual source typography and semantic emphasis are
separate concepts while still retaining visible italics in the final EPUB.

Inline XHTML is deliberately kept TTS-friendly. Runs whose language matches the
document inherit `lang`/`xml:lang` from the XHTML root instead of being wrapped
in redundant per-run spans. A source-italic run therefore renders as a single
`<span class="source-italic">…</span>` inside its paragraph; an explicit language
span is emitted only for a real language change. Provider Markdown delimiters
such as `**…**` are also removed when the same whole run already carries
structural styling, so those markers cannot leak into readable EPUB text.

The projection currently maps explicit logical structure into XHTML-safe
semantics:

- paragraphs become `<p>`;
- resolved headings become `<h1>` through `<h6>`;
- labels such as `scenario_label`, `subtitle`, and `genre_label` remain
  non-hierarchical paragraph-like labels;
- ordered lists preserve structural ordinals, including `start="10"`, without
  putting source marker text into readable content;
- verse retains explicit semantic line elements;
- quotations become `<blockquote>`;
- figures use the materialized 1G-1 assets with `<figure>` and `<figcaption>`;
- inset content becomes `<aside>` with a role-specific class;
- footnote relationships become `epub:type="noteref"` links and footnote
  bodies use `epub:type="footnote"`;
- attribution and translation relationships remain in semantic JSON for later
  packaging/navigation logic rather than being invented as non-standard EPUB
  behavior.

`structure/book.json` now has a canonical loader as well as a serializer, so a
persisted assembly can be reused by later stages without repeating structural
analysis. The loader preserves source provenance, semantic relationships,
figure regions, materialized asset IDs, and explicit semantic marks.

The XHTML stage copies only referenced assets and rejects absolute paths or
path traversal. It also leaves unresolved `CONTINUES_TO` relationships as
warnings rather than silently merging content during rendering. Continuation
resolution remains a structural/semantic responsibility, not renderer magic.

This milestone deliberately does not yet create `mimetype`, `META-INF`, OPF,
navigation documents, or the final ZIP container. Those packaging concerns are
reserved for the next EPUB milestone after the semantic XHTML surface is
stable.

## Milestone 1G-3 - Final EPUB 3 package builder

Milestone 1G-3 packages the provider-free XHTML artifacts from 1G-2 into an
actual `.epub` archive.

```text
EPUB-ready XHTML directory
        ↓
EpubPackageBuilder
        ↓
mimetype
META-INF/container.xml
EPUB/package.opf
EPUB/nav.xhtml
EPUB/text/content.xhtml
EPUB/styles/book.css
EPUB/assets/*
        ↓
validated .epub ZIP container
```

Package an existing 1G-2 output with:

```bash
siftforge ebook package-epub \
  --epub-ready runs/18-nam-kim-cuong-xhtml \
  --output dist/18-nam-kim-cuong.epub
```

Optional publication metadata can be pinned for reproducible builds:

```bash
siftforge ebook package-epub \
  --epub-ready runs/18-nam-kim-cuong-xhtml \
  --output dist/18-nam-kim-cuong.epub \
  --identifier urn:isbn:9780000000000 \
  --modified 2026-09-11T10:45:00Z
```

When no identifier is supplied, SiftForge derives a stable UUID URN from the
publication metadata plus rendered content, stylesheet, and referenced assets.
The EPUB 3 `dcterms:modified` timestamp defaults to current UTC time; supplying
`--modified` makes the package byte-reproducible for identical inputs.

The builder follows the EPUB ZIP constraints that are easy to violate when
creating archives manually:

- `mimetype` is the first ZIP member;
- `mimetype` is stored **uncompressed** and contains exactly
  `application/epub+zip`;
- `META-INF/container.xml` points to `EPUB/package.opf`;
- the OPF contains EPUB 3 metadata, a navigation item, manifest, and spine;
- semantic headings from `semantic/document.json` become navigation links;
- books without resolved headings receive a title-level fallback TOC entry;
- CSS, XHTML, and referenced figure assets are copied into the OPF manifest
  with explicit media types;
- all persisted paths are checked for traversal and overlapping package paths.

Before publishing the destination file, SiftForge reopens the generated
archive and performs internal structural checks. It verifies the ZIP mimetype
rules, parses the container, OPF, navigation XHTML, and content XHTML, confirms
that every OPF manifest item exists, and verifies that navigation fragments
point to real content IDs.

This validation is intentionally **not a replacement for EPUBCheck**. It catches
SiftForge packaging defects early and keeps unit tests provider-free. A later
milestone will add EPUBCheck as an external standards-validation gate before a
book is considered distribution-ready.

## Milestone 1G-4 - EPUBCheck standards-validation gate

Milestone 1G-4 keeps standards validation as a distinct stage after deterministic
EPUB packaging:

```text
EPUB-ready XHTML
        ↓
SiftForge EPUB package builder
        ↓
internal structural checks
        ↓
final .epub
        ↓
official EPUBCheck JAR
        ↓
PASS / FAIL + captured JSON report
```

SiftForge deliberately does **not** bundle or auto-download EPUBCheck. Point the
validator at an EPUBCheck JAR that you install separately, either explicitly or
through `EPUBCHECK_JAR`:

```bash
export EPUBCHECK_JAR=/opt/epubcheck/epubcheck.jar

siftforge ebook validate-epub \
  --epub dist/18-nam-kim-cuong.epub \
  --report artifacts/18-nam-kim-cuong.epubcheck.json
```

On PowerShell the environment variable can be configured with:

```powershell
$env:EPUBCHECK_JAR = 'C:\tools\epubcheck\epubcheck.jar'
```

An explicit path is also supported:

```bash
siftforge ebook validate-epub \
  --epub dist/18-nam-kim-cuong.epub \
  --epubcheck-jar tools/epubcheck.jar
```

The validator invokes the external tool as:

```text
java -jar <epubcheck.jar> <book.epub>
```

`--java-command` can select another Java executable and `--timeout` controls the
maximum validation duration. SiftForge captures EPUBCheck stdout/stderr without
trying to reinterpret or rewrite its diagnostics. The optional JSON report also
records the EPUB SHA-256 and EPUBCheck JAR SHA-256 so a CI result is traceable to
both exact inputs.

CLI exit codes distinguish validation from infrastructure failures:

- `0`: EPUBCheck passed;
- `1`: EPUBCheck ran successfully but reported the EPUB as invalid;
- `2`: configuration or execution failed, such as a missing JAR, missing Java,
  or a timeout.

This keeps the architectural boundary explicit: the package builder owns EPUB
construction and cheap deterministic sanity checks; EPUBCheck remains the
external standards authority used as the distribution gate.

## Milestone 1G-4r1 - Footnote and navigation cleanup

Reader validation exposed two presentation bugs without changing the underlying
EPUB semantics. Footnote bodies could repeat their visible label because the
source label was preserved both as `FootnoteNode.label` and as the first body
span. Semantic projection now removes that duplicated marker from body content
while retaining the structural label exactly once for XHTML rendering.

Navigation labels now omit `footnote_ref` inline content. The body heading keeps
its clickable superscript reference, but `nav.xhtml` contains only the readable
heading text. When a removed reference separated two adjacent heading fragments,
the packager inserts a conservative word boundary so TOC labels do not collapse
into strings such as `...13Cá chép...`.

## Milestone 1G-4r2 - Page-13 title/footnote boundary refinement

Reader validation exposed a page-local extraction ambiguity on the preface opener:
two distinct centered subtitle-like lines, each carrying its own superscript footnote
reference, could be merged into one heading. Prompt revision **5.2** keeps those lines
as separate blocks and explicitly preserves superscript footnote-reference spans even
inside short title-like text.

The EPUB navigation policy also excludes supporting `chapter_label`, `subtitle`, and
`genre_label` headings from standalone TOC entries. They remain visible in the reading
flow; hierarchical headings and scenario labels/titles remain navigable.

Existing prompt revisions 5 and 5.1 remain versioned for reproducibility. Schema v5 is
unchanged.

## Milestone 1G-4r3 - Reader-stable subtitle and noteref rendering

KOReader validation confirmed that page-13 extraction, structural analysis, and
footnote relationships were already correct, but adjacent subtitle-like labels
could still appear visually collapsed in the reading view. The XHTML renderer
now emits non-hierarchical heading labels as explicit block `div` elements and
ships a `display: block` rule so reader styles cannot accidentally flow adjacent
labels inline.

Footnote references keep `epub:type="noteref"` on the clickable anchor, while a
`sup.noteref` wrapper and conservative CSS make the visible marker reliably
superscript without changing the semantic link target. This applies equally to
subtitle labels and normal headings such as the page-118 footnote case.

No extraction prompt, page-evidence schema, structural rule, or semantic model
changed in this revision; it is intentionally a renderer-only refinement based
on real reader behavior.

## Milestone 1G-5 - End-to-end EPUB build orchestration

Milestone 1G-5 adds a single provider-free command that composes the existing
book assembly, semantic XHTML, EPUB packaging, and optional EPUBCheck stages
without collapsing their internal boundaries.

The normal local workflow is now:

```bash
siftforge ebook build-epub \
  --runs-root runs/18-nam-kim-cuong \
  --output dist/18-nam-kim-cuong.epub \
  --title "18 Năm Kim Cương" \
  --language vi
```

The command consumes existing `page-*` extraction runs. It does **not** call
Gemini again. The individual stage commands remain available for debugging and
inspection:

```text
page-* runs
   ↓ assemble-book
BookDocument
   ↓ render-xhtml
semantic XHTML/CSS/assets
   ↓ package-epub
final EPUB
   ↓ optional validate-epub
EPUBCheck result
```

`build-epub` deliberately rebuilds the derived assembly and EPUB-ready stages
from scratch every time. This is the first freshness policy: correctness is
preferred over incremental caching, so a newly extracted page cannot be hidden
behind stale `BookDocument` or XHTML artifacts. The source page runs are never
removed.

By default the derived workspace is a sibling of the runs root:

```text
runs/
├── 18-nam-kim-cuong/
│   └── page-*/
└── 18-nam-kim-cuong-build/
    ├── assembly/
    ├── epub-ready/
    └── build-manifest.json
```

A custom workspace can be selected with `--work-dir`.

Printed front matter or other unwanted physical pages can be omitted at build
time without deleting source evidence:

```bash
siftforge ebook build-epub \
  --runs-root runs/18-nam-kim-cuong \
  --exclude-pages 7-10,14 \
  --output dist/18-nam-kim-cuong.epub
```

`--exclude-pages` accepts comma-separated one-based PDF page numbers and
inclusive ranges. The exclusion is recorded in both
`assembly/manifest.json` and `build-manifest.json`. When `--require-reviewed`
is also enabled, excluded pages do not participate in the strict review gate,
because they are not part of the final EPUB.

EPUBCheck remains optional and external. To include it in the same command:

```bash
siftforge ebook build-epub \
  --runs-root runs/18-nam-kim-cuong \
  --output dist/18-nam-kim-cuong.epub \
  --title "18 Năm Kim Cương" \
  --language vi \
  --validate \
  --epubcheck-jar /path/to/epubcheck.jar
```

When `--validate` is used without `--epubcheck-jar`, the command falls back to
`EPUBCHECK_JAR`. The default validation report is written beneath the build
workspace at `reports/epubcheck.json`.

The orchestration exit status preserves the stage distinction:

```text
0  EPUB built successfully; EPUBCheck also passed when requested
1  EPUB was built, but EPUBCheck reported standards errors
2  configuration or pipeline execution failed
```

`build-manifest.json` records the page/node/figure counts, EPUB metadata, TOC
count, validation status, and the `clean-derived-stages` policy so a complete
build remains inspectable even though the user only needs one CLI command.

## Milestone 1G-6 - Resumable whole-book page extraction

Milestone 1G-6 closes the gap between one-page smoke tests and a real full-book
run. The new command extracts an inclusive PDF page range into the same canonical
`page-NNNN` artifacts already consumed by `build-epub`:

```bash
siftforge ebook extract-book \
  --pdf 18-nam-kim-cuong.pdf \
  --model gemini-3.6-flash
```

By default the output root is `runs/<pdf-stem>`. A custom root and a smaller
range can be selected explicitly:

```bash
siftforge ebook extract-book \
  --pdf 18-nam-kim-cuong.pdf \
  --model gemini-3.6-flash \
  --runs-root runs/18-nam-kim-cuong \
  --start-page 1 \
  --end-page 20
```

The runner is **resumable by default**. Before making a provider call it validates
an existing page run against:

- source page identity and source-page hash;
- source PDF SHA-256;
- active prompt name/version (`ebook_page_evidence` 5.2);
- schema name/version (v5);
- requested model identity;
- canonical normalized evidence and referenced source asset.

Only an exact match is reused. Incomplete, corrupt, stale-prompt, changed-PDF, or
changed-model page directories are rebuilt from scratch. Fresh extraction is written
to a sibling staging directory and published only after the complete page run succeeds,
so a failed refresh does not destroy the previous canonical run. `--force` disables
reuse for the selected range.

The command checkpoints progress atomically after every page in:

```text
runs/<pdf-stem>/book-extraction.json
```

If page 200 fails after pages 1-199 completed, the default behavior is to stop.
Rerunning the same command reuses pages 1-199 and resumes at page 200. This keeps
provider cost bounded without introducing a cache database or hiding source
artifacts behind opaque state.

For diagnostic batches, `--continue-on-error` records a failed page and continues
with later pages. The command exits non-zero when failed pages remain.

Each progress line reports whether a page was freshly extracted, reused, or failed:

```text
[18/432] page 0018 reused
[19/432] page 0019 extracted
```

The root checkpoint also aggregates numeric provider usage counters from the
canonical page manifests so token usage remains inspectable across resumed runs.

The multi-page runner reuses one `PDFSource` discovery pass and one
`PDFPageMaterializer`/`PdfReader` across the selected range; it does not repeatedly
rescan the PDF for every page.

Once extraction is complete, the existing provider-free build remains unchanged:

```bash
siftforge ebook build-epub \
  --runs-root runs/18-nam-kim-cuong \
  --output dist/18-nam-kim-cuong.epub \
  --title "18 Năm Kim Cương" \
  --language vi
```

This keeps the layer boundary intact: `extract-book` owns expensive page evidence,
while `build-epub` owns deterministic book assembly, semantic projection, XHTML,
EPUB packaging, and optional EPUBCheck validation.

## Milestone 1G-7 - One-command complete PDF-to-EPUB conversion

Milestone 1G-7 composes the resumable provider stage from 1G-6 with the
provider-free EPUB build from 1G-5 while preserving their internal boundaries.
The normal full-book workflow can now be invoked as one command:

```bash
siftforge ebook convert-pdf \
  --pdf 18-nam-kim-cuong.pdf \
  --model gemini-3.6-flash \
  --output dist/18-nam-kim-cuong.epub \
  --title "18 Năm Kim Cương" \
  --language vi
```

The command is orchestration only. Internally the same isolated services still
run in order:

```text
scanned PDF
   ↓ resumable extract-book
canonical page-* evidence runs
   ↓ build-epub
BookDocument → semantic XHTML → EPUB package
   ↓ optional EPUBCheck
final validation result
```

Existing page runs are reused only when 1G-6 confirms that the physical source
page, source PDF hash, active prompt/schema revision, and requested model all
match. Missing or stale pages are extracted before any provider-free book build
begins.

Unlike `build-epub`, `convert-pdf` always selects the **complete physical PDF**.
This is an intentional full-book readiness gate: the command does not silently
package a sparse test set as though it were the finished book. Page-range smoke
tests remain available through `extract-book` followed by `build-epub`.

If `--continue-on-error` is enabled, SiftForge can finish attempting later
pages, but a final EPUB is **not** built while any selected physical page still
has failed extraction:

```text
page 1      successful
page 2      failed
page 3..N   attempted
       ↓
conversion status = incomplete
EPUB build          = skipped
```

Rerunning the same command resumes from the canonical page runs, so repaired
provider/network failures do not require paying for already-valid pages again.
`--force-extract` is available when the user intentionally wants every page to
be refreshed.

The default artifact layout remains transparent:

```text
runs/
├── 18-nam-kim-cuong/
│   ├── page-0001/
│   ├── page-0002/
│   ├── ...
│   └── book-extraction.json
└── 18-nam-kim-cuong-build/
    ├── assembly/
    ├── epub-ready/
    ├── build-manifest.json
    └── conversion-manifest.json

dist/
└── 18-nam-kim-cuong.epub
```

`conversion-manifest.json` records the extraction summary, aggregate provider
usage, whether the build was attempted, the final EPUB path, and optional
EPUBCheck status. This gives the one-command UX without hiding or merging the
underlying pipeline stages.

EPUBCheck can be included in the same invocation when configured:

```bash
siftforge ebook convert-pdf \
  --pdf 18-nam-kim-cuong.pdf \
  --model gemini-3.6-flash \
  --output dist/18-nam-kim-cuong.epub \
  --title "18 Năm Kim Cương" \
  --language vi \
  --validate \
  --epubcheck-jar /path/to/epubcheck.jar
```

Exit status preserves the same distinction as the lower-level commands:

- `0`: every page is ready and the EPUB was built; EPUBCheck also passed when
  requested;
- `1`: extraction completed with failed pages and packaging was skipped, or the
  EPUB was built but EPUBCheck reported standards errors;
- `2`: configuration/infrastructure/pipeline execution failed.

## Milestone 1H-1 - Free-first Gemini routing

SiftForge can now keep the existing Gemini page-extraction contract while routing
credential profiles by cost. The ebook domain still submits the same image,
prompt 5.2, and schema v5; routing is a generic extraction-runtime concern.

Configure a free Gemini profile separately from an optional paid fallback:

```bash
export SIFTFORGE_GEMINI_FREE_API_KEY="..."
export SIFTFORGE_GEMINI_PAID_API_KEY="..."  # optional
```

The safe default is `free-only`:

```bash
siftforge ebook extract-book \
  --pdf 18-nam-kim-cuong.pdf \
  --model gemini-3.6-flash \
  --runs-root runs/18-nam-kim-cuong
```

A configured paid key is never used in this mode. When finishing immediately is
more important than waiting for free capacity to return, paid fallback must be
explicitly enabled:

```bash
siftforge ebook extract-book \
  --pdf 18-nam-kim-cuong.pdf \
  --model gemini-3.6-flash \
  --runs-root runs/18-nam-kim-cuong \
  --routing-policy free-then-paid
```

The current free profile receives up to three calls for retryable failures before
routing moves on. Transient server failures, short-term rate limits, malformed
structured JSON, daily quota exhaustion, authentication/permission failures, and
invalid requests are classified separately. Paid routing is skipped for failures
that another credential cannot repair, such as a task-level invalid request.

Successful page manifests preserve the complete attempt chain, including failed
free attempts before a successful fallback. Failed whole-book pages also retain
safe attempt provenance in `book-extraction.json`; API keys are never persisted.
The book checkpoint includes a fresh-run routing summary grouped by profile and
failure reason.

Existing `GEMINI_API_KEY` / `GOOGLE_API_KEY` usage remains supported as a legacy
single-profile path. Multiple alternative free models are intentionally not
activated yet: each candidate model should first pass the existing golden ebook
regression set before it can join the free route pool.

Run-level failures such as exhausted daily free quota, invalid credentials,
permission errors, or invalid requests stop whole-book extraction even when
`--continue-on-error` is set. This prevents a known bad credential/quota state
from causing hundreds of pointless page requests; the checkpoint remains safe to
resume later with the same command.

### RECITATION recovery with local OCR

Gemini can occasionally return an empty structured response with
`finish_reason=RECITATION` when exact transcription resembles memorized or
otherwise protected text. SiftForge treats this as a terminal Gemini generation
reason: it does not retry the same Gemini route or spend another paid attempt on
the same page.

For active v5 page extraction, the default recovery path uses local Tesseract OCR
to keep the book complete. The recovered canonical page is explicitly marked as
review-required in both `normalized/page.json` warnings and `manifest.json`:

```text
normalization.status   = recovered
normalization.recovery = local_ocr_recitation
normalization.needs_review = true
```

The raw OCR text is stored as `raw/local-ocr.txt`. Typography and fine semantic
structure are intentionally conservative because local OCR is an emergency text
recovery mechanism, not a replacement for Gemini page evidence. Human proofing
should verify every recovered page against its source image.

By default, `--recitation-ocr-language auto` prefers the dominant language of the
nearest already-extracted sibling page and maps common ISO codes such as `vi` to
Tesseract's `vie`. An explicit language can be supplied when needed:

```bash
siftforge ebook extract-page \
  --pdf 18-nam-kim-cuong.pdf \
  --page 32 \
  --model gemini-3.6-flash \
  --routing-policy free-then-paid \
  --recitation-ocr-language vie
```

Use `--no-recitation-ocr-fallback` when a workflow must fail instead of creating
a local-OCR recovery artifact. Whole-book progress and summaries report recovered
pages separately from failed pages. Recovered canonical runs are reusable on the
next resume; use `--force` when intentionally retrying them with Gemini.

## Milestone 1G-8 - EPUB reader compatibility hardening

The EPUB renderer now writes multiple XHTML spine documents instead of forcing
an entire book into one `text/content.xhtml`. Top-level navigable headings start
new deterministic `text/section-NNNN.xhtml` documents. A single-document book
still uses `text/content.xhtml` for backwards compatibility.

The EPUB-ready manifest keeps the legacy `content` field and adds ordered
`contents` so packaging can build a real multi-item spine:

```json
{
  "content": "text/section-0001.xhtml",
  "contents": [
    "text/section-0001.xhtml",
    "text/section-0002.xhtml"
  ]
}
```

Navigation targets are resolved against the XHTML document that actually owns
the heading ID, and every rendered content document is included in OPF spine
order. Internal package validation now checks navigation links, footnote links,
and footnote return links across XHTML files.

Footnote references now always use an explicit XHTML filename even when the
footnote lives in the same file:

```html
<a id="ref-1" epub:type="noteref" href="section-0001.xhtml#note-1">1</a>
```

Footnote bodies are emitted as `aside epub:type="footnote"` with their text in a
paragraph and with explicit backlinks:

```html
<aside id="note-1" class="footnote" epub:type="footnote">
  <p>... <a class="footnote-backlink"
     href="section-0001.xhtml#ref-1">↩</a></p>
</aside>
```

This change is entirely downstream of extraction. Existing page runs do not
need to be re-extracted; rerunning `build-epub` is enough to rebuild assembly,
semantic XHTML, navigation, and the final EPUB with the compatibility changes.

## Milestone 1G-9 - Semantic EPUB projection

The EPUB output layer now follows more conventional reflowable-book semantics
without changing Gemini extraction, page evidence, or `BookDocument`.

Logical titles produce semantic filenames when enough structure is known:

```text
text/
├── chapter-0001.xhtml
├── chapter-0002.xhtml
├── section-0001.xhtml
└── endnotes.xhtml
```

Unknown or unclassified chunks still use deterministic `section-NNNN.xhtml`
filenames, and simple books without a resolved title boundary may continue to use
`content.xhtml`.

A title with adjacent supporting labels/subtitles is rendered as one HTML
`hgroup`. Supporting headings remain separate block elements and retain any
clickable noteref markup. Verse now uses a `blockquote` with explicit `<br />`
line boundaries instead of relying on visual block layout.

Source-domain `FootnoteNode` values remain footnotes in the semantic model, but
the EPUB projection writes them to a dedicated `text/endnotes.xhtml`. Body
references point directly to the corresponding endnote:

```html
<a id="ref-1" epub:type="noteref" href="endnotes.xhtml#note-1">1</a>
```

The endnote has an explicit semantic backlink:

```html
<li id="note-1" epub:type="endnote">
  <p>... <a epub:type="backlink"
     href="chapter-0001.xhtml#ref-1">↩</a></p>
</li>
```

This keeps source semantics separate from EPUB representation while avoiding a
dependency on reader-specific Back-history behavior.

The EPUB navigation document now contains both the normal TOC and a landmarks
navigation section. Landmarks identify the start of body matter and the endnotes
section when present. The EPUB-ready manifest records the dedicated endnotes
path, and packaging validates that it is also part of the ordered spine.

These changes are downstream only. Existing page extraction runs can be reused;
rerun `build-epub` to regenerate assembly-derived XHTML and the final EPUB.

## Milestone 1I-1 - Text fidelity review

Page extraction remains unchanged: Gemini still reads the original page image and
produces prompt 5.2 / schema v5 evidence. This milestone adds an independent,
provider-free review stage after extraction instead of changing that proven path.

```text
normalized PageExtraction
        ├── review projection with block/span provenance
        └── original page image → local Tesseract OCR
                         ↓
                    text aligner
                         +
              conservative heuristics
                         ↓
                  review findings
```

Run review over existing canonical page runs:

```bash
siftforge ebook review-text \
  --runs-root runs/18-nam-kim-cuong \
  --ocr-language vie+eng
```

The default local engine is the `tesseract` executable. No new Python OCR package
is required, but Tesseract and the requested language data must be installed on
the machine. A page range can be inspected first with `--start-page` and
`--end-page`.

Long review runs print live per-page progress to stderr, including the current
page, whether OCR was processed or reused from cache, finding count, similarity,
throughput, and ETA. Use `--quiet` when progress output is not wanted.

The structured Gemini text is flattened only into a temporary comparison
projection. Character provenance still maps findings back to normalized
`block_id` and `span_id`; `normalized/page.json` is never rewritten by review.
Each page receives additive artifacts:

```text
page-NNNN/
└── review/
    ├── ocr.json
    └── findings.json
```

The whole run also receives:

```text
review/
├── summary.json
├── report.html
└── crops/
```

`report.html` highlights the smallest localized Gemini/OCR disagreement and shows
an image crop when OCR coordinates can locate the source evidence. Findings from
simple suspicious-boundary heuristics are shown before noisy OCR differences.
The heuristics only flag candidates; they never silently repair text.

This matters when both readers reproduce the same source typography. For
example, if the scanned page itself contains `ngày14`, both Gemini and Tesseract
may agree on `ngày14`. The independent heuristic still flags the letter→digit
boundary as a review candidate and can show the source crop. The same applies to
patterns such as `nhi.Tuy`, where a lower-case word and an upper-case sentence
start are glued across a period.

Human resolution/correction overlays are intentionally deferred to the next
review milestone. 1I-1 is evidence generation only: original Gemini output,
normalized evidence, local OCR, and review findings remain independently
inspectable.

## Milestone 1I-2 - Review noise reduction

The review stage now treats local OCR as an independent signal rather than a
second ground truth. Character-level diffs are first coalesced into short phrase
findings, then OCR-only candidates are filtered using the supporting Tesseract
word confidence and the Gemini block role.

By default, low-confidence heading noise, short one- or two-character OCR noise,
punctuation noise, and the common case where local OCR merely drops Vietnamese
diacritics are hidden from the HTML report. They are not deleted: every
suppressed candidate remains in `findings.json` and `summary.json` with a
`suppressed_reason` for audit.

Running furniture (`page_header`, `page_footer`, and `page_number`) plus image
placeholders are excluded from the temporary review projection. This does not
change normalized extraction or ebook structure; it only prevents irrelevant
OCR differences from consuming review attention.

The default command remains:

```bash
siftforge ebook review-text \
  --runs-root runs/18-nam-kim-cuong \
  --ocr-language vie+eng
```

The default actionable OCR threshold is 85%, with a stricter 92% threshold for
heading-like blocks. Both can be tuned with
`--review-min-ocr-confidence` and `--review-heading-min-ocr-confidence`.
Use `--show-all-ocr-differences` when the unfiltered OCR comparison is desired.

On the real page 13 + page 152 probe used while developing this milestone, the
v1 report exposed 47 findings. The v2 projection/coalescing/filtering pipeline
reduces that to two actionable findings: the source anomalies `ngày14` and
`nhi.Tuy`. Twenty-one OCR candidates remain preserved as suppressed audit data.

## Milestone 1I-3 - Review resolution overlay

The HTML text-review report now supports explicit human decisions for every
actionable finding: **Keep source**, **Use OCR**, **Use suggestion**, or a
**Manual** replacement. The report is still a standalone local HTML file. It
stores in-progress choices in browser-local state when available and exports a
small `siftforge-review-resolutions.json` file; it never writes into normalized
page evidence directly.

Import the exported decisions with:

```bash
siftforge ebook import-review \
  --runs-root runs/18-nam-kim-cuong \
  --resolutions ~/Downloads/siftforge-review-resolutions.json
```

The import step validates every finding against the current review artifacts and
against the current normalized projected text. It then writes additive,
page-local review artifacts:

```text
page-NNNN/
└── review/
    ├── ocr.json
    ├── findings.json
    ├── resolutions.json
    └── corrections.json
```

`normalized/page.json` remains immutable. `corrections.json` contains only
approved text edits, each targeting one deterministic `span_id` plus an exact
source offset and original-text snapshot. If a page is re-extracted later and
the old correction no longer matches the source span, book assembly fails
instead of silently applying a stale edit.

`assemble-book`, `build-epub`, and therefore `convert-pdf` automatically apply
valid `review/corrections.json` overlays before book-level structural analysis.
A `Keep source` decision is still persisted as review provenance but produces no
text edit.

Importing a resolution file replaces the previous imported decision set. This
keeps the whole-run `review/resolutions.json` consistent with the page-local
correction overlays that a later EPUB build will actually consume.

## Milestone 1I-4: review completeness and strict build gate

Text-fidelity review can now be audited before packaging:

```bash
siftforge ebook review-status --runs-root runs/18-nam-kim-cuong
```

The command classifies every canonical page as `not_reviewed`, `pass`,
`needs_review`, `resolved`, or `stale`. A stale review is detected when a page
was re-extracted and the saved finding snapshot no longer matches normalized
text.

For release-quality builds, opt into the strict gate:

```bash
siftforge ebook build-epub \
  --runs-root runs/18-nam-kim-cuong \
  --output dist/18-nam-kim-cuong.epub \
  --title "18 Năm Kim Cương" \
  --language vi \
  --require-reviewed
```

Without `--require-reviewed`, existing behavior is unchanged: reviewed
correction overlays are applied when present, while incomplete review remains a
warning/workflow concern rather than a hard build dependency.

## Milestone 1I-5: incremental/resumable text review

Whole-book text review now reuses compatible page-local OCR/review artifacts instead
of running Tesseract again on every invocation. This is especially important for
large 400-700 page books where extraction may be resumed or review policy may be
iterated several times.

The normal command remains unchanged:

```bash
siftforge ebook review-text \
  --runs-root runs/18-nam-kim-cuong \
  --ocr-language vie+eng
```

For every selected page, SiftForge fingerprints the normalized page artifact, the
source image bytes, local-OCR configuration, review-filter configuration, review
model version, and report output location. A matching fingerprint means the saved
`ocr.json` and `findings.json` can be reloaded directly and included in a freshly
regenerated aggregate `summary.json` / `report.html` without invoking OCR again.

The command now reports both kinds of work:

```text
pages:     432
processed: 17
reused:    415
flagged:   23
...
```

Use `--force` when local OCR should be run again deliberately:

```bash
siftforge ebook review-text \
  --runs-root runs/18-nam-kim-cuong \
  --ocr-language vie+eng \
  --force
```

A page is automatically recomputed when any review input changes, including the
normalized extraction, source image, OCR language/PSM/minimum confidence, or review
noise thresholds. Old review artifacts without the 1I-5 fingerprint are refreshed
once and then become reusable.

Each review run also writes `review/run.json` with the selected range, processed and
reused page counts, OCR cache key, filter policy, and review-model version. Existing
human `resolutions.json` / `corrections.json` remain separate from this mechanical
OCR cache and continue to be protected by the review-status and correction drift
checks.

## Book metadata and cover packaging

SiftForge can keep book-level bibliographic metadata beside the canonical page
runs instead of repeating it on every build. Put a UTF-8 `metadata.json` in the
runs root:

```text
runs/18-nam-kim-cuong/
├── metadata.json
├── cover.jpg
├── page-0001/
├── page-0002/
└── ...
```

A ready-to-copy template is included as `metadata.example.json`. A complete
metadata file can contain:

```json
{
  "title": "18 Năm Kim Cương",
  "subtitle": null,
  "language": "vi",
  "authors": ["Tên tác giả"],
  "publisher": "Tên nhà xuất bản",
  "publication_date": "2026-09-18",
  "isbn": "9780000000000",
  "description": "Mô tả ngắn về sách.",
  "subjects": ["Kỹ năng sống", "Giáo dục"],
  "rights": "© Chủ sở hữu bản quyền",
  "series": null,
  "series_index": null,
  "contributors": [],
  "cover": "cover.jpg"
}
```

`cover` is resolved relative to `metadata.json`. JPEG, PNG, GIF, and SVG cover
images are supported. `build-epub` automatically discovers
`<runs-root>/metadata.json`, so the normal provider-free build can become:

```bash
siftforge ebook build-epub \
  --runs-root runs/18-nam-kim-cuong \
  --output dist/18-nam-kim-cuong.epub
```

Use `--metadata` when the JSON lives elsewhere, or `--cover` to override only
the cover image. Existing `--title`, `--language`, and `--author` flags remain
supported and take precedence over the corresponding persisted metadata.

The EPUB-ready stage persists normalized metadata, copies the cover into the
self-contained build artifacts, and creates `text/cover.xhtml`. The final EPUB
package writes standard Dublin Core/EPUB 3 metadata for title, subtitle,
authors, contributors, language, publisher, publication date, ISBN,
description, subjects, rights, and series information. The cover image is
marked with the EPUB 3 `cover-image` manifest property and the cover is added to
both the spine and landmarks navigation.

This is deliberately a book-level layer. Page OCR/extraction artifacts remain
unchanged, so correcting metadata or replacing a cover only requires rerunning
the provider-free EPUB build; no Gemini extraction is needed.

### Suggest book metadata and extract the cover from PDF front matter

SiftForge can ask Gemini to inspect a small front-matter page range, write a
reviewable `metadata.json`, and automatically persist the detected front cover.
The command does not package the EPUB automatically; review or edit the generated
metadata first.

```bash
siftforge ebook extract-metadata \
  --pdf 18-nam-kim-cuong.pdf \
  --model gemini-3.6-flash
```

By default SiftForge inspects physical PDF pages 1-8 and writes:

```text
runs/18-nam-kim-cuong/metadata.json
runs/18-nam-kim-cuong/metadata-extraction.json
runs/18-nam-kim-cuong/cover.jpg    # when a cover is confidently detected
```

When Gemini identifies a confident `cover_page_number`, SiftForge uses the already
materialized source page to create `cover.jpg` and writes `"cover": "cover.jpg"`
into `metadata.json`. Embedded JPEG cover bytes are copied directly so no image
quality is lost; other materialized image encodings are converted to JPEG only when
needed.

If no cover can be identified confidently, metadata extraction still succeeds and
leaves `cover` unset. `metadata.json` contains only package-ready bibliographic
fields. The diagnostic `metadata-extraction.json` keeps the selected page numbers,
Gemini attempt provenance, warnings, page-role suggestions, and a `cover_extraction`
record describing whether the cover was extracted, skipped, or failed.

Use a narrower or wider front-matter range when needed:

```bash
siftforge ebook extract-metadata \
  --pdf 18-nam-kim-cuong.pdf \
  --model gemini-3.6-flash \
  --start-page 1 \
  --end-page 12
```

The extractor intentionally leaves unknown values as `null`/empty arrays and is
instructed not to guess from filenames or outside knowledge. Review the generated
`metadata.json` before `build-epub`.

## Human proofreading workspace

Generated `epub-ready/` XHTML remains a derived artifact and is rebuilt by
`build-epub`. Final human proofreading therefore has a separate ownership
boundary. After a normal build, freeze the current EPUB-ready tree once:

```bash
siftforge ebook prepare-proof \
  --epub-ready runs/18-nam-kim-cuong-build/epub-ready \
  --output runs/18-nam-kim-cuong-build/proof
```

The proof workspace is a self-contained, packageable copy:

```text
runs/18-nam-kim-cuong-build/
├── assembly/                 # generated; safe to rebuild
├── epub-ready/               # generated; safe to rebuild
└── proof/                    # human-owned; do not regenerate casually
    ├── proof-manifest.json
    ├── manifest.json
    ├── semantic/
    ├── styles/
    ├── assets/
    └── text/
        ├── cover.xhtml
        ├── chapter-0001.xhtml
        ├── chapter-0002.xhtml
        └── ...
```

Open `proof/text/chapter-XXXX.xhtml` in an editor and make final textual or
presentation corrections there. Preserve XHTML structure, element IDs, links,
and filenames; the proof layer is intended for final proofreading rather than
book-structure redesign. `proof-manifest.json` records SHA-256 baselines for the
editable XHTML files so SiftForge can report how many have changed.

A proof workspace is protected by default. Running `prepare-proof` again against
an existing destination fails instead of erasing human edits. `--force` exists
only as an explicit escape hatch when the user intentionally wants to discard
the current proof and recreate it from generated XHTML.

Once proofreading has started, package directly from proof rather than running
`build-epub` for the final artifact:

```bash
siftforge ebook package-epub \
  --proof runs/18-nam-kim-cuong-build/proof \
  --output dist/18-nam-kim-cuong.epub
```

`package-epub --proof` validates the proof manifest, reports the number of
edited XHTML files, and then uses the same structural EPUB packaging checks as
the generated path. A later `build-epub` may safely regenerate `assembly/` and
`epub-ready/`; it does not touch the sibling `proof/` directory.

To preserve proof history outside the machine-generated run tree, sync it to a
separate Git working directory:

```bash
siftforge ebook backup-book \
  --runs-root runs/18-nam-kim-cuong \
  --proof runs/18-nam-kim-cuong-build/proof \
  --output ~/projects/siftforge-books/18-nam-kim-cuong
```

This command deliberately owns only `proof/`, `metadata.json`,
`review/resolutions.json`, `build-info.json`, and `backup-manifest.json` under the
destination. Existing `.git` state and unrelated user files are left intact.

The intended ownership boundary is therefore:

```text
normalized extraction + corrections
            ↓
      BookDocument
            ↓
 SemanticBookDocument
            ↓
 epub-ready/                 MACHINE-OWNED / REGENERATABLE
            ↓ prepare-proof (once)
 proof/text/*.xhtml          HUMAN-OWNED / FINAL EDITABLE COPY
            ↓ package-epub --proof
 final EPUB                  DISTRIBUTION COPY
```
