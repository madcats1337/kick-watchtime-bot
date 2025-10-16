# Kick.com Watchtime Discord Bot

A Discord bot that tracks your Kick.com viewers’ watchtime and rewards loyal fans with Discord roles.

### 🧰 Features
- Connects to your Kick.com chat (via WebSocket)
- Tracks viewer activity → adds watchtime
- `/link` command to connect Kick ↔ Discord
- `/leaderboard` command for top watchers
- Auto-assigns roles to loyal viewers
- Fully Dockerized and Render-compatible

### 🏗️ Deployment (Render)
1. Push this repo to GitHub.
2. Go to [Render.com](https://render.com).
3. Create a **New Web Service** → connect your repo.
4. Set **Environment Variables**:
   - `DISCORD_TOKEN`
   - `DISCORD_GUILD_ID`
   - `KICK_CHANNEL`
   - `WATCH_INTERVAL`
5. Deploy 🚀
