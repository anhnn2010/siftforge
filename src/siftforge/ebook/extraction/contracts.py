"""Versioned prompt and schema contracts for faithful ebook page extraction."""

from __future__ import annotations

from siftforge.extraction.models import ExtractionSchema, PromptSpec

EBOOK_PAGE_PROMPT = PromptSpec(
    name="ebook_page_transcription",
    version="1",
    text="""Transcribe this scanned book page faithfully.

Rules:
- Do not summarize, translate, modernize, rewrite, or improve the author's text.
- Preserve Vietnamese diacritics, punctuation, numbers, and meaningful reading order.
- Reconstruct paragraphs semantically; do not preserve arbitrary scan line wrapping.
- Classify visible content into semantic blocks.
- Separate probable running headers, running footers, and printed page numbers instead
  of silently deleting them.
- Record a visible printed page number separately when present.
- If any content is unclear, do not invent missing words. Transcribe only what can be
  supported by the image and add a concise warning describing the uncertainty.
- Decorative artwork without meaningful text does not need invented descriptions.
""",
)

EBOOK_PAGE_SCHEMA = ExtractionSchema(
    name="ebook_page_content",
    version="1",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "page_kind",
            "language",
            "printed_page_number",
            "blocks",
            "warnings",
        ],
        "properties": {
            "page_kind": {
                "type": "string",
                "enum": [
                    "cover",
                    "title",
                    "copyright",
                    "toc",
                    "chapter_title",
                    "text",
                    "illustration",
                    "blank",
                    "other",
                ],
                "description": "Primary semantic role of this scanned page.",
            },
            "language": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "null"},
                ],
                "description": "Main visible language code when confidently known.",
            },
            "printed_page_number": {
                "anyOf": [
                    {"type": "string"},
                    {"type": "null"},
                ],
                "description": "Page number visibly printed on the physical page.",
            },
            "blocks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": ["type", "text", "level"],
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "heading",
                                "paragraph",
                                "quote",
                                "list",
                                "image_caption",
                                "footnote",
                                "table",
                                "page_header",
                                "page_footer",
                                "page_number",
                                "other",
                            ],
                        },
                        "text": {
                            "type": "string",
                            "description": (
                                "Faithful text content in semantic reading order."
                            ),
                        },
                        "level": {
                            "anyOf": [
                                {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 6,
                                },
                                {"type": "null"},
                            ],
                            "description": (
                                "Heading level when applicable; otherwise null."
                            ),
                        },
                    },
                },
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
                "description": (
                    "Uncertainty or visibly unreadable/ambiguous source content."
                ),
            },
        },
    },
)
