# Bonus Buy Tournament — Implementation

Viewer-vs-viewer, single-elimination bonus-buy tournament. Viewers `!call` a
slot (existing slot-request flow), the streamer drafts N of them into a seeded
bracket, each match is decided by the **higher bonus-buy payout**, winners
advance until one champion remains. An OBS match widget shows the head-to-head
with a center-stage winner reveal.

Built across both repos, modeled on the raffle system (rounds, provably-fair
selection, admin-gated reveal, Redis→bot→Discord/Kick announcements, SSE OBS
widget). **Tier:** TIER2+ (`tournament` feature).

---

## Data model — `Admin-Dashboard/run_migration.py` (idempotent)

Three tables (also documented in `schema.sql`), all scoped by `discord_server_id`:

- **`tournaments`** — `id, discord_server_id, name, size (4/8/16/32),
  total_rounds (=log2 size), current_round, status
  (draft|drafting|active|completed|cancelled), champion_competitor_id,
  server_seed, server_seed_commitment, created_at, completed_at`.
  Partial unique index `idx_tournaments_one_active_per_server` enforces one
  drafting/active tournament per server (mirrors the raffle-period fix).
- **`tournament_competitors`** — drafted pool: `tournament_id, kick_username,
  display_name, avatar_url, seed (1..size), slot_request_id, eliminated,
  final_rank`.
- **`tournament_matches`** — bracket slots: `tournament_id, round,
  match_number, competitor1_id, competitor2_id, c1_/c2_{slot_name,buy_in,
  payout,multiplier}, winner_competitor_id, status
  (pending|awaiting_payouts|decided), decided_at`. Unique
  `(tournament_id, round, match_number)`.

Apply with `railway run python run_migration.py` (safe to re-run).

---

## Engine — `Admin-Dashboard/utils/tournament.py`

psycopg2 + RealDictCursor, `conn`-first, server-scoped. Reuses
`utils/provably_fair.py` and `utils/database.py` slot helpers
(`get_wager_platform`, `slot_table_for_platform`, `find_matching_slot`).

- `create_tournament(conn, server_id, name, size)` — commits a server seed
  (commit-reveal), status `draft`.
- `draft_competitors(conn, tournament_id)` — eligible = unpicked `slot_requests`
  for the server, not in `slot_call_blacklist`; provably-fair shuffle via the
  committed seed into seeds 1..size; inserts competitors, marks source requests
  picked, builds round-1 matches by standard seeding (seed N vs size+1−N) and
  pre-creates empty later-round matches; status → `active`.
- `set_match_payouts(conn, match_id, side, slot_name, buy_in, payout, multiplier)`
  — records one side ('c1'/'c2'); resolves slot art; flips to
  `awaiting_payouts` when both sides are in. Multiplier derived if omitted.
- `decide_match(conn, match_id)` — higher payout wins (tie: multiplier, then
  competitor1); marks loser eliminated; advances winner to
  `round+1, ceil(match_number/2)` (odd→c1, even→c2); completes the tournament +
  sets champion on the final.
- `get_bracket` / `get_active_tournament` / `get_active_match` / `cancel_tournament`.

---

## API — `Admin-Dashboard/app.py`

Management (`@login_required @admin_required @tier_required("tournament")`):
`POST /api/tournament/create`, `POST /api/tournament/<id>/draft`,
`GET /api/tournament/active`, `GET /api/tournament/<id>/bracket`,
`POST /api/tournament/match/<id>/payouts`,
`POST /api/tournament/match/<id>/decide`, `POST /api/tournament/<id>/cancel`.

Realtime: payouts/decide publish to the widget channel
**`tournament:match:events`** (`match_payout`, `match_decided`) via raw
`redis_client`. When both payouts land, `payouts` **auto-decides + auto-reveals**
(the confirmed default). `POST /api/tournament/animation/complete` (auth-less,
like its raffle twin) → `redis_publisher.tournament_announce_winner` on
**`dashboard:tournament`** so the bot announces, plus a `match_landed` sync.

Public (`@public_tier_required("tournament")`):
`GET /api/tournament/match/stream` (SSE, 15s keepalive),
`GET /api/tournament/active/public?server_id=` (widget bootstrap).

---

## Bot — `Kick-dicord-bot/redis_subscriber.py`

`"dashboard:tournament"` added to the subscribe list, the resubscribe block, and
the channel dispatcher → `handle_tournament_event(action, data)`. On
`announce_winner` it posts the decided match to the stream chat
(`announce_in_chat` → Kick/Twitch fan-out) and to Discord, with a champion line
on the final. The Discord channel is the dedicated
`bot_settings.tournament_announcement_channel_id` (set via a ChannelSelect on the
Tournament page), falling back to `slot_calls_channel_id` when unset.

Tier map: `"tournament"` added to `TIER2` in **both** `utils/subscription_tier.py`
(bot) and `Admin-Dashboard/utils/tiers.py` (dashboard) — kept in sync.

---

## Frontend

- **Page** `frontend/src/pages/Tournament.tsx` + client `api/tournament.ts`:
  setup (create + size → auto-draft), bracket view (rounds as columns), per-side
  payout entry; both-in → backend auto-decides and the widget reveal fires. Also
  a Discord channel picker (ChannelSelect → `/api/bot-settings`
  `tournament_announcement_channel_id`).
- **Wiring** `App.tsx`: nav item (`Swords`, Bonus Hunt section), `NAV_FEATURE`
  `tournament: 'tournament'`, desktop-only `md`, route
  `gated('tournament', TournamentPage)`.
- **Widget** ported from `tournament-match-widget.mockup.html` into
  `widget-templates/` as the `tournament-match` template (category `Tournament`).
  Hook `useTournamentMatchData.ts` (SSE) drives phases pending → awaiting →
  reveal. Authored in `calc(N * var(--cqw))` (CEF-safe, scales with the OBS
  source), with the per-instance SVG `feGaussianBlur` velocity-blur reveal.

---

## Verification

1. `railway run python run_migration.py` twice → tables created then no-op.
2. Engine unit: create size-8, draft (deterministic from seed), set payouts,
   decide, assert advancement + champion (bracket logic verified separately).
3. API: authed calls per server; second server can't see the first's; gate
   returns 402 when tier lacks `tournament`.
4. Realtime: `/payouts` then auto-decide → subscriber on
   `tournament:match:events` sees `match_payout` + `match_decided`;
   `dashboard:tournament` gets `announce_winner` after `/animation/complete`.
5. Bot: staging guild → winner announced to Discord + Kick.
6. Widget: `/widget/<id>` plays Awaiting payout… → payouts land → ~1s hold →
   slide-to-centre velocity blur → glow/WIN/payout pop → next match.

Frontend `tsc` + production build both pass.

## Notes
- Public, streamer-facing → its own changelog entry on ship (no emojis,
  professional tone); exclude any super-admin-only pieces.
- Deferred: auto-pull payouts from a linked bonus-hunt session; hand-pick draft
  override; explicit manual reveal gating (endpoint exists, not the default).
