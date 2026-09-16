# WG-Study: Draft Consent and Ethics Documentation

**Status: DRAFT ONLY. This document has not been reviewed or approved by
any institutional review board (IRB), research ethics committee, or
equivalent body, because none has been sought. No participant may be
recruited or run through `python -m research.wg_study run` under this
protocol until the study owner has determined whether applicable
institutional or regulatory rules require such review for this kind of
task, and — if they do — obtained it.** This document exists so that
determination has a concrete artifact to review, not as a substitute for
it. See `docs/research/wg-study.md` §14 for the same statement in the
study's main design document.

## 1. Study summary (for a reviewing body or a prospective participant)

WG-Study asks volunteers to look at small, synthetic (not real-world)
case records — abstract graphs of relabeled entities and relationships,
never real names, real people, or real events — and judge, for pairs of
"chains" within a case, whether the underlying evidence is the same,
different, or indeterminate from what is shown. Sessions run entirely
on the participant's own local machine via a command-line program; no
data leaves that machine. See
`docs/research/wg-study-participant-protocol.md` for the exact session
mechanics and `docs/research/wg-study.md` §1–§9 for the full research
design.

## 2. Risk assessment

This is a minimal-risk task: an abstract reasoning exercise over
synthetic, fictional case data, with no deception, no sensitive
subject matter, no physical or psychological intervention, and no
real-world stakes attached to any answer. The main risks identified are:

- **Participant time burden.** A full session covers 9 cases and up to
  ~40 pairwise questions (the two 6-chain "high path multiplicity"
  cases alone contribute 15 pairs each); no fixed time limit is
  enforced, but a session may take a nontrivial amount of a
  participant's time. The instructions state there is no time limit and
  no penalty for answering `indeterminate`, specifically so a
  participant does not feel pressured to guess.
- **Mild task frustration.** Some cases are deliberately designed to be
  hard to interpret under conditions A/B (see
  `docs/research/wg-study.md` §5); a participant may find some cases
  confusing by design. This is the object of study, not a side effect
  to eliminate, but it is disclosed here as a foreseeable experience.
- **No physical, financial, legal, or reputational risk** is identified;
  the task involves no real names, real organizations, or real events,
  and no participant-identifying information is collected (§4).

No risk beyond ordinary use of a personal computer for a short cognitive
task has been identified. A reviewing body may identify others this
draft has missed; this section should be revised in response.

## 3. Draft participant-facing consent text

The following is a draft only. It has never been shown to a real
participant. The current software (`python -m research.wg_study run`)
does **not** yet display or require acknowledgment of any consent text
before starting a session — that is deliberately called out as an open
item in §6, not a completed feature.

> **WG-Study: Provenance Reasoning Task — Participant Information**
>
> You are being invited to take part in a short research task about how
> people interpret evidence-provenance information in structured case
> records. Participation is voluntary. You may stop at any time, for any
> reason, without giving one; if you stop partway, the answers you have
> already given up to that point remain recorded (see §4 for what is and
> is not stored) unless you separately ask the study owner to delete
> them.
>
> **What you will do.** You will read a short set of instructions, then
> work through 9 short cases, answering one or more multiple-choice
> questions per case (SHARED / DISJOINT / INDETERMINATE) about
> synthetic, relabeled data. There is no time limit, and answering
> INDETERMINATE is a valid, expected answer with no penalty.
>
> **What is collected.** Your answers, how long each answer took, an
> anonymous participant identifier you are not asked to make
> personally identifying, and the timestamp of each answer. No name,
> email address, or other directly-identifying information is
> requested or stored. See §4 below for the exact schema.
>
> **Where your data goes.** Nowhere but the local computer running the
> task. This program makes no network connection and uploads nothing.
> If you were asked to also share the resulting local data file with
> the study owner (e.g. by email or file transfer), that step happens
> outside this program and outside this consent text's scope — the
> study owner is responsible for describing that step to you separately
> if it applies to your participation.
>
> **Risks.** This task asks you to reason about abstract, synthetic case
> data; some cases are intentionally ambiguous. No real people, real
> events, or sensitive topics are involved.
>
> **Withdrawal.** You may stop at any point. Because responses are keyed
> to an anonymous identifier rather than your name, the study owner can
> only remove your specific data if you retain and provide your
> participant identifier (printed at the start of your session) when
> requesting removal.
>
> By continuing, you confirm that you have read the above, are age 18 or
> older [subject to whatever this study's actual age policy is set to
> by whoever conducts it], and voluntarily agree to participate.

## 4. Data collected and retention

Exactly the schema documented in `docs/research/wg-study.md` §8
(`model.ParticipantResponse`): `participant_id` (caller-supplied,
expected anonymous token), `condition`, `case_id`, `question_id`,
`answer`, `correct_answer` (never shown to the participant),
`response_time_ms`, `timestamp`, `optional_notes`, `study_version`,
`is_developer_validation`. No name, email, address, phone number,
student id, IP address, or device identifier is collected anywhere in
this pipeline. Data is retained locally, indefinitely, at the
discretion of whoever runs the study, until the study owner deletes it;
this protocol implements no automatic retention limit or expiry.

## 5. Withdrawal and data deletion mechanism

There is currently no automated per-participant deletion command.
Because `participant_id` is the only key linking records to a person,
withdrawal in practice means: the participant retains their printed
`participant_id`, and the study owner manually removes every JSONL line
in `research/wg_study/data/participant_responses.jsonl` matching that
`participant_id` (a `grep -v <id>` or equivalent, followed by
`validate-dataset` to confirm the remaining file is still well-formed).
Adding a dedicated `python -m research.wg_study withdraw <id>` command
is a reasonable future improvement and is listed as an open item below,
not implemented in this milestone.

## 6. Open items before any real recruitment

- **Institutional/ethics review determination**, per this document's own
  header — the single hard blocker before recruiting anyone.
- **In-software consent flow.** The current `run` command starts the
  task immediately; it does not display §3's consent text or require
  any acknowledgment before the first case. Adding that display (and
  recording a boolean "consent acknowledged" field, itself not
  personally identifying) is recommended before real recruitment and is
  a small, additive change to `session.run_participant_session` — not
  implemented in this milestone so as not to freeze consent wording
  before a reviewing body has seen it.
- **Age/eligibility policy** is left as a bracketed placeholder in §3
  above; the study owner must decide and fill this in as part of
  obtaining ethics review, not this document.
- **Explicit deletion command** per §5.
- **A named point of contact** for participant questions or withdrawal
  requests is not yet specified anywhere in this draft and must be
  added before real recruitment.
