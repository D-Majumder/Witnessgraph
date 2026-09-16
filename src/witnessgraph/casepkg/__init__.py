"""Researcher case package: a portable, human-authorable interchange format.

See ``docs/research/witnessgraph-case-format.md`` for the full schema
documentation and ``docs/research/witnessgraph-researcher-guide.md`` for
the researcher-facing workflow this package implements.

This is deliberately a second *representation* of an existing case's
content, not a second persistence layer (DESIGN.md's locked object model
and ``witnessgraph.store``/``witnessgraph.store.case.Case`` remain the
only place a case is actually stored). A case package is either:

- imported into a brand-new ``Case`` (``importer.import_case_package``),
  reusing exactly the same domain constructors
  (``EvidenceItem.create``, ``Entity``, ``Relationship.create``,
  ``NormalizedEvent.create``, ``TimeAssertion.create``, ``Hypothesis``)
  and the same ``Store``/``BlobStore`` writes every other case-building
  path in this codebase (the CLI's ``entities create``,
  ``relationships create``, ``ingest``, ...) already uses; or
- produced from an existing ``Case`` (``exporter.export_case_package``)
  for sharing with another researcher.

Everything a package declares is either an observed fact (evidence,
normalized events, entities, relationships, time assertions -- backed by
the researcher's own explicit ``derived_from``/``source_locator``
declaration, exactly like every other Witnessgraph ingestion path) or an
explicitly-typed researcher hypothesis (``Hypothesis``, which can only
ever reference evidence, never assert a bare fact -- DESIGN.md principle
3). A case package never declares, and this module never computes,
findings/contradictions/gaps -- those are system-derived analysis
produced by ``witnessgraph.correlate`` over an already-imported case, not
importable input (see ``docs/research/witnessgraph-case-format.md``
§"Declared fact vs. system-derived analysis vs. researcher hypothesis").
"""

from __future__ import annotations

from witnessgraph.casepkg.schema import CASE_PACKAGE_SCHEMA_VERSION, CasePackage

__all__ = ["CASE_PACKAGE_SCHEMA_VERSION", "CasePackage"]
