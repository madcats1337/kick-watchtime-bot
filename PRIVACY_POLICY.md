# Privacy Policy

**Last Updated:** January 2, 2026

## 1. Introduction

This Privacy Policy explains how we collect, use, store, and protect your personal information when you use the LeleBot Discord bot and Admin Dashboard (collectively, the "Service"). By using the Service, you agree to the collection and use of information in accordance with this policy.

## 2. Information We Collect

### 2.1 Automatically Collected Information

When you use the Service, we automatically collect:

**Discord Information:**
- Discord User ID (unique identifier)
- Discord Username and display name
- Discord Server (Guild) ID
- Discord Role assignments
- Message timestamps (for watchtime calculation)

**Kick.com Information:**
- Kick.com username
- Kick.com User ID
- Kick.com chat activity (username and timestamps only)
- Kick.com profile information accessed via OAuth

### 2.2 Information You Provide

When you use the Service, we collect:
- OAuth authorization tokens (encrypted and stored securely)
- Account linking timestamps
- Slot requests and preferences
- Giveaway entries
- Point shop orders
- Custom commands and configurations

### 2.3 Generated Data

The Service generates and stores:
- Watchtime statistics (minutes watched)
- Chat activity timestamps
- Leaderboard rankings
- Role assignment history
- Raffle ticket allocations
- Point balances
- Provably fair seeds and hashes
- Slot pick history with reward outcomes
- Giveaway winner records

## 3. How We Use Your Information

**Primary Functions:**
- Link your Discord account to your Kick.com account
- Track your watchtime based on Kick.com chat activity
- Assign Discord roles based on watchtime milestones
- Display leaderboards and statistics
- Process slot requests and determine rewards
- Manage raffle entries and draw winners
- Process giveaway entries and select winners
- Manage point shop transactions
- Send notifications about important events

**Administrative Functions:**
- Prevent abuse and fraud (anti-farming measures)
- Maintain security of the Service
- Debug and improve Service functionality
- Provide provably fair verification data
- Comply with server administrator requests

**We DO NOT:**
- Sell your personal information to third parties
- Use your information for advertising or marketing
- Share your data with unauthorized parties
- Read or store the content of your chat messages
- Track your activity outside the Service

## 4. Data Storage and Security

### 4.1 Data Storage

- Data is stored in a secure PostgreSQL database
- Database is hosted on Railway.app with encrypted connections
- Access to the database is restricted and authenticated
- OAuth tokens are stored securely and refreshed as needed
- Provably fair seeds are stored for verification purposes

### 4.2 Data Retention

We retain your data:
- **Linked Accounts:** Until you request unlinking or account deletion
- **Watchtime Data:** Indefinitely, unless you request deletion
- **OAuth Tokens:** Until they expire or are revoked
- **Temporary Data:** OAuth states deleted within 30 minutes
- **Provably Fair Data:** Retained indefinitely for verification
- **Slot Picks/Winners:** Retained indefinitely for transparency
- **Point Balances:** Until account deletion or admin reset

### 4.3 Security Measures

We implement security measures including:
- Encrypted database connections (SSL/TLS)
- HMAC-SHA256 signature verification for OAuth links
- Timestamp expiration for OAuth links (1-hour validity)
- PKCE (Proof Key for Code Exchange) for OAuth flow
- RSA signature verification for webhook events
- Authentication required for administrative functions
- Rate limiting on sensitive endpoints
- Regular security audits and updates

## 5. Provably Fair Data

### 5.1 What We Store

For transparency in raffles, giveaways, and slot rewards, we store:
- Server seeds (cryptographically random)
- Client seeds (derived from public data)
- Nonces (unique identifiers)
- Proof hashes (SHA-256 verification hashes)
- Random values (outcome determinants)

### 5.2 Public Verification

- All provably fair data is publicly viewable at `/provably-fair/winners`
- Verification tools allow independent verification of all outcomes
- This data is intentionally public for transparency

## 6. Data Sharing and Disclosure

### 6.1 When We Share Data

We may share your information only in the following circumstances:

**With Your Consent:**
- Publicly displayed leaderboards (Kick username and watchtime)
- Publicly displayed raffle/giveaway winners
- Role assignments visible to server members
- Provably fair verification data (public)

**Legal Requirements:**
- When required by law or legal process
- To protect the rights, property, or safety of users
- To enforce our Terms of Service

