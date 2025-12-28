"""
Discord Command for Webhook Setup
Allows admins to trigger webhook setup via Discord command
"""

import logging
import asyncio
from discord.ext import commands
from setup_webhooks import setup_webhooks_for_server

logger = logging.getLogger(__name__)

class WebhookSetupCommands(commands.Cog):
    """Admin commands for webhook management"""

    def __init__(self, bot):
        self.bot = bot
    
    @commands.command(name='setup-webhooks')
    @commands.has_permissions(administrator=True)
    async def setup_webhooks(self, ctx):
        """
        Setup Kick webhooks for this server (Admin only)
        
        This will:
        - Refresh OAuth tokens
        - Delete old webhooks
        - Register new webhooks with secure secrets
        - Enable real-time Kick events
        
        Usage: !setup-webhooks
        """
        logger.info(f"[WEBHOOKS] Setup command called by {ctx.author} in guild {ctx.guild.name}")
        
        discord_server_id = str(ctx.guild.id)
        
        # Send initial message
        msg = await ctx.send("🔧 **Setting up Kick webhooks...**\nThis may take a moment.")
        
        try:
            # Run the webhook setup
            success = await setup_webhooks_for_server(discord_server_id)
            
            if success:
                await msg.edit(content=f"""✅ **Webhook Setup Complete!**

**Registered Events:**
• `livestream.status.updated` - Stream on/off notifications
• `channel.subscription.new` - New subscriber tracking
• `channel.subscription.gifts` - Gifted sub tracking (auto-adds to raffle)
• `channel.subscription.renewal` - Subscription renewals

**Webhook URL:** `https://bot.lelebot.xyz/webhooks/kick`

Your bot will now receive real-time Kick events with secure signature verification! 🎉""")
            else:
                await msg.edit(content=f"""❌ **Webhook Setup Failed**

Could not setup webhooks for this server. This usually means:
• OAuth linking not completed (use `/link` command first)
• Missing Kick tokens in database
• API connection issues

Check the logs for more details.""")
        
        except Exception as e:
            logger.error(f"[WEBHOOKS] Setup failed: {e}", exc_info=True)
            await msg.edit(content=f"""❌ **Webhook Setup Error**

An error occurred: `{str(e)}`

Please check the bot logs for more information.""")
    
    @setup_webhooks.error
    async def setup_webhooks_error(self, ctx, error):
        """Error handler for setup-webhooks command"""
        if isinstance(error, commands.MissingPermissions):
            await ctx.send("❌ You need **Administrator** permissions to setup webhooks.")
        else:
            logger.error(f"[WEBHOOKS] Command error: {error}", exc_info=True)
            await ctx.send(f"❌ An error occurred: {str(error)}")


async def setup(bot):
    """Setup function for loading the cog"""
    await bot.add_cog(WebhookSetupCommands(bot))
