"""
Raffle System Package
Monthly ticket-based raffle system with multiple earning methods
"""

__version__ = "1.0.0"

# Export main components
from .commands import RaffleCommands
from .scheduler import setup_raffle_scheduler
from .shuffle_tracker import setup_shuffle_tracker
from .tickets import TicketManager
from .draw import RaffleDraw

__all__ = [
    'RaffleCommands',
    'setup_raffle_scheduler',
    'setup_shuffle_tracker',
    'TicketManager',
    'RaffleDraw'
]
