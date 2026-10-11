# Desktop lib CSRF audit (2026-10-11)

Card: tsk-kdv2ro (re-cut of tsk-gsoyad). Measured on `origin/dev` at `fac2932f`.

## Result

**Nothing is unprotected.** All 35 mutating calls in the 12 candidate files
get the `X-CSRF-Token` double-submit header. No fix PR is needed.

The raw "mutating fetch with no `withCsrf` reference" counts were not holes
because every one of these files calls the bare global `fetch`, and the
desktop patches `window.fetch` at startup to attach the header centrally.

## Why every call is covered

1. `desktop/src/lib/auth-guard.ts` `installAuthGuard()` replaces
   `window.fetch` with a wrapper that runs `withCsrf(init)` on every
   string/URL request whose resolved origin equals the page origin, and
   merges the token into `init` for `Request`-object inputs. It never
   overwrites a caller-set `X-CSRF-Token` and never sends the token
   cross-origin.
2. All three Vite entrypoints (`vite.config.ts` `rollupOptions.input`:
   `index.html`, `chat.html`, `app.html`) call `installAuthGuard()` at module
   top level before rendering: `desktop/src/main.tsx:13`,
   `desktop/src/chat-main.tsx:13`, `desktop/src/app-standalone-main.tsx:14`.
3. The service worker (`desktop/src/sw.ts`) is built separately but only
   handles `GET` (`sw.ts:97` returns early for any other method), so it issues
   no mutations.
4. Nothing captures a pre-patch `fetch` reference that is then used for a
   mutation. The only captures are `backendStatus.ts:40` (polls
   `GET /api/health`, created lazily inside React) and `taos-fetch.ts`
   (applies `withCsrf` itself). No `XMLHttpRequest`, `sendBeacon` or worker
   code exists under `desktop/src`.
5. Every URL in the candidate files is a relative `/api/...` path, so the
   same-origin gate in the wrapper always passes.

Step 3 of the card's method (which auth the route uses) does not change any
verdict: since every call already carries the token, no row depends on a
route being Bearer-authenticated and CSRF-exempt.

### Test evidence already on dev

- `desktop/src/lib/auth-guard.test.ts`: "attaches X-CSRF-Token to same-origin
  mutating requests only" (same-origin POST gets the token, GET does not,
  cross-origin, protocol-relative and lookalike hosts do not, `Request`
  inputs do).
- `desktop/src/__tests__/entry-guards.test.ts`: asserts all three entry
  modules install the guard on import.

### Related PRs

- #2165 (hognek fork, desktop CSRF): closed unmerged 2026-08-04. Its
  approach (global guard in all three entrypoints, plus entry-guard test)
  is what dev now carries, so there is nothing left to collide with.
- #2385 (memory.ts `withCsrf`): merged. Redundant with the guard but
  harmless (the guard skips a header the caller already set).

## Per-call verdicts

Evidence path for every row: bare global `fetch` with a relative `/api/...`
URL, patched by `installAuthGuard()` (auth-guard.ts) in all three
entrypoints. Rows marked *helper* reach `fetch` through the file's own
`fetchJson`, which spreads `init` (method included) into a bare `fetch`.

