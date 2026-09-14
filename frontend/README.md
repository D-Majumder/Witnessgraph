# Witnessgraph UI (v1)

A local-only web UI over an existing Witnessgraph case: React +
TypeScript + Cytoscape.js, talking to the `witnessgraph-api` FastAPI
backend over `fetch()`. See the root [`README.md`](../README.md#web-ui-v1)
for how to run it, and `docs/phase-ui-v1-architecture-design.md` /
`docs/phase-ui-v1-implementation.md` for the architecture and what was
actually built.

## Scripts

```sh
npm run dev        # start the Vite dev server
npm run lint        # oxlint
npm run typecheck   # tsc --noEmit
npm run test        # vitest
npm run build       # production build
```

The backend URL defaults to `http://127.0.0.1:8420`; override it with a
`VITE_API_BASE_URL` environment variable (see `.env.example`).
