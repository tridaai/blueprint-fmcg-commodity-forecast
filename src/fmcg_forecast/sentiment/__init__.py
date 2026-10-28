"""The sentiment pack (R4, Law 3): scored items, computed index.

Law 3: sentiment is a scored pack with provenance. Each item is
data — source, date, commodity, headline — stored as an artefact;
extraction turns a headline into a structured, signed reading via
the model port; the weekly index is computed in code from the
stored extractions by a stated formula. No unattributed mood
reaches a forecast: the engine's sentiment contribution is
estimated from the index like any other driver, and commentary may
only cite sentiment through the items behind it.

ISOLATION LAW (mirrors the truth store's): the corpus is planted
with a known intent per item — the grading truth for extraction.
That intent lives only in ``corpus`` (generation) and ``grading``
(the intent store), and ONLY the load path, the tests and the eval
gate may import them. The scoring path — ``pack``, ``extract``,
``index``, ``verify``, ``service``, ``models`` — must never import
either: the extractor grades itself against headlines alone, the
same discipline that keeps the forecast engine sealed off from
the future price path. A structural test and the eval gate scan
the scoring modules' import graphs for exactly this.
"""
