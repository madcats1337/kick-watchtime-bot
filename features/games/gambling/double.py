"""
Double game logic.
20% chance to double the bet amount, 80% chance to lose it all.
Uses provably fair: win if random_value < 20.0
"""

from typing import Tuple

WIN_CHANCE = 20.0  # percent
WIN_MULTIPLIER = 2.0


def resolve_double(random_value: float) -> Tuple[bool, float]:
    """
    Resolve a double game.

    Args:
        random_value: Provably fair value (0.00-99.99)

    Returns:
        (won, multiplier) - won is True if random_value < WIN_CHANCE
    """
    won = random_value < WIN_CHANCE
    multiplier = WIN_MULTIPLIER if won else 0.0
    return won, multiplier


def calculate_double_payout(bet: int, random_value: float) -> Tuple[int, bool]:
    """
    Calculate the payout for a double game.

    Returns:
        (payout, won)
    """
    won, multiplier = resolve_double(random_value)
    payout = int(bet * multiplier)
    return payout, won
