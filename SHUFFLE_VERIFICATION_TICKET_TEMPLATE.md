# 🎰 Shuffle Account Verification - Ticket Welcome Message

Use this as the welcome message in your TicketTool panel for Shuffle verification.

---

## Discord Embed Format

**Title:** 🎰 Shuffle Account Verification

**Description:**

```
Welcome {user}! 👋

Thank you for wanting to link your Shuffle.com account to earn raffle tickets!

📋 **What You Need to Provide:**

1️⃣ Your **Shuffle.com username**
2️⃣ Screenshot showing you used affiliate code **"lele"**

💡 **How to Find Your Info:**

**Your Shuffle Username:**
• Go to https://shuffle.com
• Click your profile (top right)
• Your username is displayed

**Verify Affiliate Code:**
• Go to Shuffle Settings
• Check "Affiliate Code" section
• Should show: `lele`
• Take a screenshot

⚠️ **Important Requirements:**
• You must have your Kick account linked to Discord first
• You must use affiliate code "lele" when wagering
• One Shuffle account per Discord user
• Admin will verify before approval

🎟️ **Ticket Rewards:**
Once verified, you'll earn **20 raffle tickets per $1000 wagered** on Shuffle.com!

📝 **Please Reply Below With:**
```
Shuffle Username: [your_username]
Affiliate Code: lele ✅
Screenshot: [attach image]
```

An admin will review and verify your account shortly! ⏳
```

**Color:** `#FFD700` (Gold)

**Thumbnail:** https://shuffle.com/favicon.ico (or your server logo)

**Footer:** Raffle System • Powered by TicketTool

---

## Plain Text Version (If Embeds Not Supported)

```
🎰 **Shuffle Account Verification**

Welcome {user}! 👋

Thank you for wanting to link your Shuffle.com account to earn raffle tickets!

━━━━━━━━━━━━━━━━━━━━━━━━━━

📋 **WHAT YOU NEED TO PROVIDE:**

1. Your Shuffle.com username
2. Screenshot showing affiliate code "lele"

━━━━━━━━━━━━━━━━━━━━━━━━━━

💡 **HOW TO FIND YOUR INFO:**

**Your Shuffle Username:**
→ Go to https://shuffle.com
→ Click your profile (top right)
→ Copy your username

**Verify Affiliate Code:**
→ Go to Shuffle Settings
→ Check "Affiliate Code" section
→ Must show: lele
→ Take a screenshot

━━━━━━━━━━━━━━━━━━━━━━━━━━

⚠️ **REQUIREMENTS:**
✓ Kick account linked to Discord first
✓ Must use affiliate code "lele"
✓ One Shuffle account per Discord user
✓ Admin verification required

━━━━━━━━━━━━━━━━━━━━━━━━━━

🎟️ **REWARDS:**
Once verified: 20 raffle tickets per $1000 wagered!

━━━━━━━━━━━━━━━━━━━━━━━━━━

📝 **PLEASE REPLY WITH:**

Shuffle Username: [your_username]
Affiliate Code: lele ✅
Screenshot: [attach image]

An admin will review shortly! ⏳
```

---

## TicketTool Setup Instructions

### 1. Create Panel

In Discord:
```
/panel create
```

**Settings:**
- Panel Name: `Shuffle Verification`
- Category: Create/select "Support Tickets" category
- Button Label: `🎰 Link Shuffle Account`
- Button Color: Green
- Max Tickets Per User: 1 (they can only have 1 open at a time)

### 2. Set Welcome Message

```
/panel edit [panel_id] welcome_message
```

Paste the embed or plain text message above.

### 3. Configure Permissions

**Ticket Category Permissions:**
- Staff Role: View + Send Messages + Manage Messages
- Everyone: No Access
- Ticket Creator: View + Send Messages (auto-granted by TicketTool)

### 4. Add Auto-Responses (Optional)

Create saved responses for common questions:

```
/response create verified
```
Message:
```
✅ **Your Shuffle account has been verified!**

You'll now earn **20 raffle tickets per $1000 wagered** on Shuffle.com using code "lele"!

Check your tickets anytime with: `!tickets`
View leaderboard: `!raffleboard`

This ticket will be closed. Thank you! 🎉
```

```
/response create rejected
```
Message:
```
❌ **Verification Failed**

Your Shuffle account could not be verified because:
[Admin: Edit this with reason]

Common issues:
• Affiliate code is not "lele"
• Shuffle username doesn't match
• No wager activity found
• Already linked to another Discord account

Please fix the issue and create a new ticket. Need help? Ask an admin!
```

---

## Staff Quick Reference

When a ticket is opened:

1. **Check Prerequisites:**
   ```
   !watchtime @user
   ```
   → Verify they have Kick linked

2. **Verify Shuffle Account:**
   - Check screenshot for "lele" code
   - Go to: https://affiliate.shuffle.com/stats/1755f751-33a9-4532-804e-b14b5c90236b
   - Find their username in the list
   - Verify campaign code shows "lele"

3. **Approve Link:**
   ```
   !raffleverify @user [shuffle_username]
   ```

4. **Respond & Close:**
   ```
   /response verified
   /ticket close
   ```

---

## Alternative: Auto-Response Bot

If you want the bot to automatically respond when tickets are created, you can set up a webhook listener. Let me know if you want that implementation!

---

## Button Panel Message (Server Announcements)

Post this in your server announcements:

```
🎰 **LINK YOUR SHUFFLE ACCOUNT** 🎰

Want to earn raffle tickets from your Shuffle.com wagers?

**Click the button below to start verification! ↓**

🎟️ **Rewards:** 20 tickets per $1000 wagered
🔗 **Required:** Affiliate code "lele"
⏱️ **Verification Time:** Usually under 24 hours

[🎰 Link Shuffle Account Button]
```

---

## Tips for Staff

**Quick Verification Checklist:**
- ✅ User has Kick linked (`!watchtime @user`)
- ✅ Screenshot shows "lele" code clearly
- ✅ Username found in affiliate dashboard
- ✅ Campaign code matches "lele"
- ✅ Not already linked to another Discord account

**Reject Reasons:**
- No Kick account linked
- Wrong affiliate code (not "lele")
- Username not found in dashboard
- Already linked elsewhere
- Insufficient/missing proof

---

Save this file for your staff reference and TicketTool configuration!
