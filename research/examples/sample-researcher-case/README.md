# Sample researcher case package

A fully synthetic worked example of the case package format
(`docs/research/witnessgraph-case-format.md`), for a researcher who
wants to see a filled-in example rather than the minimal
`witnessgraph case-package init` template.

All data in `case.json` is hand-authored and synthetic: made-up
hostnames, a made-up username, an address in the `203.0.113.0/24`
documentation range (RFC 5737), and fabricated timestamps. No real
logs, credentials, IPs, or personal data of any kind. See
`SECURITY.md`.

## What it demonstrates

- Two evidence items (`evidence_items`) with inline JSON content.
- One normalized event (`normalized_events`) derived from one of them.
- Three entities (`entities`): a user, a host, and an ip — each with
  explicit `derived_from` lineage.
- Two directed relationships (`relationships`) forming a two-hop chain:
  user → (`authenticated_as`) → host → (`connected_to`) → ip.
- One time assertion (`time_assertions`) about when the login occurred.
- One researcher hypothesis (`hypotheses`), explicitly evidence-backed
  and clearly labeled as an example, not a finding.

## Run it

```sh
pip install -e ".[dev]"   # from the repo root, once
witnessgraph case-package validate research/examples/sample-researcher-case/case.json
witnessgraph case-package import research/examples/sample-researcher-case/case.json ./sample-case
witnessgraph graph path ./sample-case <user-entity-id> <ip-entity-id> --explain
witnessgraph verify ./sample-case
```

(`case-package import`'s output prints the entity ids used above,
`entity-user`/`entity-host`/`entity-ip` — those are the same strings
used as `local_id` in `case.json`, since entity ids are exactly their
declared `local_id`; see the case format doc.)

Or export it back out and confirm the round trip is exact:

```sh
witnessgraph case-package export ./sample-case reexported.json
witnessgraph case-package import reexported.json ./sample-case-2
witnessgraph verify ./sample-case-2   # same manifest hash as ./sample-case
```
