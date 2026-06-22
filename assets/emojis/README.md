# Link-panel brand emojis

Drop the Twitch and Kick brand logos here so the combined link panel buttons show
real logos instead of the 🟢 / 🟣 unicode circles.

Required files (square, transparent PNG, ~128×128, ≤ 256 KB each — Discord's
application-emoji size limit):

- `kick.png`   — Kick logo
- `twitch.png` — Twitch logo

On startup `ensure_link_emojis()` (in
`features/linking/combined_link_panel.py`) uploads these as the bot's
**application emojis** the first time, then reuses them by name on later boots.

If a file is missing or the upload fails, that platform's button falls back to its
unicode circle and the panel still works — so the bot won't break if these aren't
in place yet.
