"""Participant-facing instruction text.

Wording is reviewed against ``docs/research/wg-study.md`` section 4's
neutrality requirements: it explains the task and the three possible
answers, states there is no penalty for answering INDETERMINATE, and
does not name, describe, or hint at the study's research hypothesis or
which condition (which this text never names either) is expected to
perform better. It is shown identically to every participant regardless
of assigned condition.
"""

from __future__ import annotations

PARTICIPANT_INSTRUCTIONS = """\
WG-Study: Provenance Reasoning Task
====================================

This is a research task about interpreting the information a case
record provides about where evidence came from.

In each case, you will see one or more "chains" -- structural paths
connecting two records -- along with some information about the
evidence associated with each chain. Exactly what information is shown
varies by case; only use what is shown to you for a given case.

Your task: for each pair of chains in a case, decide whether the
evidence underlying those two chains is:

  SHARED    -- the two chains are grounded in at least some of the same
              underlying evidence record(s).
  DISJOINT  -- the two chains are grounded in entirely separate
              underlying evidence record(s), based on what is shown.
  INDETERMINATE -- the information shown does not let you decide either
              way.

A case with only one relevant chain has no pair to compare; you will be
asked a single yes/no question about whether a second, comparable chain
is present instead.

There is no penalty for answering INDETERMINATE. If the information
shown genuinely does not support a SHARED or DISJOINT conclusion, that
is a valid and useful answer -- please do not guess.

Please answer based only on the information displayed for that
specific case. Take the time you need; your response time is recorded
but there is no time limit.

This task does not ask you to judge whether any evidence is true,
authentic, or reliable -- only whether the case record shows it as
coming from the same or different underlying source(s).
"""
