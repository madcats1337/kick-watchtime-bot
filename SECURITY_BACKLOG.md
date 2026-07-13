# Security Backlog — Kick Discord Bot

Deferred / follow-up items from the 2026-07-13 security review. The Critical and High
items were fixed in that pass; the items below need operator action or later work.
See also `Admin-Dashboard/SECURITY_BACKLOG.md`.

## Ops actions required (do these now — the leaked credential is the priority)

- **CRITICAL — rotate the production Postgres password.** A live connection string was
  committed in `check_db.py` / `fix_chatroom.py` and remains in git history
  (`postgres@shinkansen.proxy.rlwy.net:57221`, a public Railway proxy). Assume it is
  compromised:
  1. Rotate the password in Railway now.
  2. Purge it from history (`git filter-repo --replace-text` or BFG), then force-push.
     It appears across multiple commits (`17b1cc0`, `3d88839`, and earlier).
  3. Audit for any other user/service that shared that password.
  The scripts now read `DATABASE_URL` from the environment, but that does not undo the
  historical exposure.
- **Set `REDIS_MSG_SECRET`** (same value as the dashboard) to turn on Redis pub/sub
  message authentication. Deploy code first (no-op without the secret), then enable the
  secret on both services and restart together.
- **Leave `ENABLE_TEST_WEBHOOKS` unset in production.** The `/webhooks/kick/simulate*`
  routes (which bypass signature verification) are now disabled unless this flag is set.
- Confirm `REDIS_URL` uses a password and Redis is on the private network.

## Deferred code hardening

- **`allowed_mentions` audit.** A safe default is now set on the bot
  (`AllowedMentions(everyone=False, roles=False, users=True)`). Audit any `channel.send`
  path that puts Kick/Twitch chat text into `content=` to confirm none needs a stricter
  per-send override (e.g. `.none()` where user mentions aren't wanted either).
- **Dead duplicate `kick_chat_loop`.** There are two definitions (`bot.py` ~2517 and
  ~3201); the second shadows the first, leaving ~700 lines of dead code. Remove the
  shadowed one to shrink the module and reduce confusion.
- **Single shared `aiohttp.ClientSession`.** ~20 ad-hoc `ClientSession()` creations in
  `bot.py` each spin up a fresh connector/DNS cache. Not a resident leak, but a shared
  session would cut connector churn.
- **Member cache tuning (deferred from the memory pass).** `chunk_guilds_at_startup` and
  `member_cache_flags` are the largest resident lever but risk breaking `update_roles_task`
  and other `guild.members` iterators. Revisit as a separate, tested change with metrics.
- **Point-shop mosaic memory spike.** `bot.py` (`_dm`/mosaic generation) downloads all
  shop item images into memory and composites a tall canvas. Downscale/stream and use
  `optimize=True` to cap transient RSS.

## Deferred: re-enable bandit B105 / B608

`B105` (hardcoded password) and `B608` (SQL f-strings) remain in the
`[tool.bandit] skips` list. Cleanly re-enabling them was attempted and reverted:

- Every current `B608` hit is a **false positive** - all dynamic SQL uses
  hardcoded / closed-set identifiers (table/column names from fixed tuples or
  validated maps) with bound parameters; the review found no injection reachable
  from chat, webhook, or Redis input. Every `B105` hit is an OAuth endpoint URL,
  not a secret.
- A committed bandit baseline does **not** work with the pre-commit hook: pre-commit
  passes bandit a per-file list, and `bandit --baseline` only applies to a single
  recursive target, so the baseline is ignored and the safe findings fail the hook.
  It is also fragile (any line shift un-grandfathers a finding).

To re-enable later, pick one:
- Add `# nosec B608` / `# nosec B105` at each confirmed-safe site (the ~7 multiline
  `text(f""" ... """)` queries need collapsing to a single line so the `# nosec`
  lands on the reported line), or
- Move bandit to a CI job that runs `bandit -c pyproject.toml -r . --baseline <file>`
  (recursive single target, where `--baseline` works).

Separately, the higher-value control for the original leaked-credential risk (C1) is
a dedicated **secret scanner** (gitleaks / detect-secrets / ggshield) in pre-commit or
CI - the dashboard already has a ggshield cache; enable an equivalent here.