| file:line | method | function | route | verdict |
|---|---|---|---|---|
| knowledge.ts:78 | POST | `postJson` *helper* (callers :217, :247) | `/api/knowledge/rules`, `/api/knowledge/subscriptions` | covered |
| knowledge.ts:126 | DELETE | `deleteItem` | `/api/knowledge/items/{id}` | covered |
| knowledge.ts:169 | POST | `ingestUrl` | `/api/knowledge/ingest` | covered |
| knowledge.ts:224 | DELETE | `deleteRule` | `/api/knowledge/rules/{id}` | covered |
| knowledge.ts:255 | DELETE | `deleteSubscription` | `/api/knowledge/subscriptions/...` | covered |
| agent-browsers.ts:53 | POST | `postJson` *helper* (callers :129, :138) | `/api/agent-browsers/profiles/{id}/start`, `/stop` | covered |
| agent-browsers.ts:61 | PUT | `putJson` *helper* (callers :199, :208) | `/api/agent-browsers/profiles/{id}/assign`, `/move` | covered |
| agent-browsers.ts:87 | POST | `createProfile` | `/api/agent-browsers/profiles` | covered |
| agent-browsers.ts:103 | DELETE | `deleteProfile` | `/api/agent-browsers/profiles/{id}` | covered |
| agent-browsers.ts:115 | DELETE | `deleteProfileData` | `/api/agent-browsers/profiles/{id}/data` | covered |
| channel-admin-api.ts:31 | PATCH | `patchChannel` | `/api/chat/channels/{id}` | covered |
| channel-admin-api.ts:40 | POST | `addChannelMember` | `/api/chat/channels/{id}/members` | covered |
| channel-admin-api.ts:49 | POST | `removeChannelMember` | `/api/chat/channels/{id}/members` | covered |
| channel-admin-api.ts:58 | POST | `muteAgent` | `/api/chat/channels/{id}/muted` | covered |
| channel-admin-api.ts:67 | POST | `unmuteAgent` | `/api/chat/channels/{id}/muted` | covered |
| chat-messages-api.ts:9 | POST | `pinMessage` | `/api/chat/messages/{id}/pin` | covered |
| chat-messages-api.ts:14 | DELETE | `unpinMessage` | `/api/chat/messages/{id}/pin` | covered |
| chat-messages-api.ts:27 | PATCH | `editMessage` | `/api/chat/messages/{id}` | covered |
| chat-messages-api.ts:36 | DELETE | `deleteMessage` | `/api/chat/messages/{id}` | covered |
| chat-messages-api.ts:42 | POST | `markUnread` | `/api/chat/channels/{id}/read-cursor/rewind` | covered |
| userspace-apps.ts:75 | POST | `installUserspaceApp` | `/api/userspace-apps/install` | covered |
| userspace-apps.ts:99 | POST | `packageUserspaceApp` | `/api/userspace-apps/package` | covered |
| userspace-apps.ts:122 | POST | `grantUserspacePermissions` | `/api/userspace-apps/{id}/permissions` | covered |
| browser-push-api.ts:38 | POST | `subscribePush` | `/api/desktop/browser/push/subscribe` | covered |
| browser-push-api.ts:64 | DELETE | `unsubscribePush` | `/api/desktop/browser/push/subscriptions/...` | covered |
| browser-push-api.ts:93 | PUT | `setPushMute` | `/api/desktop/browser/push/mutes` | covered |
| browser-agent-api.ts:69 | POST | `pinAgent` | `/api/desktop/browser/pins` | covered |
| browser-agent-api.ts:103 | DELETE | `unpinAgent` | `/api/desktop/browser/pins?...` | covered |
| browser-agent-api.ts:119 | POST | `mintCopilotTicket` | `/api/desktop/browser/copilot/ticket` | covered |
| browser-windows-api.ts:51 | PUT | `saveWindows` | `/api/desktop/browser/windows` | covered |
| browser-windows-api.ts:68 | DELETE | `deleteWindow` | `/api/desktop/browser/windows/{id}` | covered |
| reddit.ts:166 | POST | `saveToLibrary` | `/api/knowledge/ingest` | covered |
| youtube.ts:58 | POST | `postJsonRaw` *helper* (callers :76, :83) | `/api/youtube/ingest`, `/api/youtube/download` | covered |
| taos-agent-api.ts:65 | POST | `uploadChatAttachment` | `/api/taos-agent/attachments/upload` | covered |
| use-typing-emitter.ts:22 | POST | `useTypingEmitter` | `/api/chat/channels/{id}/typing` | covered |

## What would reopen this

A new mutation is only at risk if it bypasses the patched `window.fetch`:
a new Vite entrypoint that does not call `installAuthGuard()`, a module that
captures `fetch` at import time and later mutates with it, `XMLHttpRequest`
or `sendBeacon`, a mutating request from the service worker, or an absolute
URL to a different origin that is still cookie-authenticated.
