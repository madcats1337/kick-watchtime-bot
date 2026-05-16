# Terms of Service

**Last Updated:** May 2026

## 1. Acceptance of Terms

By using the LeleBot Discord bot and associated Admin Dashboard (collectively, the "Service"), you agree to be bound by these Terms of Service ("Terms"). If you do not agree to these Terms, please do not use the Service.

## 2. Description of Service

LeleBot is a comprehensive Discord-Kick integration platform providing automation, community engagement, and fair gaming systems. The Service includes:

**Core Discord Bot Features:**
- **Account Linking:** Secure OAuth 2.0 linking between Discord and Kick.com accounts
- **Watchtime Tracking:** Real-time tracking of viewer activity in Kick.com chat
- **Automated Role Assignment:** Discord roles assigned based on watchtime milestones
- **Leaderboard & Statistics:** Display top viewers and personal watchtime data
- **Raffle System:** Multi-source ticket earning (watchtime, gifted subs, gambling wagers)
- **Slot Request Management:** Chat commands for requesting slots with Discord notifications
- **Gifted Subscription Tracking:** Real-time detection and ticket awards for gifted subs
- **Multi-Platform Gambling Integration:** Support for Shuffle, Stake, Stake.us wager tracking
- **Guess The Balance Game:** Interactive game with `!gtb` commands
- **Custom Commands:** User-defined commands without code changes
- **Giveaway System:** Raffle-integrated giveaway management
- **Timed Messages:** Scheduled announcements in Kick chat

**Admin Dashboard Features** (Separate Repository):
- **Analytics & Monitoring:** Real-time bot status, watchtime stats, raffle analytics
- **Account Management:** Manage linked accounts, verify users, view account history
- **Raffle Administration:** Monitor tickets, manage periods, view draws and leaderboards
- **Slot Management:** Configure request limits, search slots, manage blacklists
- **Gambling Integration:** Configure platforms, verify accounts, track wagers
- **Role Configuration:** Set watchtime thresholds and manage reward roles
- **Custom Commands:** Create and edit custom commands with variables
- **Settings & Configuration:** Manage bot behavior, feature toggles, intervals
- **Audit Trail:** View activity logs and manage security

## 3. User Responsibilities

By using the Service, you agree to:
- Provide accurate information when linking your Kick.com account
- Link only accounts you own and have permission to access
- Not attempt to manipulate, exploit, or abuse any features
- Not use the Service for any illegal or unauthorized purpose
- Comply with Discord's Terms of Service and Community Guidelines
- Comply with Kick.com's Terms of Service
- Respect other users and community guidelines

## 4. Account Linking

- You may only link one Discord account to one Kick.com account per server
- Account linking requires OAuth authorization through Kick.com
- You are responsible for maintaining the security of your linked accounts
- We reserve the right to unlink accounts that violate these Terms
- You may request to unlink your account at any time by contacting a server administrator or using the `/unlink` command

## 5. Watchtime Tracking

- Watchtime is tracked based on chat activity in the monitored Kick.com channel
- You must be actively participating in chat to earn watchtime
- Anti-farming protections are in place to ensure fair tracking
- Daily watchtime limits may be enforced (default: 18 hours)
- Watchtime data is calculated based on chat messages and may not reflect exact viewing time
- Watchtime contributes to raffle tickets for weekly/monthly draws

## 6. Slot Request System

- Slot requests are subject to availability and streamer discretion
- Requests are picked using a provably fair random selection algorithm
- Slot rewards (tips/bonus buys) are determined using the same provably fair system
- Only verified (linked) users are eligible for slot rewards
- All provably fair data is publicly verifiable at `/provably-fair/winners`

## 7. Raffle and Giveaway Systems

- Raffles and giveaways use provably fair algorithms
- Winners are selected using cryptographically secure random selection
- All draws can be independently verified using the provided seeds and hashes
- Entry requirements and eligibility are set by server administrators
- Prize distribution is at the discretion of server administrators

## 8. Point Shop

- Points are earned through chat activity and watchtime
- Point balances are server-specific and non-transferable
- Points have no real monetary value
- Point shop items and pricing are set by server administrators
- We reserve the right to adjust point balances for system integrity

## 9. Prohibited Activities

You may NOT:
- Use multiple accounts to farm watchtime, points, or entries (alt accounts)
- Attempt to manipulate or exploit the tracking or randomization systems
- Share or sell your linked account
- Use automated tools, bots, or scripts to generate fake activity
- Harass, abuse, or spam other users
- Attempt to gain unauthorized access to the Service or its database
- Reverse engineer, decompile, or modify the Service's code
- Abuse the slot request or giveaway systems
- Attempt to predict or manipulate provably fair outcomes

## 10. Provably Fair System

- The Service uses provably fair algorithms for slot picks, raffles, and giveaways
- Server seeds are generated using cryptographically secure random generation
- All random outcomes can be verified using SHA-256 hash verification
- Verification tools are publicly available at `/provably-fair/winners#verify`
- We do not and cannot manipulate provably fair outcomes

## 11. Data Collection and Privacy

- The Service collects and stores data as described in our Privacy Policy
- By using the Service, you consent to data collection as outlined in the Privacy Policy
- Data is stored securely and used only for Service functionality

## 12. Termination

We reserve the right to:
- Terminate or suspend your access to the Service at any time
- Remove your linked account data
- Deny service without prior notice
- Modify or discontinue the Service at any time

Reasons for termination may include:
- Violation of these Terms
- Fraudulent or illegal activity
- Abuse of the Service's features
- At the request of server administrators

## 13. Disclaimer of Warranties

THE SERVICE IS PROVIDED "AS IS" WITHOUT WARRANTY OF ANY KIND, EXPRESS OR IMPLIED. WE DO NOT GUARANTEE:
- Uninterrupted or error-free operation
- Accuracy of watchtime tracking or point calculations
- Availability of the service
- That the Service will meet your specific requirements
- Fairness of outcomes beyond the provably fair algorithm

## 14. Limitation of Liability

TO THE MAXIMUM EXTENT PERMITTED BY LAW, WE SHALL NOT BE LIABLE FOR:
- Any indirect, incidental, special, or consequential damages
- Loss of data, profits, or revenue
- Service interruptions or data loss
- Damages resulting from use or inability to use the Service
- Outcomes of raffles, giveaways, or slot reward systems

## 15. Third-Party Services

The Service integrates with third-party services including:
- **Discord** - Chat platform and bot hosting
- **Kick.com** - Streaming platform and OAuth provider
- **Pusher** - Real-time messaging
- **Railway.app** - Hosting infrastructure

You are subject to the terms and policies of these third-party services.

## 16. Intellectual Property

- The Service and its original content, features, and functionality are owned by LeleBot
- You may not copy, modify, distribute, or create derivative works without permission
- OBS overlays may be used for streaming purposes as intended

## 17. Changes to Terms

We reserve the right to modify these Terms at any time. Changes will be effective immediately upon posting. Your continued use of the Service after changes constitutes acceptance of the modified Terms.

## 18. Severability

If any provision of these Terms is found to be unenforceable or invalid, that provision shall be limited or eliminated to the minimum extent necessary, and the remaining provisions shall remain in full force and effect.

## 19. Governing Law

These Terms shall be governed by and construed in accordance with applicable laws, without regard to conflict of law principles.

## 20. Contact Information

For questions about these Terms:
- Contact server administrators in the Discord server where the bot is deployed
- Visit the Admin Dashboard for server-specific support

---

**By using the Service, you acknowledge that you have read, understood, and agree to be bound by these Terms of Service.**
