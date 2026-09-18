"""Versioned AI contract for front-matter book metadata extraction."""

from __future__ import annotations

from siftforge.extraction.models import ExtractionSchema, PromptSpec


EBOOK_METADATA_PROMPT_V1 = PromptSpec(
    name="ebook_book_metadata",
    version="1",
    text="""Extract bibliographic metadata from the supplied scanned book pages.

The images are selected physical pages from one book, usually front matter such as
cover, title, copyright, publisher, or edition pages. Use ONLY information visibly
supported by these images. Do not use outside knowledge, do not guess missing values,
and do not infer facts from the filename.

Return one structured JSON object matching the supplied schema.

Field rules:
- title: the main publication title, not a chapter title or series label.
- subtitle: only when visibly presented as a subtitle of the publication.
- authors: ordered author names explicitly credited as authors. Do not include
  translators, editors, illustrators, or publishers here.
- language: dominant publication language when confidently supported; prefer a
  lowercase BCP 47 / ISO 639-1 code such as "vi" or "en".
- publisher: publishing house/imprint only when explicitly identified. Do not confuse
  a printer, distributor, website, or copyright holder with the publisher.
- publication_date: publication/edition date only when explicitly printed. Prefer an
  unambiguous ISO-like value (YYYY, YYYY-MM, or YYYY-MM-DD) when the source clearly
  supports it; otherwise preserve a concise printed form.
- isbn: transcribe the ISBN exactly enough to preserve all digits; hyphens may be
  retained. Do not invent an ISBN from another identifier.
- description: only a visibly printed publisher/jacket description or summary. Do not
  summarize the book yourself.
- subjects: only explicit subject/category labels visible in the supplied pages; do
  not infer topical categories from prose.
- rights: a visible copyright/rights statement when present.
- series and series_index: only when an explicit series/collection and position are
  visibly stated.
- contributors: non-author contributor names visibly credited, such as translator,
  editor, illustrator, or compiler. Include a short role prefix when the role is
  printed, for example "Dịch giả: Nguyễn Văn A".

Page-role hints:
- cover_page_number: physical page number of the most likely front cover among the
  supplied images, or null if not confidently identifiable.
- title_page_number: physical page number of the strongest title-page evidence, or
  null.
- copyright_page_number: physical page number containing the strongest copyright /
  publication-detail evidence, or null.

Uncertainty:
- Use null for unknown scalar fields and [] for unknown list fields.
- Add concise warnings for ambiguous/conflicting metadata, unreadable text, or values
  that require human review.
- Never silently resolve conflicts between different editions or repeated title-like
  pages; report the conflict in warnings.
""",
)


_OPTIONAL_STRING_SCHEMA: dict[str, object] = {
    "anyOf": [{"type": "string"}, {"type": "null"}]
}
_OPTIONAL_POSITIVE_INTEGER_SCHEMA: dict[str, object] = {
    "anyOf": [
        {"type": "integer", "minimum": 1},
        {"type": "null"},
    ]
}
_STRING_ARRAY_SCHEMA: dict[str, object] = {
    "type": "array",
    "items": {"type": "string"},
}

EBOOK_METADATA_SCHEMA_V1 = ExtractionSchema(
    name="ebook_book_metadata",
    version="1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "title",
            "subtitle",
            "language",
            "authors",
            "publisher",
            "publication_date",
            "isbn",
            "description",
            "subjects",
            "rights",
            "series",
            "series_index",
            "contributors",
            "cover_page_number",
            "title_page_number",
            "copyright_page_number",
            "warnings",
        ],
        "properties": {
            "title": _OPTIONAL_STRING_SCHEMA,
            "subtitle": _OPTIONAL_STRING_SCHEMA,
            "language": _OPTIONAL_STRING_SCHEMA,
            "authors": _STRING_ARRAY_SCHEMA,
            "publisher": _OPTIONAL_STRING_SCHEMA,
            "publication_date": _OPTIONAL_STRING_SCHEMA,
            "isbn": _OPTIONAL_STRING_SCHEMA,
            "description": _OPTIONAL_STRING_SCHEMA,
            "subjects": _STRING_ARRAY_SCHEMA,
            "rights": _OPTIONAL_STRING_SCHEMA,
            "series": _OPTIONAL_STRING_SCHEMA,
            "series_index": _OPTIONAL_STRING_SCHEMA,
            "contributors": _STRING_ARRAY_SCHEMA,
            "cover_page_number": _OPTIONAL_POSITIVE_INTEGER_SCHEMA,
            "title_page_number": _OPTIONAL_POSITIVE_INTEGER_SCHEMA,
            "copyright_page_number": _OPTIONAL_POSITIVE_INTEGER_SCHEMA,
            "warnings": _STRING_ARRAY_SCHEMA,
        },
    },
)
