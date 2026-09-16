# Witnessgraph Quickstart

The fastest path from nothing to an opened case. See
`docs/research/witnessgraph-researcher-guide.md` for the full guide and
`docs/research/witnessgraph-case-format.md` for the case package schema
reference.

## 1. Install

```sh
git clone <this repository>
cd witnessgraph
python -m venv .venv
.venv/Scripts/activate   # or: source .venv/bin/activate
pip install -e ".[dev]"
```

Requires Python 3.11+. No network access needed after `pip install`.

## 2. Create a demo case

```sh
witnessgraph case-package init demo.json
witnessgraph case-package validate demo.json
witnessgraph case-package import demo.json ./demo-case
```

`demo.json` is clearly labeled `DEMO / TEMPLATE DATA` — two synthetic
entities, one relationship, one evidence item.

## 3. Open it in the UI

Terminal 1:

```sh
witnessgraph-api ./demo-case
```

Terminal 2 (once per checkout, run `npm install` first):

```sh
cd frontend
npm run dev
```

Open the printed local URL (default `http://localhost:5173`).

## 4. Import your own case

Write a case package describing your data
(`docs/research/witnessgraph-case-format.md`), then:

```sh
witnessgraph case-package validate my-case.json
witnessgraph case-package import my-case.json ./my-case
witnessgraph-api ./my-case   # then open the UI as in step 3
```

## 5. Look at the graph and provenance

```sh
witnessgraph graph paths ./my-case <source-entity-id> <target-entity-id> --explain
witnessgraph verify ./my-case
```

`--explain` shows each chain's resolved root evidence and overlap
classification — this is the structural-vs-provenance-multiplicity
distinction Witnessgraph exists to make inspectable (see the researcher
guide's "what problem it addresses" section). `verify` recomputes and
checks the case's provenance manifest.

## 6. Export to share

```sh
witnessgraph case-package export ./my-case my-case.witnessgraph-case
```

Hand `my-case.witnessgraph-case` to another researcher; they run
`case-package import` and `witnessgraph verify` to confirm they got the
exact same case (see the researcher guide §19).

## Before you rely on any result

Read `docs/research/witnessgraph-researcher-guide.md` §3 ("what it does
NOT establish") first — in particular, disjoint provenance is a
property of your declared case model, not proof of real-world epistemic
independence, authenticity, or truth.
