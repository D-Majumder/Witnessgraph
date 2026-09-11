"""Ingestion: turns already-existing evidence sources into EvidenceItem/NormalizedEvent.

See SECURITY.md: adapters only ever read a source that already exists on
the local filesystem. There is no network- or execution-capable source
kind in v0.1.
"""
