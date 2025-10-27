"""
Raffle System Configuration
All configurable parameters for the raffle system
"""

# Ticket conversion rates
WATCHTIME_TICKETS_PER_HOUR = 10      # 1 hour of watchtime = 10 tickets
GIFTED_SUB_TICKETS = 15              # 1 gifted sub = 15 tickets
SHUFFLE_TICKETS_PER_1000_USD = 20    # $1000 wagered = 20 tickets

# Update intervals (in seconds)
WATCHTIME_CONVERSION_INTERVAL = 3600  # 1 hour
SHUFFLE_CHECK_INTERVAL = 900          # 15 minutes

# Shuffle.com configuration
SHUFFLE_AFFILIATE_URL = "https://affiliate.shuffle.com/stats/1755f751-33a9-4532-804e-b14b5c90236b"
SHUFFLE_CAMPAIGN_CODE = "lele"

# Monthly reset configuration
RESET_DAY_OF_MONTH = 1  # 1st day of the month
RESET_HOUR_UTC = 0      # 00:00 UTC

# Raffle settings
MINIMUM_TICKETS_TO_ENTER = 1
AUTO_DRAW_ON_RESET = False  # Manual draw by admin (set True for automatic)

# Notifications
TICKET_NOTIFICATION_THRESHOLD = 20     # Only notify for 20+ tickets earned at once
ENABLE_TICKET_NOTIFICATIONS = True

# Security & Anti-cheat
LINK_SHUFFLE_COOLDOWN = 86400  # 24 hours between Shuffle link attempts
MAX_SHUFFLE_LINKS_PER_USER = 1  # One Shuffle account per Discord user
REQUIRE_SHUFFLE_VERIFICATION = True  # Require admin verification for Shuffle links

# Leaderboard settings
DEFAULT_LEADERBOARD_SIZE = 10
MAX_LEADERBOARD_SIZE = 25
AUTO_LEADERBOARD_UPDATE_INTERVAL = 3600  # 1 hour in seconds