**Service Providers:**
- Discord (for bot functionality)
- Kick.com (for OAuth and chat monitoring)
- Pusher (for real-time updates)
- Railway.app (for hosting and database)

### 6.2 When We DO NOT Share Data

We do not:
- Sell your data to third parties
- Share your data for marketing purposes
- Provide your data to unauthorized parties
- Share OAuth tokens or private account details

## 7. Your Rights and Choices

### 7.1 Access and Control

You have the right to:
- **Access:** View your account information via commands or dashboard
- **Unlink:** Request to unlink your accounts via `/unlink` command
- **Delete:** Request deletion of your data
- **Correct:** Update incorrect information by relinking
- **Opt-Out:** Stop using the Service at any time

### 7.2 How to Exercise Your Rights

To exercise your rights:
- **Unlink Account:** Use `/unlink` command or contact a server administrator
- **Delete Data:** Contact a server administrator to request full data deletion
- **View Data:** Use `/watchtime`, `/points`, or `/tickets` commands
- **Questions:** Contact server administrators in the Discord server

### 7.3 Data Deletion

If you request data deletion, we will remove:
- Your Discord-Kick account link
- Your watchtime statistics
- Your point balances
- Your raffle ticket allocations
- Your OAuth tokens

Note: Provably fair records (winners, draws) may be retained for transparency.

## 8. Third-Party Services

The Service integrates with third-party services:

**Discord:**
- Privacy Policy: https://discord.com/privacy
- We use Discord's API in accordance with their Terms of Service

**Kick.com:**
- Privacy Policy: https://kick.com/privacy
- We use Kick.com's OAuth and public APIs
- We monitor public chat messages for watchtime tracking

**Pusher:**
- Privacy Policy: https://pusher.com/legal/privacy-policy
- Used for real-time event delivery

**Railway.app:**
- Privacy Policy: https://railway.app/legal/privacy
- Provides secure database and hosting infrastructure

We are not responsible for the privacy practices of these third-party services.

## 9. Children's Privacy

The Service is not intended for users under the age of 13 (or the minimum age required in your jurisdiction). We do not knowingly collect personal information from children. If we become aware that a child has provided us with personal information, we will take steps to delete such information.

## 10. International Data Transfers

Your data may be transferred to and stored in countries outside your country of residence. By using the Service, you consent to such transfers. We ensure appropriate safeguards are in place to protect your data.

## 11. Cookies and Tracking

- The Service uses session cookies for authentication on the dashboard
- OAuth flow uses temporary state tokens for security
- We do not use tracking cookies or third-party analytics

## 12. Changes to This Privacy Policy

We may update this Privacy Policy from time to time. Changes will be posted with an updated "Last Updated" date. Your continued use of the Service after changes constitutes acceptance of the updated Privacy Policy.

## 13. Data Breach Notification

In the unlikely event of a data breach affecting your personal information, we will:
- Investigate the breach promptly
- Notify affected users as soon as reasonably possible
- Take steps to mitigate harm
- Report to relevant authorities if required by law

## 14. Compliance

We strive to comply with applicable data protection laws, including:

### GDPR Rights (EU Users)

If you are in the European Union, you have additional rights:
- Right to access your data
- Right to rectification of inaccurate data
- Right to erasure ("right to be forgotten")
- Right to restrict processing
- Right to data portability
- Right to object to processing
- Right to withdraw consent

### CCPA Rights (California Users)

If you are a California resident, you have the right to:
- Know what personal information is collected
- Request deletion of your personal information
- Opt-out of the sale of personal information (we do not sell data)
- Non-discrimination for exercising your rights

## 15. Data Minimization

We practice data minimization by:
- Collecting only necessary information for Service functionality
- Not storing chat message content (only usernames and timestamps)
- Automatically deleting expired OAuth states
- Limiting data retention to what is necessary for transparency

## 16. Automated Decision Making

The Service uses automated processing for:
- Watchtime calculation based on chat activity
- Automatic role assignment based on thresholds
- Provably fair random selection for raffles, giveaways, and slot rewards
- Anti-farming detection
- Point calculations

These automated decisions do not have legal or significant effects on you beyond Discord server role assignments and optional reward systems.

## 17. Contact Information

For privacy-related questions, concerns, or requests:
- Contact server administrators in the Discord server where the bot is deployed
- For data deletion requests, contact an administrator with "Manage Server" permissions
- Visit the Admin Dashboard for server-specific support

---

**By using the Service, you acknowledge that you have read and understood this Privacy Policy.**
