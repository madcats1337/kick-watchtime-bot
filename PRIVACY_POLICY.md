# Privacy Policy

**Last Updated:** October 22, 2025

## 1. Introduction

This Privacy Policy explains how we collect, use, store, and protect your personal information when you use this Discord bot (the "Bot"). By using the Bot, you agree to the collection and use of information in accordance with this policy.

## 2. Information We Collect

### 2.1 Automatically Collected Information

When you use the Bot, we automatically collect:

**Discord Information:**
- Discord User ID (unique identifier)
- Discord Username
- Discord Server (Guild) ID
- Discord Role assignments
- Message timestamps (for watchtime calculation)

**Kick.com Information:**
- Kick.com username
- Kick.com User ID
- Kick.com chat messages (username and timestamps only)
- Kick.com profile information accessed via OAuth

### 2.2 Information You Provide

When you link your accounts, we collect:
- OAuth authorization tokens (encrypted and stored securely)
- Account linking timestamps
- Voluntary commands and interactions with the Bot

### 2.3 Generated Data

The Bot generates and stores:
- Watchtime statistics (minutes watched)
- Chat activity timestamps
- Leaderboard rankings
- Role assignment history
- OAuth state tokens (temporary, deleted after use)

## 3. How We Use Your Information

We use collected information for the following purposes:

**Primary Functions:**
- Link your Discord account to your Kick.com account
- Track your watchtime based on Kick.com chat activity
- Assign Discord roles based on watchtime milestones
- Display leaderboards and statistics
- Send notifications about role assignments and linking status

**Administrative Functions:**
- Prevent abuse and fraud (anti-farming measures)
- Maintain security of the Bot
- Debug and improve Bot functionality
- Comply with server administrator requests

**We DO NOT:**
- Sell your personal information to third parties
- Use your information for advertising or marketing
- Share your data with unauthorized parties
- Read or store the content of your chat messages

## 4. Data Storage and Security

### 4.1 Data Storage

- Data is stored in a secure PostgreSQL database
- Database is hosted on Railway.app or similar secure cloud platforms
- Access to the database is restricted and encrypted
- OAuth tokens are stored securely and refreshed as needed

### 4.2 Data Retention

We retain your data:
- **Linked Accounts:** Until you request unlinking or account deletion
- **Watchtime Data:** Indefinitely, unless you request deletion
- **OAuth Tokens:** Until they expire or are revoked
- **Temporary Data:** OAuth states and codes deleted within 30 minutes
- **Logs:** Link attempt logs retained for security purposes

### 4.3 Security Measures

We implement security measures including:
- Encrypted database connections
- HMAC-SHA256 signature verification for OAuth links
- Timestamp expiration for OAuth links (1-hour validity)
- PKCE (Proof Key for Code Exchange) for OAuth flow
- Limited access to administrative functions
- Regular security updates and monitoring

## 5. Data Sharing and Disclosure

### 5.1 When We Share Data

We may share your information only in the following circumstances:

**With Your Consent:**
- Publicly displayed leaderboards (Kick username and watchtime)
- Role assignments visible to server members

**Legal Requirements:**
- When required by law or legal process
- To protect the rights, property, or safety of users
- To enforce our Terms of Service

**Service Providers:**
- Discord (for bot functionality)
- Kick.com (for OAuth and chat monitoring)
- Railway.app or database hosting provider (for data storage)

### 5.2 When We DO NOT Share Data

We do not:
- Sell your data to third parties
- Share your data for marketing purposes
- Provide your data to unauthorized parties
- Share Discord User IDs publicly (except to admins)

## 6. Your Rights and Choices

### 6.1 Access and Control

You have the right to:
- **Access:** View your linked account information using `!watchtime`
- **Unlink:** Request to unlink your accounts via server administrators
- **Delete:** Request deletion of your data
- **Correct:** Update incorrect information by relinking
- **Opt-Out:** Stop using the Bot at any time

### 6.2 How to Exercise Your Rights

To exercise your rights:
- **Unlink Account:** Contact a server administrator and request `!unlink @yourusername`
- **Delete Data:** Contact a server administrator to request full data deletion
- **View Data:** Use `!watchtime` to see your stored information
- **Questions:** Contact server administrators in the Discord server

### 6.3 Data Deletion

If you request data deletion, we will remove:
- Your Discord-Kick account link
- Your watchtime statistics
- Your OAuth tokens
- Your link attempt logs

Note: Some data may be retained in backups for a limited time.

## 7. Third-Party Services

The Bot integrates with third-party services:

**Discord:**
- Privacy Policy: https://discord.com/privacy
- We use Discord's API in accordance with their Terms of Service

**Kick.com:**
- Privacy Policy: https://kick.com/privacy
- We use Kick.com's OAuth and public APIs
- We monitor public chat messages for watchtime tracking

**Railway.app (or similar hosting):**
- Provides secure database and hosting infrastructure
- Subject to their privacy policies and security measures

We are not responsible for the privacy practices of these third-party services.

## 8. Children's Privacy

The Bot is not intended for users under the age of 13 (or the minimum age required in your jurisdiction). We do not knowingly collect personal information from children. If we become aware that a child has provided us with personal information, we will take steps to delete such information.

## 9. International Data Transfers

Your data may be transferred to and stored in countries outside your country of residence. By using the Bot, you consent to such transfers. We ensure appropriate safeguards are in place to protect your data.

## 10. Cookies and Tracking

The Bot does not use cookies. However, the OAuth flow may use session tokens temporarily to complete account linking. These tokens are deleted after use.

## 11. Changes to This Privacy Policy

We may update this Privacy Policy from time to time. Changes will be posted with an updated "Last Updated" date. Your continued use of the Bot after changes constitutes acceptance of the updated Privacy Policy.

Significant changes may be announced in the Discord server.

## 12. Data Breach Notification

In the unlikely event of a data breach affecting your personal information, we will:
- Investigate the breach promptly
- Notify affected users as soon as reasonably possible
- Take steps to mitigate harm
- Report to relevant authorities if required by law

## 13. Contact Information

For privacy-related questions, concerns, or requests:
- Contact server administrators in the Discord server where the Bot is deployed
- For data deletion requests, contact an administrator with "Manage Server" permissions

## 14. Compliance

We strive to comply with applicable data protection laws, including:
- General Data Protection Regulation (GDPR) - European Union
- California Consumer Privacy Act (CCPA) - California, USA
- Other applicable regional data protection regulations

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
- Collecting only necessary information for Bot functionality
- Not storing chat message content (only usernames and timestamps)
- Automatically deleting expired OAuth states
- Limiting data retention to what is necessary

## 16. Automated Decision Making

The Bot uses automated processing for:
- Watchtime calculation based on chat activity
- Automatic role assignment based on thresholds
- Anti-farming detection

These automated decisions do not have legal or significant effects on you beyond Discord server role assignments.

## 17. Your Consent

By using the Bot, you consent to:
- Collection of information as described in this policy
- Processing of your data for Bot functionality
- Storage of your data in our secure database
- Integration with Discord and Kick.com services

---

**If you have any questions or concerns about this Privacy Policy, please contact a server administrator.**
