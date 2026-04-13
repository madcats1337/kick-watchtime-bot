"""Gambling games feature - Blackjack, Roll, Double with provably fair outcomes"""

from .commands import GamblingCog


async def setup_gambling(bot, engine):
    """Setup gambling commands as a Cog"""
    cog = GamblingCog(bot, engine)
    await bot.add_cog(cog)
    print("🎰 Gambling commands registered (!bj, !roll, !double)")


__all__ = ["setup_gambling", "GamblingCog"]
