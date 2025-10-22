# OAuth Setup Guide

This guide explains how to set up Kick OAuth authentication for instant account linking.

## Prerequisites

1. **Kick Account with 2FA enabled**
2. **Railway deployment** (or any hosting with HTTPS)
3. **Domain name** (Railway provides one automatically)

---

## Step 1: Register Your App with Kick

1. Go to https://kick.com/settings/developer
2. Click "Create App" or "New Application"
3. Fill in the application details:

   **App Name:** `[Your Bot Name] Discord Bot`  
   Example: `Maikelele Discord Bot`

   **Description:**
   ```
   Discord bot that rewards community members with roles based on Kick chat participation. 
   Tracks watchtime for active viewers and automatically assigns tiered roles.
   ```

   **Redirect URI:** `https://[your-railway-domain].up.railway.app/auth/kick/callback`  
   Example: `https://kick-discord-bot-production-1a2b.up.railway.app/auth/kick/callback`

   **Scopes:** `user:read`

4. Click "Create" or "Submit"
5. **Save your credentials:**
   - `CLIENT_ID` (e.g., `01K22E3RSA0P8MV6Y7TD3A1EHZ`)
   - `CLIENT_SECRET` (keep this secure!)

---

## Step 2: Find Your Railway Domain

1. Go to your Railway project
2. Click on your service
3. Go to "Settings" → "Domains"
4. Your domain will look like: `your-app-production-xxxx.up.railway.app`
5. Copy the full domain

---

## Step 3: Configure Environment Variables on Railway

Add these environment variables in Railway:

### Required for OAuth:

```bash
KICK_CLIENT_ID=01K22E3RSA0P8MV6Y7TD3A1EHZ
KICK_CLIENT_SECRET=your_secret_here_keep_this_secure
OAUTH_BASE_URL=https://your-app-production-xxxx.up.railway.app
```

### Existing Variables (keep these):

```bash
DISCORD_TOKEN=your_discord_bot_token
DISCORD_GUILD_ID=your_server_id
KICK_CHANNEL=Maikelele
DATABASE_URL=(automatically set by Railway PostgreSQL)
WATCH_INTERVAL_SECONDS=60
ROLE_UPDATE_INTERVAL_SECONDS=600
```

### Optional:

```bash
FLASK_SECRET_KEY=generate_random_string_here
PORT=8000
```

---

## Step 4: Deploy

After setting environment variables, Railway will automatically redeploy your bot.

**Check deployment logs for:**
```
📡 Starting OAuth web server on port 8000...
🤖 Starting Discord bot...
✅ Logged in as [YourBot]
```

---

## Step 5: Update Redirect URI (if needed)

If you get a different Railway domain after deployment:

1. Go back to https://kick.com/settings/developer
2. Edit your application
3. Update the Redirect URI to match your actual Railway domain
4. Save changes

---

## Usage

### Users can now link accounts two ways:

**Method 1: OAuth (Instant) ⚡**
```
!linkoauth
```
- Click the "Link with Kick" button
- Log in to Kick (if needed)
- Authorize → Done!

**Method 2: Bio Verification (Traditional) 📝**
```
!link username123
```
- Add code to Kick bio
- Run `!verify username123`

---

## Troubleshooting

### "OAuth not configured" error
- Check that `KICK_CLIENT_ID`, `KICK_CLIENT_SECRET`, and `OAUTH_BASE_URL` are set in Railway
- Redeploy after adding variables

### "Invalid redirect URI" from Kick
- Your Redirect URI in Kick settings must EXACTLY match: `https://[your-domain]/auth/kick/callback`
- No trailing slash
- Must be HTTPS (not HTTP)

### OAuth server not starting
- Check Railway logs for errors
- Ensure Flask and authlib are in requirements.txt
- Verify start.sh has execute permissions

### "State invalid or expired"
- Link expires after 10 minutes
- User needs to run `!linkoauth` again

---

## Security Notes

🔒 **NEVER commit your `CLIENT_SECRET` to git!**  
🔒 **Only use HTTPS in production** (Railway provides this automatically)  
🔒 **Keep your Kick developer account secure** (2FA enabled)  
🔒 **Regularly rotate CLIENT_SECRET** if compromised

---

## Testing

Test the OAuth flow:

1. In Discord, type `!linkoauth`
2. Click the "Link with Kick" button
3. Should redirect to Kick login
4. After authorization, should redirect back with success message
5. Check Discord - you should now be linked

---

## Need Help?

- Railway logs: Click on your service → "Deployments" → Latest deployment → "View Logs"
- Check `/health` endpoint: `https://your-domain.up.railway.app/health`
- Should return: `{"status": "healthy", "oauth_configured": true}`
