"""Versioned prompt and schema contracts for faithful ebook page extraction."""

from __future__ import annotations

from siftforge.extraction.models import ExtractionSchema, PromptSpec

EBOOK_PAGE_PROMPT = PromptSpec(
    name="ebook_page_transcription",
    version="4",
    text="""Transcribe this scanned book page faithfully.

Content fidelity:
- Do not summarize, translate, modernize, rewrite, or improve the author's text.
- Preserve Vietnamese diacritics, punctuation, numbers, letter case, and meaningful
  reading order.
- Reconstruct paragraphs semantically; do not preserve arbitrary scan line wrapping.
- If any content is unclear, do not invent missing words. Transcribe only what can be
  supported by the image and add a concise warning describing the uncertainty.

Semantic structure:
- Classify visible content into semantic blocks.
- Separate probable running headers, running footers, and printed page numbers instead
  of silently deleting them.
- Record a visible printed page number separately when present.
- Use an image block to record a meaningful illustration, photograph, or diagram when
  present. Its content may be empty; do not invent a visual description.
- Put visible image captions in a separate image_caption block.

Language:
- Set the page language to the dominant visible language when confidently known.
- Set each textual block's language independently so mixed-language pages remain
  representable.
- Prefer lowercase ISO 639-1 language codes such as "vi" or "en" when applicable.
- Use null when the language is not meaningful or cannot be determined confidently.

Semantic typography:
- Every text span MUST explicitly classify posture, weight, vertical position, and
  caps style from the visible glyphs in that span.
- posture is roman, italic, or unknown.
- weight is normal, bold, or unknown.
- vertical_position is baseline, superscript, subscript, or unknown.
- caps_style is normal, small_caps, or unknown.
- decorations may contain underline when visibly present.
- Preserve uppercase/lowercase directly in span text. Uppercase text by itself is not
  small caps.
- Do not infer a style from neighboring lines, surrounding paragraphs, document
  context, expected typography, or semantic role.
- In particular, a plain roman label immediately before or after italic text must
  remain roman when its own glyphs are upright.
- Use unknown for a typography dimension when visual evidence is genuinely
  insufficient. Do not guess.
- When a typography dimension is unknown, add a concise page warning identifying the
  affected text when practical.
- Use multiple spans when typography changes inside one block.
- Record block alignment only when left/center/right/justify alignment is visually
  clear and meaningful.
- Do not preserve exact font family, font size, paper margins, pixel coordinates, or
  line breaks caused only by the printed page width.
""",
)

_TYPOGRAPHY_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "posture",
        "weight",
        "vertical_position",
        "caps_style",
        "decorations",
    ],
    "properties": {
        "posture": {
            "type": "string",
            "enum": ["roman", "italic", "unknown"],
        },
        "weight": {
            "type": "string",
            "enum": ["normal", "bold", "unknown"],
        },
        "vertical_position": {
            "type": "string",
            "enum": ["baseline", "superscript", "subscript", "unknown"],
        },
        "caps_style": {
            "type": "string",
            "enum": ["normal", "small_caps", "unknown"],
        },
        "decorations": {
            "type": "array",
            "uniqueItems": True,
            "items": {
                "type": "string",
                "enum": ["underline"],
            },
        },
    },
}

EBOOK_PAGE_SCHEMA = ExtractionSchema(
    name="ebook_page_content",
    version="4",
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
            },
            "language": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
            },
            "printed_page_number": {
                "anyOf": [{"type": "string"}, {"type": "null"}],
            },
            "blocks": {
                "type": "array",
                "items": {
                    "type": "object",
                    "additionalProperties": False,
                    "required": [
                        "type",
                        "content",
                        "language",
                        "level",
                        "alignment",
                    ],
                    "properties": {
                        "type": {
                            "type": "string",
                            "enum": [
                                "heading",
                                "paragraph",
                                "quote",
                                "list",
                                "image",
                                "image_caption",
                                "footnote",
                                "table",
                                "page_header",
                                "page_footer",
                                "page_number",
                                "other",
                            ],
                        },
                        "content": {
                            "type": "array",
                            "items": {
                                "type": "object",
                                "additionalProperties": False,
                                "required": ["text", "typography"],
                                "properties": {
                                    "text": {"type": "string"},
                                    "typography": _TYPOGRAPHY_SCHEMA,
                                },
                            },
                        },
                        "language": {
                            "anyOf": [{"type": "string"}, {"type": "null"}],
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
                        },
                        "alignment": {
                            "anyOf": [
                                {
                                    "type": "string",
                                    "enum": [
                                        "left",
                                        "center",
                                        "right",
                                        "justify",
                                    ],
                                },
                                {"type": "null"},
                            ],
                        },
                    },
                },
            },
            "warnings": {
                "type": "array",
                "items": {"type": "string"},
            },
        },
    },
)
