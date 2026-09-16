# WG-Study Participant Protocol

Status: **draft protocol for a not-yet-conducted pilot.** This document
describes how a participant session actually runs, for a reviewer (or a
future IRB-equivalent body) checking the procedure, not for the
participant themselves — participants only ever see
`research/wg_study/instructions.py::PARTICIPANT_INSTRUCTIONS`, printed
verbatim at the start of their session, and the case/question text
produced by `presentation.py`/`questions.py`. See
`docs/research/wg-study.md` for the study's scientific design (research
question, conditions, case set, ground truth, metrics) — this document
covers only the mechanics of *running* a session end to end.

## 1. Who runs what

Two entry points exist, sharing all case-building, presentation, and
question logic (`research/wg_study/session.py`):

| Command | Who uses it | Writes to | Reveals correct answers? |
| --- | --- | --- | --- |
| `python -m research.wg_study run [--participant-id ID]` | A real participant | `research/wg_study/data/participant_responses.jsonl` | Never |
| `python -m research.wg_study pilot-walkthrough` | A developer/pilot reviewer checking the interface | `research/wg_study/data/developer_validation_responses.jsonl` | Yes, after every answer |

The two files are physically separate (`storage.py`); `analyze` reads
only the participant file and unconditionally excludes any record
stamped `is_developer_validation=True`, so a pilot walkthrough can never
contaminate a real dataset even if run on the same machine, same day, as
real data collection.

## 2. What a participant actually experiences

1. Launches `python -m research.wg_study run` from a terminal in a
   checkout of this repository. No login, account, or network
   connection is required or used.
2. If `--participant-id` is omitted, an anonymous 16-hex-character token
   is generated with `secrets.token_hex(8)` and printed once, so the
   participant can record it if they need to resume later under the
   same condition/case-order assignment. No name, email, or other
   directly-identifying value is ever requested.
3. Reads `PARTICIPANT_INSTRUCTIONS` (printed once, identical for every
   participant regardless of assigned condition).
4. For each of the study's 9 cases, presented in a per-participant
   deterministic order (`runner.case_order`): sees the case rendered
   under their assigned condition (A/B/C — see
   `docs/research/wg-study.md` §3), then answers one question per
   relevant chain pair (or one single question for the one-chain
   negative-control case), typing `shared`, `disjoint`, or
   `indeterminate` (aliases: `s`/`d`/`i`/`unsure` — see
   `session.parse_answer`). An unrecognized answer reprompts with
   "Please answer one of: shared, disjoint, indeterminate." and does not
   advance or record anything.
5. Each answer's response time and text are recorded immediately
   (`runner.record_response`); the participant never sees whether an
   answer was correct at any point, and the session's closing message
   states this explicitly (see the neutrality tests below).
6. At the end, sees a brief thank-you and completion message, and
   nothing else.

## 3. What is never shown to a participant

Enforced both by module boundaries (`presentation.py` never imports
`answer_key.py` — see `docs/research/wg-study.md` §3) and by test
(`tests/unit/test_wg_study_pilot_package.py`):

- The correct answer to any question, at any point during or after a
  real session.
- The case's underlying `case_type` (e.g. `SHARED_ROOT`,
  `DISJOINT_ROOT`) or any label containing a classification-bearing
  substring (`SHARED`, `DISJOINT`, `INDEPENDENT`, `CORROBORAT`).
- Which condition (A/B/C) they are in, by name, or any hint that one
  condition is "the good one" — the instructions text is audited
  (`test_instructions_text_names_no_condition`,
  `test_instructions_text_contains_no_biasing_terms`) to contain no
  condition name and no biasing term such as "hypothesis" or "expected
  to perform better".
- The study's research question or hypotheses (H1-Study/H2-Study).

## 4. Session integrity guarantees

- **No participant-controlled filesystem paths.** A participant supplies
  only an optional `participant_id` string used as a dictionary key and
  a hash/shuffle seed input, never as part of a filesystem path
  (`storage.append_response`'s `out_dir` is always either the module's
  fixed `data/` directory or a `Path` a caller — never participant
  input — constructs directly; see
  `test_append_response_never_uses_participant_supplied_path`).
- **No command execution through participant input.** The only
  processing applied to a typed answer is a case-insensitive lookup
  against a fixed alias table (`session._ANSWER_ALIASES`); an
  unrecognized string is rejected and reprompted, never evaluated,
  interpolated into a shell command, or written anywhere except (after
  successful parsing) as a plain string field value inside a JSON
  record.
- **No network access.** Nothing in `research/wg_study/` makes an HTTP
  request or otherwise leaves the local machine.
- **No authentication.** Running the tool requires no credential.

## 5. Resuming a session

`run --participant-id ID` with the same `ID` reproduces the same
condition assignment and case order (both are deterministic functions
of `ID` — see `runner.assign_condition`/`runner.case_order`). This
protocol does not currently implement resuming mid-case-list (a
participant who stops partway and restarts with the same `ID` will be
walked through all 9 cases again from the start, recording a second set
of responses for cases already answered). `dataset_validation.py`
detects and rejects the resulting duplicate `(participant_id, case_id,
question_id)` records at analysis time rather than silently overwriting
or averaging them — see its module docstring. A future revision could
add true mid-session resume; it is out of scope for this milestone (see
`docs/research/wg-study.md` §16).

## 6. Exact commands

```sh
# Researcher: confirm the pipeline is internally consistent (no human involved).
python -m research.wg_study validate

# Researcher: print the frozen study manifest (case set, conditions, seed, versions).
python -m research.wg_study freeze

# Researcher/reviewer: walk through the real participant flow with answers revealed,
# writing only to the developer-validation file.
python -m research.wg_study pilot-walkthrough

# Participant: run one real session (anonymous id auto-generated if omitted).
python -m research.wg_study run
python -m research.wg_study run --participant-id <token>

# Researcher: validate a collected dataset's integrity before analyzing it.
python -m research.wg_study validate-dataset

# Researcher: analyze whatever real participant data currently exists.
python -m research.wg_study analyze
```
