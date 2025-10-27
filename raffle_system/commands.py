"""
Discord Commands for Raffle System
Handles user and admin commands for raffle participation
"""

import logging
from datetime import datetime
import discord
from discord.ext import commands
from sqlalchemy import text
from .tickets import TicketManager
from .draw import RaffleDraw
from .shuffle_tracker import ShuffleWagerTracker

logger = logging.getLogger(__name__)


class RaffleCommands(commands.Cog):
    """Discord commands for raffle system"""
    
    def __init__(self, bot, engine):
        self.bot = bot
        self.engine = engine
        self.ticket_manager = TicketManager(engine)
        self.raffle_draw = RaffleDraw(engine)
        self.shuffle_tracker = ShuffleWagerTracker(engine)
    
    # ========================================
    # USER COMMANDS
    # ========================================
    
    @commands.command(name='tickets', aliases=['ticket', 'mytickets'])
    async def check_tickets(self, ctx):
        """
        Check your raffle ticket balance
        Usage: !tickets
        """
        try:
            discord_id = ctx.author.id
            tickets = self.ticket_manager.get_user_tickets(discord_id)
            
            if not tickets or tickets['total_tickets'] == 0:
                await ctx.send(f"❌ {ctx.author.mention} You don't have any raffle tickets yet!\n"
                             f"Earn tickets by:\n"
                             f"• Watching streams (10 tickets per hour)\n"
                             f"• Gifting subs (15 tickets per sub)\n"
                             f"• Wagering on Shuffle.com with code 'lele' (20 tickets per $1000)")
                return
            
            # Get user's rank
            rank = self.ticket_manager.get_user_rank(discord_id)
            stats = self.ticket_manager.get_period_stats()
            total_participants = stats['total_participants'] if stats else 0
            
            # Calculate win probability
            win_prob = self.raffle_draw.get_user_win_probability(discord_id, stats['period_id']) if stats else None
            win_prob_text = f"{win_prob['probability_percent']:.2f}%" if win_prob else "N/A"
            
            embed_text = f"""
🎫 **Raffle Tickets for {ctx.author.display_name}**

**Total Tickets**: {tickets['total_tickets']:,}
**Rank**: #{rank} of {total_participants}
**Win Probability**: {win_prob_text}

**Breakdown**:
• Watchtime: {tickets['watchtime_tickets']} tickets
• Gifted Subs: {tickets['gifted_sub_tickets']} tickets
• Shuffle Wagers: {tickets['shuffle_wager_tickets']} tickets
• Bonus: {tickets['bonus_tickets']} tickets

Use `!leaderboard` to see top participants!
            """
            
            await ctx.send(embed_text.strip())
            
        except Exception as e:
            logger.error(f"Error checking tickets: {e}")
            await ctx.send(f"❌ Error checking tickets. Please try again.")
    
    @commands.command(name='raffleboard', aliases=['raffletop', 'rafflerankings'])
    async def raffle_leaderboard(self, ctx, limit: int = 10):
        """
        View raffle ticket leaderboard
        Usage: !raffleboard [limit]
        Example: !raffleboard 20
        """
        try:
            if limit < 1 or limit > 50:
                limit = 10
            
            leaderboard = self.ticket_manager.get_leaderboard(limit=limit)
            
            if not leaderboard:
                await ctx.send("❌ No raffle participants yet!")
                return
            
            # Get period stats
            stats = self.ticket_manager.get_period_stats()
            
            response = f"🏆 **Raffle Leaderboard** (Period #{stats['period_id']})\n\n"
            response += f"**Total Tickets**: {stats['total_tickets']:,}\n"
            response += f"**Total Participants**: {stats['total_participants']}\n\n"
            
            for entry in leaderboard:
                rank = entry['rank']
                kick_name = entry['kick_name'] or 'Unknown'
                total = entry['total_tickets']
                prob = (total / stats['total_tickets']) if stats['total_tickets'] > 0 else 0
                
                medal = ""
                if rank == 1:
                    medal = "🥇"
                elif rank == 2:
                    medal = "🥈"
                elif rank == 3:
                    medal = "🥉"
                else:
                    medal = f"#{rank}"
                
                response += f"{medal} **{kick_name}**: {total:,} tickets ({prob:.2%} chance)\n"
            
            response += f"\nUse `!tickets` to check your own balance!"
            
            await ctx.send(response)
            
        except Exception as e:
            logger.error(f"Error showing leaderboard: {e}")
            await ctx.send(f"❌ Error loading leaderboard. Please try again.")
    
    @commands.command(name='raffleinfo', aliases=['raffle'])
    async def raffle_info(self, ctx):
        """
        View current raffle period information
        Usage: !raffleinfo
        """
        try:
            stats = self.ticket_manager.get_period_stats()
            
            if not stats:
                await ctx.send("❌ No active raffle period!")
                return
            
            # Get draw history
            history = self.raffle_draw.get_draw_history(limit=1)
            last_winner = history[0] if history else None
            
            response = f"""
🎰 **Current Raffle Information**

**Period**: #{stats['period_id']}
**Started**: {stats['start_date'].strftime('%B %d, %Y')}
**Ends**: {stats['end_date'].strftime('%B %d, %Y')}
**Status**: {stats['status'].upper()}

**Statistics**:
• Total Tickets: {stats['total_tickets']:,}
• Total Participants: {stats['total_participants']}

**How to Earn Tickets**:
• Watch streams: 10 tickets per hour
• Gift subs: 15 tickets per sub
• Wager on Shuffle.com (code 'lele'): 20 tickets per $1000

**Commands**:
• `!tickets` - Check your ticket balance
• `!raffleboard` - View top participants
• `!linkshuffle <username>` - Link your Shuffle account
            """
            
            if last_winner:
                response += f"\n**Last Winner**: {last_winner['winner_kick_name']} ({last_winner['total_tickets']:,} tickets, {last_winner['win_probability']:.2%} chance)"
            
            await ctx.send(response.strip())
            
        except Exception as e:
            logger.error(f"Error showing raffle info: {e}")
            await ctx.send(f"❌ Error loading raffle info. Please try again.")
    
    @commands.command(name='linkshuffle')
    async def link_shuffle(self, ctx, shuffle_username: str = None):
        """
        Link your Shuffle.com account to earn tickets from wagers
        Usage: !linkshuffle <shuffle_username>
        Example: !linkshuffle CryptoKing420
        """
        try:
            if not shuffle_username:
                await ctx.send(f"❌ {ctx.author.mention} Please provide your Shuffle username!\n"
                             f"Usage: `!linkshuffle <your_shuffle_username>`\n"
                             f"Example: `!linkshuffle CryptoKing420`")
                return
            
            discord_id = ctx.author.id
            
            # Get Kick name from links table
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT kick_name FROM links WHERE discord_id = :discord_id
                """), {'discord_id': discord_id})
                
                row = result.fetchone()
                if not row:
                    await ctx.send(f"❌ {ctx.author.mention} You must link your Kick account first!\n"
                                 f"Ask an admin to link your Discord to your Kick account.")
                    return
                
                kick_name = row[0]
            
            # Attempt to link
            result = self.shuffle_tracker.link_shuffle_account(
                shuffle_username=shuffle_username,
                kick_name=kick_name,
                discord_id=discord_id,
                verified=False  # Requires admin verification
            )
            
            if result['status'] == 'success':
                await ctx.send(f"✅ {ctx.author.mention} Link request created!\n"
                             f"**Shuffle**: {shuffle_username} → **Kick**: {kick_name}\n\n"
                             f"⏳ **Pending admin verification**\n"
                             f"An admin will review your request. Once verified, your Shuffle wagers "
                             f"under code 'lele' will earn raffle tickets!")
                
                # Notify admins (optional - send to admin channel)
                logger.info(f"🔗 New Shuffle link request: {shuffle_username} → {kick_name} (Discord: {discord_id})")
                
            elif result['status'] == 'already_linked':
                await ctx.send(f"❌ {ctx.author.mention} Shuffle username '{shuffle_username}' is already linked to "
                             f"{result['existing_kick_name']}!")
                
            elif result['status'] == 'discord_already_linked':
                await ctx.send(f"❌ {ctx.author.mention} You already have a Shuffle account linked: "
                             f"{result['existing_shuffle_username']}\n"
                             f"Contact an admin if you need to change it.")
            else:
                await ctx.send(f"❌ Error creating link request: {result.get('error', 'Unknown error')}")
            
        except Exception as e:
            logger.error(f"Error linking Shuffle account: {e}")
            await ctx.send(f"❌ Error processing link request. Please try again.")
    
    # ========================================
    # ADMIN COMMANDS
    # ========================================
    
    @commands.command(name='verifyshuffle', aliases=['shuffleverify', 'raffleverify'])
    @commands.has_permissions(administrator=True)
    async def verify_shuffle_link(self, ctx, user: commands.UserConverter, shuffle_username: str):
        """
        [ADMIN] Verify a Shuffle account link
        Usage: !verifyshuffle @user <shuffle_username>
        Example: !verifyshuffle @John CryptoKing420
        """
        try:
            discord_id = user.id
            admin_id = ctx.author.id
            
            # Check if link exists and is unverified
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT verified FROM raffle_shuffle_links
                    WHERE discord_id = :discord_id AND shuffle_username = :username
                """), {'discord_id': discord_id, 'username': shuffle_username})
                
                row = result.fetchone()
                
                if not row:
                    await ctx.send(f"❌ No link request found for {user.mention} with Shuffle username '{shuffle_username}'")
                    return
                
                if row[0]:  # already verified
                    await ctx.send(f"ℹ️ This link is already verified!")
                    return
                
                # Get kick name from links table
                link_result = conn.execute(text("""
                    SELECT kick_name FROM links WHERE discord_id = :discord_id
                """), {'discord_id': discord_id})
                
                link_row = link_result.fetchone()
                if not link_row:
                    await ctx.send(f"❌ {user.mention} must link their Kick account first! Use `!link`")
                    return
                
                kick_name = link_row[0]
                
                # Get current period info
                period_result = conn.execute(text("""
                    SELECT id, start_date FROM raffle_periods WHERE status = 'active'
                """))
                period_row = period_result.fetchone()
                
                if not period_row:
                    await ctx.send(f"❌ No active raffle period!")
                    return
                
                period_id = period_row[0]
                period_start = period_row[1]
                
                # Verify the link
                conn.execute(text("""
                    UPDATE raffle_shuffle_links
                    SET 
                        verified = TRUE,
                        verified_by_discord_id = :admin_id,
                        verified_at = CURRENT_TIMESTAMP,
                        kick_name = :kick_name
                    WHERE discord_id = :discord_id AND shuffle_username = :username
                """), {
                    'admin_id': admin_id,
                    'discord_id': discord_id,
                    'username': shuffle_username,
                    'kick_name': kick_name
                })
                
                # Check if user has wager tracking for current period
                wager_result = conn.execute(text("""
                    SELECT total_wager_usd, created_at
                    FROM raffle_shuffle_wagers
                    WHERE shuffle_username = :username AND period_id = :period_id
                """), {
                    'username': shuffle_username,
                    'period_id': period_id
                })
                
                wager_row = wager_result.fetchone()
                tickets_awarded = 0
                
                if wager_row:
                    total_wager = wager_row[0]
                    wager_created = wager_row[1]
                    
                    # If wager tracking was created AFTER period started, award tickets for the wager
                    if wager_created >= period_start and total_wager > 0:
                        from .config import SHUFFLE_TICKETS_PER_1000_USD
                        tickets_awarded = int((total_wager / 1000.0) * SHUFFLE_TICKETS_PER_1000_USD)
                        
                        if tickets_awarded > 0:
                            # Award the tickets
                            success = self.ticket_manager.award_tickets(
                                discord_id=discord_id,
                                kick_name=kick_name,
                                tickets=tickets_awarded,
                                source='shuffle_wager',
                                description=f"Shuffle wagers during period (pre-verification): ${total_wager:.2f}",
                                period_id=period_id
                            )
                            
                            if success:
                                # Update wager tracking
                                conn.execute(text("""
                                    UPDATE raffle_shuffle_wagers
                                    SET 
                                        discord_id = :discord_id,
                                        kick_name = :kick_name,
                                        last_known_wager = total_wager_usd,
                                        tickets_awarded = :tickets
                                    WHERE shuffle_username = :username AND period_id = :period_id
                                """), {
                                    'discord_id': discord_id,
                                    'kick_name': kick_name,
                                    'tickets': tickets_awarded,
                                    'username': shuffle_username,
                                    'period_id': period_id
                                })
                                
                                logger.info(f"💰 Awarded {tickets_awarded} tickets for pre-verification wagers: {shuffle_username} (${total_wager:.2f})")
                    else:
                        # Wagers were from previous period, don't award tickets
                        conn.execute(text("""
                            UPDATE raffle_shuffle_wagers
                            SET 
                                discord_id = :discord_id,
                                kick_name = :kick_name,
                                last_known_wager = total_wager_usd
                            WHERE shuffle_username = :username AND period_id = :period_id
                        """), {
                            'discord_id': discord_id,
                            'kick_name': kick_name,
                            'username': shuffle_username,
                            'period_id': period_id
                        })
            
            if tickets_awarded > 0:
                await ctx.send(f"✅ **Verified!** {user.mention}'s Shuffle account '{shuffle_username}' is now linked.\n"
                             f"🎟️ **Awarded {tickets_awarded:,} tickets** for ${wager_row[0]:.2f} wagered this period!\n"
                             f"Future wagers under code 'lele' will continue earning tickets.")
            else:
                await ctx.send(f"✅ **Verified!** {user.mention}'s Shuffle account '{shuffle_username}' is now linked.\n"
                             f"Future wagers under code 'lele' will earn raffle tickets!")
            
            logger.info(f"✅ Admin {ctx.author} verified Shuffle link: {shuffle_username} → {kick_name} (Discord {discord_id}) - {tickets_awarded} tickets awarded")
            
        except commands.BadArgument:
            await ctx.send(f"❌ Invalid user mention. Usage: `!verifyshuffle @user <shuffle_username>`")
        except Exception as e:
            logger.error(f"Error verifying Shuffle link: {e}")
            await ctx.send(f"❌ Error verifying link. Please try again.")
    
    @commands.command(name='rafflegive')
    @commands.has_permissions(administrator=True)
    async def give_tickets(self, ctx, user: commands.UserConverter, tickets: int, *, reason: str = "Admin bonus"):
        """
        [ADMIN] Manually award tickets to a user
        Usage: !rafflegive @user <tickets> [reason]
        Example: !rafflegive @John 100 Event participation bonus
        """
        try:
            if tickets <= 0:
                await ctx.send(f"❌ Ticket amount must be positive!")
                return
            
            discord_id = user.id
            
            # Get kick name
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT kick_name FROM links WHERE discord_id = :discord_id
                """), {'discord_id': discord_id})
                
                row = result.fetchone()
                if not row:
                    await ctx.send(f"❌ {user.mention} is not linked to a Kick account!")
                    return
                
                kick_name = row[0]
            
            # Award tickets
            success = self.ticket_manager.award_tickets(
                discord_id=discord_id,
                kick_name=kick_name,
                tickets=tickets,
                source='bonus',
                description=f"Manual award by {ctx.author.name}: {reason}"
            )
            
            if success:
                await ctx.send(f"✅ Awarded **{tickets:,} tickets** to {user.mention}!\n"
                             f"Reason: {reason}")
                logger.info(f"🎁 Admin {ctx.author} awarded {tickets} tickets to {user} ({kick_name}): {reason}")
            else:
                await ctx.send(f"❌ Failed to award tickets. Check logs for details.")
            
        except commands.BadArgument:
            await ctx.send(f"❌ Invalid user or ticket amount. Usage: `!rafflegive @user <tickets> [reason]`")
        except Exception as e:
            logger.error(f"Error giving tickets: {e}")
            await ctx.send(f"❌ Error awarding tickets. Please try again.")
    
    @commands.command(name='raffleremove')
    @commands.has_permissions(administrator=True)
    async def remove_tickets(self, ctx, user: commands.UserConverter, tickets: int, *, reason: str = "Admin removal"):
        """
        [ADMIN] Remove tickets from a user
        Usage: !raffleremove @user <tickets> [reason]
        Example: !raffleremove @John 50 Rule violation
        """
        try:
            if tickets <= 0:
                await ctx.send(f"❌ Ticket amount must be positive!")
                return
            
            discord_id = user.id
            
            # Get kick name
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT kick_name FROM links WHERE discord_id = :discord_id
                """), {'discord_id': discord_id})
                
                row = result.fetchone()
                if not row:
                    await ctx.send(f"❌ {user.mention} is not linked to a Kick account!")
                    return
                
                kick_name = row[0]
            
            # Remove tickets
            success = self.ticket_manager.remove_tickets(
                discord_id=discord_id,
                kick_name=kick_name,
                tickets=tickets,
                reason=reason
            )
            
            if success:
                await ctx.send(f"✅ Removed **{tickets:,} tickets** from {user.mention}!\n"
                             f"Reason: {reason}")
                logger.info(f"🗑️ Admin {ctx.author} removed {tickets} tickets from {user} ({kick_name}): {reason}")
            else:
                await ctx.send(f"❌ Failed to remove tickets. User may not have enough tickets.")
            
        except commands.BadArgument:
            await ctx.send(f"❌ Invalid user or ticket amount. Usage: `!raffleremove @user <tickets> [reason]`")
        except Exception as e:
            logger.error(f"Error removing tickets: {e}")
            await ctx.send(f"❌ Error removing tickets. Please try again.")
    
    @commands.command(name='raffledraw')
    @commands.has_permissions(administrator=True)
    async def draw_winner(self, ctx, *, prize_description: str = "Monthly Raffle Prize"):
        """
        [ADMIN] Draw a raffle winner
        Usage: !raffledraw [prize description]
        Example: !raffledraw $500 Cash Prize
        """
        try:
            admin_id = ctx.author.id
            
            # Get current period stats
            stats = self.ticket_manager.get_period_stats()
            
            if not stats or stats['total_tickets'] == 0:
                await ctx.send(f"❌ Cannot draw winner: No tickets in current raffle period!")
                return
            
            # Check if already drawn
            with self.engine.begin() as conn:
                existing = conn.execute(text("""
                    SELECT winner_kick_name FROM raffle_draws
                    WHERE period_id = :period_id
                """), {'period_id': stats['period_id']})
                
                if existing.fetchone():
                    await ctx.send(f"❌ A winner has already been drawn for this period!")
                    return
            
            # Confirmation message
            await ctx.send(f"🎲 **Drawing raffle winner...**\n"
                         f"Period: #{stats['period_id']}\n"
                         f"Total Tickets: {stats['total_tickets']:,}\n"
                         f"Total Participants: {stats['total_participants']}\n"
                         f"Prize: {prize_description}")
            
            # Draw winner
            result = self.raffle_draw.draw_winner(
                period_id=stats['period_id'],
                prize_description=prize_description,
                drawn_by_discord_id=admin_id
            )
            
            if result:
                # Get Discord user object if possible
                try:
                    discord_user = await self.bot.fetch_user(result['winner_discord_id'])
                    mention = discord_user.mention
                except:
                    mention = f"Discord ID: {result['winner_discord_id']}"
                
                # Get full ticket breakdown
                winner_tickets = self.ticket_manager.get_user_tickets(result['winner_discord_id'])
                
                await ctx.send(f"""
🎉 **RAFFLE WINNER DRAWN!** 🎉

**Winner**: {result['winner_kick_name']} ({mention})
**Tickets**: {result['winner_tickets']:,} out of {result['total_tickets']:,}
**Win Probability**: {result['win_probability']:.2f}%
**Prize**: {prize_description}

**Breakdown**:
• Watchtime: {winner_tickets.get('watchtime_tickets', 0)} tickets
• Gifted Subs: {winner_tickets.get('gifted_sub_tickets', 0)} tickets
• Shuffle Wagers: {winner_tickets.get('shuffle_wager_tickets', 0)} tickets
• Bonus: {winner_tickets.get('bonus_tickets', 0)} tickets

Congratulations! 🎊
                """.strip())
                
                logger.info(f"🎉 Raffle winner drawn: {result['winner_kick_name']} (Period #{stats['period_id']})")
                
            else:
                await ctx.send(f"❌ Error drawing winner: No participants or unexpected error")
            
        except Exception as e:
            logger.error(f"Error drawing raffle winner: {e}")
            import traceback
            traceback.print_exc()
            await ctx.send(f"❌ Error drawing winner. Please try again.")
    
    @commands.command(name='rafflestats')
    @commands.has_permissions(administrator=True)
    async def raffle_stats(self, ctx, user: discord.Member = None):
        """
        [ADMIN] View detailed raffle statistics
        Usage: !rafflestats [@user]
        """
        try:
            if user:
                # Show user-specific stats
                discord_id = user.id
                tickets = self.ticket_manager.get_user_tickets(discord_id)
                
                if not tickets:
                    await ctx.send(f"❌ {user.mention} has no raffle tickets!")
                    return
                
                # Get rank
                rank = self.ticket_manager.get_user_rank(discord_id)
                stats = self.ticket_manager.get_period_stats()
                
                # Get detailed breakdown from tables
                with self.engine.begin() as conn:
                    # Watchtime stats
                    watchtime_result = conn.execute(text("""
                        SELECT SUM(minutes_converted), SUM(tickets_awarded)
                        FROM raffle_watchtime_converted
                        WHERE kick_name = :kick_name
                    """), {'kick_name': tickets['kick_name']})
                    wt_row = watchtime_result.fetchone()
                    total_minutes = wt_row[0] or 0
                    
                    # Gifted sub stats
                    subs_result = conn.execute(text("""
                        SELECT COUNT(*), SUM(sub_count), SUM(tickets_awarded)
                        FROM raffle_gifted_subs
                        WHERE gifter_kick_name = :kick_name
                    """), {'kick_name': tickets['kick_name']})
                    subs_row = subs_result.fetchone()
                    gift_events = subs_row[0] or 0
                    total_subs = subs_row[1] or 0
                    
                    # Shuffle stats
                    shuffle_result = conn.execute(text("""
                        SELECT total_wager_usd, tickets_awarded
                        FROM raffle_shuffle_wagers
                        WHERE discord_id = :discord_id
                    """), {'discord_id': discord_id})
                    shuffle_row = shuffle_result.fetchone()
                    total_wager = shuffle_row[0] if shuffle_row else 0
                
                # Get win probability
                win_prob = self.raffle_draw.get_user_win_probability(discord_id, stats['period_id'])
                win_prob_text = f"{win_prob['probability_percent']:.2f}%" if win_prob else "N/A"
                    
                response = f"""
📊 **Detailed Stats for {user.display_name}**

**Rank**: #{rank} of {stats['total_participants']}
**Total Tickets**: {tickets['total_tickets']:,}
**Win Probability**: {win_prob_text}

**Watchtime**: {tickets['watchtime_tickets']} tickets
• Total watch time: {total_minutes/60:.1f} hours

**Gifted Subs**: {tickets['gifted_sub_tickets']} tickets
• Gift events: {gift_events}
• Total subs gifted: {total_subs}

**Shuffle Wagers**: {tickets['shuffle_wager_tickets']} tickets
• Total wagered: ${total_wager:.2f}

**Bonus**: {tickets['bonus_tickets']} tickets
                """
                
                await ctx.send(response.strip())
                
            else:
                # Show overall stats
                stats = self.ticket_manager.get_period_stats()
                
                response = f"""
📊 **Overall Raffle Statistics**

**Period**: #{stats['period_id']}
**Duration**: {stats['start_date'].strftime('%b %d')} - {stats['end_date'].strftime('%b %d, %Y')}
**Status**: {stats['status'].upper()}

**Participation**:
• Total Tickets: {stats['total_tickets']:,}
• Total Participants: {stats['total_participants']}
• Average per participant: {stats['total_tickets'] / max(stats['total_participants'], 1):.1f} tickets

Use `!rafflestats @user` to see individual stats
                """
                
                await ctx.send(response.strip())
            
        except commands.BadArgument:
            await ctx.send(f"❌ Invalid user mention.")
        except Exception as e:
            logger.error(f"Error showing raffle stats: {e}")
            await ctx.send(f"❌ Error loading stats. Please try again.")
    
    # ========================================
    # PERIOD MANAGEMENT COMMANDS
    # ========================================
    
    @commands.command(name='raffleend', aliases=['endraffle'])
    @commands.has_permissions(administrator=True)
    async def end_raffle(self, ctx):
        """
        [ADMIN] End the current raffle period
        Usage: !raffleend
        """
        try:
            with self.engine.begin() as conn:
                # Get current period
                result = conn.execute(text("""
                    SELECT id, start_date, end_date, status
                    FROM raffle_periods
                    WHERE status = 'active'
                    ORDER BY start_date DESC
                    LIMIT 1
                """))
                period = result.fetchone()
                
                if not period:
                    await ctx.send("❌ No active raffle period to end!")
                    return
                
                # End the period
                conn.execute(text("""
                    UPDATE raffle_periods
                    SET status = 'ended', end_date = CURRENT_TIMESTAMP
                    WHERE id = :period_id
                """), {'period_id': period[0]})
                
                await ctx.send(f"✅ Raffle period #{period[0]} has been ended.\n"
                             f"Use `!raffledraw` to select a winner, then `!rafflestart` to begin a new period.")
            
        except Exception as e:
            logger.error(f"Error ending raffle period: {e}")
            await ctx.send(f"❌ Error ending raffle period: {str(e)}")
    
    @commands.command(name='rafflestart', aliases=['newraffle'])
    @commands.has_permissions(administrator=True)
    async def start_raffle(self, ctx, start_day: int = None, end_day: int = None):
        """
        [ADMIN] Start a new raffle period
        Usage: !rafflestart [start_day] [end_day]
        Example: !rafflestart 1 30  (1st to 30th of current month)
        If no dates provided, uses current month (1st to last day)
        """
        try:
            from datetime import datetime
            from dateutil.relativedelta import relativedelta
            
            # Check if there's already an active period
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT id FROM raffle_periods
                    WHERE status = 'active'
                    LIMIT 1
                """))
                if result.fetchone():
                    await ctx.send("❌ There's already an active raffle period! Use `!raffleend` first.")
                    return
                
                # Calculate dates
                now = datetime.now()
                
                if start_day and end_day:
                    start = now.replace(day=start_day, hour=0, minute=0, second=0, microsecond=0)
                    end = now.replace(day=end_day, hour=23, minute=59, second=59, microsecond=0)
                else:
                    # Default: current month
                    start = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                    next_month = start + relativedelta(months=1)
                    end = next_month - relativedelta(seconds=1)
                
                # Create new period
                result = conn.execute(text("""
                    INSERT INTO raffle_periods (start_date, end_date, status)
                    VALUES (:start, :end, 'active')
                    RETURNING id
                """), {'start': start, 'end': end})
                period_id = result.fetchone()[0]
                
                await ctx.send(f"✅ New raffle period #{period_id} started!\n"
                             f"**Duration**: {start.strftime('%b %d, %Y')} - {end.strftime('%b %d, %Y')}\n"
                             f"Users can now earn tickets!")
            
        except Exception as e:
            logger.error(f"Error starting raffle period: {e}")
            await ctx.send(f"❌ Error starting raffle period: {str(e)}")
    
    @commands.command(name='rafflerestart', aliases=['resetraffle'])
    @commands.has_permissions(administrator=True)
    async def restart_raffle(self, ctx):
        """
        [ADMIN] End current period and immediately start a new one for next month
        Usage: !rafflerestart
        """
        try:
            from datetime import datetime
            from dateutil.relativedelta import relativedelta
            
            with self.engine.begin() as conn:
                # Get current period
                result = conn.execute(text("""
                    SELECT id, total_tickets
                    FROM raffle_periods
                    WHERE status = 'active'
                    ORDER BY start_date DESC
                    LIMIT 1
                """))
                current_period = result.fetchone()
                
                if current_period:
                    # End current period
                    conn.execute(text("""
                        UPDATE raffle_periods
                        SET status = 'ended', end_date = CURRENT_TIMESTAMP
                        WHERE id = :period_id
                    """), {'period_id': current_period[0]})
                    
                    old_tickets = current_period[1]
                else:
                    old_tickets = 0
                
                # Create new period for next month
                now = datetime.now()
                next_month = now + relativedelta(months=1)
                start = next_month.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
                end = (start + relativedelta(months=1)) - relativedelta(seconds=1)
                
                result = conn.execute(text("""
                    INSERT INTO raffle_periods (start_date, end_date, status)
                    VALUES (:start, :end, 'active')
                    RETURNING id
                """), {'start': start, 'end': end})
                new_period_id = result.fetchone()[0]
                
                await ctx.send(f"✅ Raffle reset complete!\n\n"
                             f"**Old Period**: Ended with {old_tickets:,} total tickets\n"
                             f"**New Period #{new_period_id}**: {start.strftime('%b %d, %Y')} - {end.strftime('%b %d, %Y')}\n\n"
                             f"💡 Don't forget to draw a winner from the old period: `!raffledraw`")
            
        except Exception as e:
            logger.error(f"Error restarting raffle: {e}")
            await ctx.send(f"❌ Error restarting raffle: {str(e)}")
    
    @commands.command(name='rafflesetdate', aliases=['raffledates'])
    @commands.has_permissions(administrator=True)
    async def set_raffle_dates(self, ctx, start_date: str, end_date: str):
        """
        [ADMIN] Update the current raffle period dates
        Usage: !rafflesetdate YYYY-MM-DD YYYY-MM-DD
        Example: !rafflesetdate 2025-11-01 2025-11-30
        """
        try:
            from datetime import datetime
            
            # Parse dates
            try:
                start = datetime.strptime(start_date, '%Y-%m-%d')
                end = datetime.strptime(end_date, '%Y-%m-%d').replace(hour=23, minute=59, second=59)
            except ValueError:
                await ctx.send("❌ Invalid date format! Use YYYY-MM-DD (e.g., 2025-11-01)")
                return
            
            if start >= end:
                await ctx.send("❌ Start date must be before end date!")
                return
            
            with self.engine.begin() as conn:
                # Get current active period
                result = conn.execute(text("""
                    SELECT id FROM raffle_periods
                    WHERE status = 'active'
                    ORDER BY start_date DESC
                    LIMIT 1
                """))
                period = result.fetchone()
                
                if not period:
                    await ctx.send("❌ No active raffle period! Use `!rafflestart` to create one.")
                    return
                
                # Update dates
                conn.execute(text("""
                    UPDATE raffle_periods
                    SET start_date = :start, end_date = :end
                    WHERE id = :period_id
                """), {'start': start, 'end': end, 'period_id': period[0]})
                
                await ctx.send(f"✅ Raffle period #{period[0]} dates updated!\n"
                             f"**New Duration**: {start.strftime('%b %d, %Y')} - {end.strftime('%b %d, %Y')}")
            
        except Exception as e:
            logger.error(f"Error setting raffle dates: {e}")
            await ctx.send(f"❌ Error updating dates: {str(e)}")
    
    @commands.command(name='shuffledebug')
    @commands.has_permissions(administrator=True)
    async def shuffle_debug(self, ctx):
        """
        [ADMIN] Debug Shuffle wager tracking
        Usage: !shuffledebug
        """
        try:
            await ctx.send("🔍 Fetching Shuffle affiliate data...")
            
            # Fetch raw data
            import aiohttp
            from .config import SHUFFLE_AFFILIATE_URL, SHUFFLE_CAMPAIGN_CODE
            
            async with aiohttp.ClientSession() as session:
                async with session.get(SHUFFLE_AFFILIATE_URL, timeout=30) as response:
                    if response.status != 200:
                        await ctx.send(f"❌ API returned status {response.status}")
                        return
                    
                    data = await response.json()
                    
                    if not isinstance(data, list):
                        await ctx.send(f"❌ Unexpected data format: {type(data)}")
                        return
                    
                    # Show total users
                    await ctx.send(f"📊 Total users in affiliate data: {len(data)}")
                    
                    # Show all campaign codes found
                    campaign_codes = set(user.get('campaignCode', 'NONE') for user in data)
                    await ctx.send(f"📋 Campaign codes found: {', '.join(sorted(campaign_codes))}")
                    
                    # Filter for our campaign code
                    filtered = [
                        user for user in data 
                        if user.get('campaignCode', '').lower() == SHUFFLE_CAMPAIGN_CODE.lower()
                    ]
                    
                    await ctx.send(f"🎯 Users with code '{SHUFFLE_CAMPAIGN_CODE}': {len(filtered)}")
                    
                    # Show first 5 users with the code
                    if filtered:
                        response_text = "**Sample users:**\n"
                        for user in filtered[:5]:
                            username = user.get('username', 'Unknown')
                            wager = user.get('wagerAmount', 0)
                            code = user.get('campaignCode', 'NONE')
                            response_text += f"• {username}: ${wager:.2f} (code: {code})\n"
                        
                        await ctx.send(response_text)
                    
                    # Check database tracking
                    with self.engine.begin() as conn:
                        result = conn.execute(text("""
                            SELECT shuffle_username, total_wager_usd, last_known_wager, 
                                   tickets_awarded, kick_name, discord_id
                            FROM raffle_shuffle_wagers
                            WHERE period_id = (SELECT id FROM raffle_periods WHERE status = 'active')
                            ORDER BY total_wager_usd DESC
                            LIMIT 5
                        """))
                        
                        rows = result.fetchall()
                        if rows:
                            db_text = "**Database tracking:**\n"
                            for row in rows:
                                db_text += f"• {row[0]}: ${row[1]:.2f} (last: ${row[2]:.2f}, tickets: {row[3]}, linked: {'Yes' if row[4] else 'No'})\n"
                            await ctx.send(db_text)
                        else:
                            await ctx.send("No Shuffle wagers tracked in database yet")
                    
        except Exception as e:
            logger.error(f"Shuffle debug error: {e}")
            import traceback
            traceback.print_exc()
            await ctx.send(f"❌ Error: {str(e)}")
    
    @commands.command(name='shuffleunlinked')
    @commands.has_permissions(administrator=True)
    async def shuffle_unlinked(self, ctx, limit: int = 20):
        """
        [ADMIN] Show unlinked Shuffle accounts with wagers
        Usage: !shuffleunlinked [limit]
        """
        try:
            with self.engine.begin() as conn:
                result = conn.execute(text("""
                    SELECT shuffle_username, total_wager_usd, last_checked
                    FROM raffle_shuffle_wagers
                    WHERE period_id = (SELECT id FROM raffle_periods WHERE status = 'active')
                      AND (discord_id IS NULL OR kick_name IS NULL)
                      AND total_wager_usd > 0
                    ORDER BY total_wager_usd DESC
                    LIMIT :limit
                """), {'limit': limit})
                
                rows = result.fetchall()
                
                if not rows:
                    await ctx.send("✅ All Shuffle users with wagers are linked!")
                    return
                
                response = f"**Unlinked Shuffle Accounts ({len(rows)}):**\n\n"
                response += "These users have wagers but need to link their accounts:\n\n"
                
                for row in rows:
                    username = row[0]
                    wager = row[1]
                    last_check = row[2].strftime('%Y-%m-%d %H:%M') if row[2] else 'Never'
                    response += f"• **{username}**: ${wager:,.2f} wagered (last checked: {last_check})\n"
                
                response += f"\n**To link:** Users run `!linkshuffle <username>`, then you verify with `!verifyshuffle @user <username>`"
                
                await ctx.send(response)
                
        except Exception as e:
            logger.error(f"Error showing unlinked Shuffle users: {e}")
            await ctx.send(f"❌ Error: {str(e)}")


async def setup(bot, engine):
    """Add raffle commands to bot"""
    await bot.add_cog(RaffleCommands(bot, engine))
    logger.info("✅ Raffle commands loaded")


