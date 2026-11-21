# Ordo frontend

React + Vite + TypeScript. Owned by role 6. Spec: issue #6.

## Run

```bash
npm install
npm run dev          # http://localhost:5173, mock mode
```

| Command | What it does |
|---|---|
| `npm run dev` | Development server |
| `npm run typecheck` | Regenerates the API types from `contracts/schemas`, then type-checks |
| `npm test` | Unit tests (mock mode answers every call; money formatting; recommendation guard) |
| `npm run build` | Type-check, then a static build in `dist/` |

For CI, run `npm ci`, `npm run typecheck` and `npm test` in this folder.

## The one switch: mock or live

Defined in `src/config.ts`. Nothing else changes between the two.

| Mode | Where data comes from | How to choose it |
|---|---|---|
| mock (default) | `contracts/fixtures/*.json`, answered in `src/api/mock.ts` with the response shapes of `contracts/openapi.yaml` | default, or add `?mock=1` to any URL |
| live | `VITE_API_BASE` (default `/api/v1`) | `VITE_API_MODE=live npm run dev`, or add `?mock=0` to any URL |

The URL flag is remembered for the browser tab. The sidebar shows the current mode.
In local development, live mode forwards `/api` to `VITE_API_PROXY` (default `http://localhost:8000`).

## Layout

| Path | What |
|---|---|
| `scripts/gen-types.mjs` | Generates `src/api/types.gen.ts` from `contracts/schemas`. Never edit the generated file |
| `src/api/client.ts` | Typed API functions (`api.inbox()`, `api.forecast()` …) and `subscribeEvents()` |
| `src/api/transport.ts` | The single place where mock and live differ |
| `src/api/mock.ts` | Mock answers for every API path, plus a replay of the fixture events |
| `src/api/guards.ts` | A recommendation without control level, execution mode, explanation and evidence is not rendered |
| `src/lib/money.ts` | Money formatting on the decimal string; never through a float |
| `src/lib/voice.ts`, `src/components/Voice.tsx` | Voice input in the chat: the mic records up to a minute (webm/opus, ogg/opus or mp4 by browser), Whisper on the cluster writes it down through `POST /chat/transcribe`, and the text goes into the message box for the owner to check and send. Shown only when `/health` reports `speech`; PL / EN / RU remembered per browser |
| `src/components/` | Layout with sidebar and company switcher, control-level badges, loading/error/empty state |
| `src/pages/` | Dashboard, Inbox, Documents, Sources, Activity, Chat. First versions that render fixture data; the screen tickets replace them |
| `src/styles/app.css` | Colour tokens with the same names and values as the Figma file |

## Routes

`/` dashboard, `/inbox`, `/inbox/:id`, `/documents`, `/documents/:id`, `/sources`, `/activity`, `/chat`.
Any other path (some evidence links point at views later tickets build) shows a "not built yet" page.

## Deploy note for role 1

The app uses clean URLs, so the web server must answer unknown paths with `index.html`. `nginx.conf` in this folder does that.
