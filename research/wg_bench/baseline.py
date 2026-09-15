"""A deliberately simple, provenance-blind baseline.

This classifies the connection between two entities using *only* the
count of tied-shortest relationship chains
``correlate.graph.find_all_shortest_paths`` returns -- it never inspects
``derived_from``, ``EvidenceItem``, or any other provenance field. It
exists to make explicit exactly what "graph path multiplicity alone" can
and cannot tell a reader, per WG-Bench's research question -- it is not
intended to be a good, realistic, or even reasonable classifier, only an
honest baseline for what information path count by itself carries.
"""

from __future__ import annotations

NO_OR_SINGLE_PATH = "no_or_single_path"
MULTIPLE_PATHS = "multiple_paths"


def classify_by_path_count(path_count: int) -> str:
    """Bucket a shortest-path count into the baseline's only two outputs.

    Zero or one path -> :data:`NO_OR_SINGLE_PATH` (no structural
    multiplicity to interpret at all). Two or more tied-shortest chains
    -> :data:`MULTIPLE_PATHS`. This mirrors exactly the distinction a
    reader of ``graph paths``' path *count* alone -- with no
    ``--explain`` -- could draw, and nothing more.
    """
    if path_count < 0:
        raise ValueError(f"path_count must be non-negative (got {path_count})")
    return MULTIPLE_PATHS if path_count >= 2 else NO_OR_SINGLE_PATH


def implies_independent_corroboration(classification: str) -> bool:
    """The naive reading a consumer of path-count-only output would draw.

    Treating 2+ structurally distinct shortest chains as implying
    independent, corroborating support is exactly the interpretation
    WG-Bench's research question asks whether root-evidence overlap
    analysis corrects (see ``docs/research/wg-bench.md``). This function
    names that naive reading explicitly, as one line, so it is never
    silently assumed anywhere else in the evaluation code.
    """
    return classification == MULTIPLE_PATHS
