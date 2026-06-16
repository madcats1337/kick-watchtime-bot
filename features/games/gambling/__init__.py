"""Gambling games feature - Blackjack, Roll, Double with provably fair outcomes"""

import logging

from .commands import GamblingCog

logger = logging.getLogger(__name__)


async def setup_gambling(bot, engine):
    """Setup gambling commands as a Cog"""
    cog = GamblingCog(bot, engine)
    await bot.add_cog(cog)
    logger.debug("🎰 Gambling commands registered (!bj, !roll, !double)")


__all__ = ["setup_gambling", "GamblingCog"]
