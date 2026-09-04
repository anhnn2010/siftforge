"""Versioned prompt and schema contracts for faithful ebook page extraction."""

from __future__ import annotations

from siftforge.extraction.models import ExtractionSchema, PromptSpec

_SOURCE_TYPOGRAPHY_SCHEMA = {
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

# v4 remains the active runtime contract during Milestone 1F-2. Keeping explicit
# versioned names lets v5 evolve in parallel without changing the working CLI.
EBOOK_PAGE_PROMPT_V4 = PromptSpec(
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

EBOOK_PAGE_SCHEMA_V4 = ExtractionSchema(
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
                                    "typography": _SOURCE_TYPOGRAPHY_SCHEMA,
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

_MARKER_SCHEMA = {
    "anyOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["kind", "raw_text", "ordinal"],
            "properties": {
                "kind": {
                    "type": "string",
                    "enum": [
                        "bullet",
                        "numeric",
                        "alphabetic",
                        "dash",
                        "graphic",
                        "unknown",
                    ],
                },
                "raw_text": {
                    "anyOf": [{"type": "string"}, {"type": "null"}],
                },
                "ordinal": {
                    "anyOf": [
                        {"type": "integer", "minimum": 1},
                        {"type": "null"},
                    ],
                },
            },
        },
        {"type": "null"},
    ]
}

_NORMALIZED_REGION_SCHEMA = {
    "anyOf": [
        {
            "type": "object",
            "additionalProperties": False,
            "required": ["x", "y", "width", "height"],
            "properties": {
                "x": {"type": "number", "minimum": 0, "maximum": 1},
                "y": {"type": "number", "minimum": 0, "maximum": 1},
                "width": {"type": "number", "minimum": 0, "maximum": 1},
                "height": {"type": "number", "minimum": 0, "maximum": 1},
            },
        },
        {"type": "null"},
    ]
}

_V5_SPAN_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": [
        "text",
        "language",
        "source_typography",
        "semantic_line_break_after",
    ],
    "properties": {
        "text": {"type": "string"},
        "language": {
            "anyOf": [{"type": "string"}, {"type": "null"}],
        },
        "source_typography": _SOURCE_TYPOGRAPHY_SCHEMA,
        "semantic_line_break_after": {"type": "boolean"},
    },
}

