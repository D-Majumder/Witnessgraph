"""WG-Study: controlled analyst-reasoning study infrastructure.

WG-Bench (V1/V2/V3, see ``research/wg_bench/``) measures whether
Witnessgraph's own recursive root-evidence resolution, run through its
real, unmodified production API, correctly classifies hand-authored
fixtures relative to independently-authored ground truth. It never
involves a human reader.

WG-Study asks a different, narrower question: does explicit recursive
root-evidence provenance information, as *presented to a human analyst*,
help that analyst avoid a false-corroboration misreading, relative to
graph/path information without it? This package builds the
infrastructure for that study -- case construction (drawing on WG-Bench's
existing, already-validated fixtures), a strict participant/condition
presentation layer, local-only anonymous response collection, and
analysis of whatever responses actually exist.

No human participants have been recruited as part of building this
infrastructure. No response data in this repository beyond
clearly-labeled developer-validation records (see ``validation.py``)
represents a real person's answer. See ``docs/research/wg-study.md`` for
the full protocol, hypotheses, and current status.
"""

from __future__ import annotations
