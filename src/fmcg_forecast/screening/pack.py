"""The screening pack — what counts as instruction-shaped,
as data.

The corpus the sentiment pipeline reads is an attack
surface the moment it is a live feed: a headline is text
written by someone the desk does not control, and the
model port is asked to read it. F20-AS2's rule is that
instruction-shaped text never reaches the port at all —
the screen sits in the pipeline, before any model call,
and routes a flagged item to a quarantine record a human
reviews. The screen never edits text: a legitimate item
passes to the port byte-identical, and a flagged item's
headline is stored verbatim on its record as evidence.

The rules, stated here and versioned, never buried in
code:

- Normalisation (the stated discipline a pattern is
  judged under): the text is folded to lower case,
  zero-width characters (U+200B, U+200C, U+200D,
  U+FEFF) are removed, and every run of
  non-alphanumeric characters collapses to one space.
  Patterns are stated over that folded shape, so case
  games, punctuation-splitting and zero-width splitting
  do not evade the screen — they are the same text
  under the pack's own reading of it.
- A rule is a category and the folded phrases that
  mark it. The categories are a closed vocabulary:
  instruction_override (an attempt to void the
  reader's standing instructions), role_reassignment
  (an attempt to hand the reader a new role),
  directed_verdict (an imperative telling the reader
  what conclusion to report), fake_authority (a
  pseudo system/developer marker borrowing authority
  the writer does not hold) and output_directive (an
  attempt to dictate the reader's output shape).
- Any single match quarantines the whole item.
  Screening is per item, not per sentence: a headline
  that opens as market news and closes with an
  instruction is an instruction-carrying item.
- Reporting ABOUT instructions is not instructing.
  The patterns name constructions addressed at a
  reader ("ignore previous instructions"), never the
  bare words: a ministry issuing instructions to
  states, a board revising a classification, a report
  on the new system of mandi reporting all pass.

Stated limits, in the open: text obfuscated past the
stated normalisation — leetspeak, homoglyph
substitution, instructions spelled out letter by
letter — is not caught by this pack and travels to the
port as inert text. The offline profile reads it with
the lexicon rule and finds no signal in it; a hosted
profile's residual exposure to it is a deployment
decision, recorded here rather than papered over. The
screen is one layer: commentary figures are still
computed in code, and sentiment claims still verify
against stored extractions.
"""

from __future__ import annotations

from pydantic import BaseModel, Field

CATEGORIES: tuple[str, ...] = (
    "instruction_override",
    "role_reassignment",
    "directed_verdict",
    "fake_authority",
    "output_directive",
)


class ScreenRule(BaseModel):
    """One rule: folded phrases that mark one category."""

    rule_id: str = Field(description="SCR-<category slug>-<n>")
    category: str = Field(description="One of the pack's closed categories")
    phrases: list[str] = Field(
        description="Folded phrases (lower case, single spaces); "
        "any one of them, found in the folded text, matches the rule"
    )
    rationale: str = Field(description="Why this shape is instruction, not news")


class ScreeningPack(BaseModel):
    version: str
    rules: list[ScreenRule]
    screening_rule: str = Field(description="The screening discipline, stated")


_RULES: tuple[tuple[str, str, tuple[str, ...], str], ...] = (
    (
        "SCR-override-1",
        "instruction_override",
        (
            "ignore previous instructions",
            "ignore all previous instructions",
            "ignore your previous instructions",
            "ignore your instructions",
            "ignore the instructions",
            "ignore all instructions",
            "disregard previous instructions",
            "disregard all previous instructions",
            "disregard the above instructions",
            "disregard your instructions",
            "forget your instructions",
            "forget all previous instructions",
            "override your instructions",
        ),
        "voiding the reader's standing instructions is the canonical "
        "injection opening; no market headline needs it",
    ),
    (
        "SCR-role-1",
        "role_reassignment",
        (
            "you are now",
            "act as a",
            "act as an",
            "pretend you are",
            "pretend to be",
            "from now on you are",
            "from now on act as",
            "you must now act as",
            "switch to the role of",
        ),
        "a headline reports the market; it does not assign the reader "
        "a role to read it in",
    ),
    (
        "SCR-verdict-1",
        "directed_verdict",
        (
            "classify this as",
            "classify this headline as",
            "classify this item as",
            "classify the headline as",
            "report sentiment as",
            "report the sentiment as",
            "mark this headline as",
            "mark this item as",
            "mark this as",
            "score this headline as",
            "score this as",
            "label this headline as",
            "label this as",
            "rate this headline as",
        ),
        "the reading of an item is the pipeline's stated rule, never "
        "a conclusion the item itself dictates",
    ),
    (
        "SCR-authority-1",
        "fake_authority",
        (
            "system message",
            "system instruction",
            "system prompt",
            "developer instruction",
            "developer message",
            "admin instruction",
            "new directive from",
            "updated instructions from",
        ),
        "authority markers belong to the deployment, not to corpus "
        "text; the folded shape also catches bracketed and colon "
        "forms, whose separators collapse away",
    ),
    (
        "SCR-output-1",
        "output_directive",
        (
            "respond only with",
            "respond only in",
            "reply only with",
            "answer only with",
            "output only",
            "only output",
            "do not mention",
            "never mention",
            "do not reveal",
            "without mentioning",
        ),
        "dictating the reader's output shape is an instruction, "
        "whatever it is attached to",
    ),
)

SCREENING_PACK_V1 = ScreeningPack(
    version="2026.10.1",
    rules=[
        ScreenRule(rule_id=r, category=c, phrases=list(p), rationale=why)
        for r, c, p, why in _RULES
    ],
    screening_rule=(
        "fold the text to lower case, remove zero-width characters "
        "(U+200B, U+200C, U+200D, U+FEFF), collapse every run of "
        "non-alphanumeric characters to one space and pad with a "
        "space at both ends; a rule matches when any of its folded "
        "phrases appears in the folded text; any match quarantines "
        "the whole item — the item is never extracted, never "
        "indexed and never cited, and its headline is stored "
        "verbatim on the quarantine record; an unmatched item "
        "passes to the model port byte-identical, because the "
        "screen routes and never edits"
    ),
)


def load_screening_pack(version: str | None = None) -> ScreeningPack:
    """Fail-closed loader: only the shipped pack exists in R17.

    An unknown version is an error, never a silent fallback —
    a quarantine record must name the pack it was judged under.
    """
    if version is None or version == SCREENING_PACK_V1.version:
        return SCREENING_PACK_V1
    raise ValueError(f"unknown screening pack version: {version!r}")