EBOOK_PAGE_PROMPT_V5 = PromptSpec(
    name="ebook_page_evidence",
    version="5",
    text="""Extract faithful page-local evidence from this scanned book page.

This output is NOT the final ebook structure. Report what this physical page supports;
a later book-level structural pass will resolve cross-page continuity, containers,
heading hierarchy, running furniture, semantic emphasis, and other document-wide
relationships. Do not invent stable IDs; downstream code assigns deterministic block
and span IDs from source-page identity and array order.

Content fidelity:
- Do not summarize, translate, modernize, rewrite, proofread, or improve the text.
- Preserve Vietnamese diacritics, punctuation, numbers, letter case, and meaningful
  reading order exactly as supported by the image.
- Reconstruct prose paragraphs semantically and remove line breaks caused only by page
  width.
- If content is unclear, do not invent missing words. Transcribe only supported text
  and add a concise page warning describing the uncertainty.

Page-local role hints:
- role_hint is local evidence, not a final semantic decision. Use unknown when needed.
- Use heading for a heading-like text block. Give heading_role_hint only when the role
  is locally well supported; otherwise use unknown.
- Use list_item for one locally apparent enumeration/list item, not for a whole list.
- Use verse for poetry, lyrics, ca dao, or other line-oriented verse whose semantic
  line boundaries matter.
- Use quote for prose quotation content. Multiple quoted paragraphs may be separate
  quote blocks; a later pass will group them.
- Use attribution for a visible source/author attribution when that role is locally
  clear.
- Repeated dialogue turns are not automatically a list. A dash introducing dialogue
  punctuation should remain in the text rather than being converted to a list marker.
- Visual list formatting does not by itself prove semantic list structure. For example,
  heart-marked conversational turns may remain paragraph evidence with a visual marker.
- Separate probable running headers, running footers, and printed page-number blocks
  instead of silently deleting them. For a page-number block, language should be null.

Visual markers:
- Record a marker separately when a visible prefix or graphic functions as presentation
  or structural evidence, such as a bullet, numeric/alphabetic enumerator, list dash, or
  section graphic.
- Exclude a separately recorded marker from readable content text.
- A dash that is normal dialogue punctuation is NOT a marker and must remain in text.
- For numeric markers, record the visible raw_text and ordinal. For alphabetic sequence
  markers, ordinal may encode a=1, b=2, and so on when clear.
- For a graphic marker, set kind=graphic and raw_text=null unless literal readable text
  is actually printed. Never substitute an arbitrary Unicode glyph or emoji such as
  Apple-logo private-use characters, pointing hands, flowers, or similar approximations
  for a source graphic.

Semantic line boundaries:
- Every span has semantic_line_break_after. Set it true only when a line break carries
  meaning that must survive reflow, such as a verse/lyric line, address line, or a
  deliberately line-structured caption.
- Keep semantic_line_break_after false for ordinary prose wrapping caused only by page
  width.
- When typography changes within one semantic line, use multiple spans and set the line
  break only on the final span of that semantic line.

Language:
- Set dominant_language for the page and each textual block when confidently known.
- Set language independently on every text span so mixed-language content inside one
  block remains representable.
- Prefer lowercase ISO 639-1 codes such as "vi" or "en" when applicable.
- Use null when language is not meaningful or cannot be determined confidently.

Source typography:
- source_typography describes visible glyph appearance only. It does NOT assert EPUB
  semantic emphasis or strong importance.
- Every text span MUST explicitly classify posture, weight, vertical position, and caps
  style from its own visible glyphs.
- posture is roman, italic, or unknown.
- weight is normal, bold, or unknown.
- vertical_position is baseline, superscript, subscript, or unknown.
- caps_style is normal, small_caps, or unknown.
- decorations may contain underline when visibly present.
- Preserve uppercase/lowercase directly in text. Uppercase text by itself is not small
  caps.
- Do not infer typography from neighboring text, semantic role, expected book style, or
  surrounding paragraphs. A whole body/inset may legitimately use an italic base font
  without implying semantic emphasis.
- Use unknown rather than guessing when visual evidence is insufficient, and add a
  concise warning when practical.
- Use multiple spans whenever source typography or span language changes.

Images and regions:
- Use image for a meaningful photograph, illustration, or diagram. Do not invent a
  prose description of image content.
- Put a visible image caption in a separate caption block.
- For each meaningful image block, provide a tight normalized region using x, y, width,
  and height in the range 0..1 relative to the full page image.
- Regions are extraction/provenance evidence for later cropping, not instructions to
  reproduce the exact printed-page layout.
- Use region=null for ordinary text blocks unless a region is specifically useful and
  visually well supported.

Layout hints:
- Record alignment only when left/center/right/justify alignment is visually clear and
  meaningful.
- heading_level_hint is only a local visual/hierarchy hint from 1 to 6; use null when it
  is not meaningful.
- Do not preserve exact font family, font size, paper margins, or arbitrary physical
  line wrapping.
""",
)

EBOOK_PAGE_SCHEMA_V5 = ExtractionSchema(
    name="ebook_page_evidence",
    version="5",
    json_schema={
        "type": "object",
        "additionalProperties": False,
        "required": [
            "page_kind_hint",
            "dominant_language",
            "printed_page_number",
            "blocks",
            "warnings",
        ],
        "properties": {
            "page_kind_hint": {
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
            "dominant_language": {
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
                        "role_hint",
                        "content",
                        "dominant_language",
                        "heading_level_hint",
                        "heading_role_hint",
                        "marker",
                        "region",
                        "alignment",
                    ],
                    "properties": {
                        "role_hint": {
                            "type": "string",
                            "enum": [
                                "heading",
                                "paragraph",
                                "quote",
                                "list_item",
                                "verse",
                                "attribution",
                                "image",
                                "caption",
                                "footnote",
                                "table",
                                "page_header",
                                "page_footer",
                                "page_number",
                                "other",
                                "unknown",
                            ],
                        },
                        "content": {
                            "type": "array",
                            "items": _V5_SPAN_SCHEMA,
                        },
                        "dominant_language": {
                            "anyOf": [
                                {"type": "string"},
                                {"type": "null"},
                            ],
                        },
                        "heading_level_hint": {
                            "anyOf": [
                                {
                                    "type": "integer",
                                    "minimum": 1,
                                    "maximum": 6,
                                },
                                {"type": "null"},
                            ],
                        },
                        "heading_role_hint": {
                            "type": "string",
                            "enum": [
                                "chapter_label",
                                "chapter_title",
                                "section_title",
                                "subsection_title",
                                "subtitle",
                                "genre_label",
                                "scenario_label",
                                "scenario_title",
                                "unknown",
                            ],
                        },
                        "marker": _MARKER_SCHEMA,
                        "region": _NORMALIZED_REGION_SCHEMA,
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

# Compatibility aliases intentionally keep the proven v4 runtime active until the
# dedicated v5 normalizer lands in Milestone 1F-3.
EBOOK_PAGE_PROMPT = EBOOK_PAGE_PROMPT_V4
EBOOK_PAGE_SCHEMA = EBOOK_PAGE_SCHEMA_V4
