"""
Blackjack game logic.
Standard rules: dealer stands on 17, BJ pays 3:2, split on pairs,
double on any two cards, no insurance/surrender, split aces get one card each.
"""

from typing import List, Tuple

# Card suits and rank names for display
SUIT_EMOJIS = ["♠️", "♥️", "♦️", "♣️"]
RANK_NAMES = ["A", "2", "3", "4", "5", "6", "7", "8", "9", "10", "J", "Q", "K"]


def card_rank(card_index: int) -> int:
    """Get rank index (0=Ace, 1=Two, ..., 12=King) from deck index."""
    return card_index // 4


def card_suit(card_index: int) -> int:
    """Get suit index (0-3) from deck index."""
    return card_index % 4


def card_name(card_index: int) -> str:
    """Get display name like 'A♠️', '10♥️', 'K♦️'."""
    return f"{RANK_NAMES[card_rank(card_index)]}{SUIT_EMOJIS[card_suit(card_index)]}"


def card_value(card_index: int) -> int:
    """Get point value of a card. Ace=11, face cards=10, others=face value."""
    rank = card_rank(card_index)
    if rank == 0:  # Ace
        return 11
    elif rank >= 10:  # J, Q, K
        return 10
    else:
        return rank + 1


def hand_value(cards: List[int]) -> Tuple[int, bool]:
    """
    Calculate the best hand value.

    Returns:
        (value, is_soft) - value is the best total, is_soft is True if an Ace counts as 11
    """
    total = sum(card_value(c) for c in cards)
    aces = sum(1 for c in cards if card_rank(c) == 0)

    # Reduce aces from 11 to 1 as needed
    while total > 21 and aces > 0:
        total -= 10
        aces -= 1

    is_soft = aces > 0  # At least one ace still counts as 11
    return total, is_soft


def is_blackjack(cards: List[int]) -> bool:
    """Check for natural blackjack (exactly 2 cards totaling 21)."""
    if len(cards) != 2:
        return False
    value, _ = hand_value(cards)
    return value == 21


def is_bust(cards: List[int]) -> bool:
    """Check if hand is busted (over 21)."""
    value, _ = hand_value(cards)
    return value > 21


def can_split(cards: List[int]) -> bool:
    """Check if hand can be split (exactly 2 cards of same rank)."""
    if len(cards) != 2:
        return False
    return card_rank(cards[0]) == card_rank(cards[1])


def can_double(cards: List[int]) -> bool:
    """Check if hand can double down (exactly 2 cards)."""
    return len(cards) == 2


def format_hand(cards: List[int], hide_second: bool = False) -> str:
    """
    Format a hand for display.

    Args:
        cards: List of card indices
        hide_second: If True, show second card as hidden (for dealer during play)
    """
    if not cards:
        return "Empty"
    if hide_second and len(cards) >= 2:
        return f"{card_name(cards[0])} 🂠"
    return " ".join(card_name(c) for c in cards)


def format_hand_with_value(cards: List[int], hide_second: bool = False) -> str:
    """Format hand with its value shown."""
    hand_str = format_hand(cards, hide_second)
    if hide_second:
        # Only show value of first card
        val = card_value(cards[0])
        return f"{hand_str} ({val} + ?)"
    value, is_soft = hand_value(cards)
    soft_str = " soft" if is_soft and value <= 21 else ""
    return f"{hand_str} ({value}{soft_str})"


def dealer_should_hit(cards: List[int]) -> bool:
    """Dealer hits on 16 or less, stands on all 17s."""
    value, _ = hand_value(cards)
    return value < 17


def play_dealer(dealer_cards: List[int], deck: List[int], deck_pos: int) -> Tuple[List[int], int]:
    """
    Play out the dealer's hand according to standard rules.

    Args:
        dealer_cards: Current dealer cards
        deck: Full shuffled deck
        deck_pos: Current position in the deck

    Returns:
        (final_dealer_cards, new_deck_pos)
    """
    while dealer_should_hit(dealer_cards):
        dealer_cards.append(deck[deck_pos])
        deck_pos += 1
    return dealer_cards, deck_pos


def resolve_hand(
    player_cards: List[int],
    dealer_cards: List[int],
    player_has_bj: bool,
    dealer_has_bj: bool,
) -> Tuple[float, str]:
    """
    Resolve a single hand against the dealer.

    Returns:
        (multiplier, outcome_str)
        multiplier: 0.0 = loss, 1.0 = push, 2.0 = win, 2.5 = blackjack win
    """
    player_val, _ = hand_value(player_cards)
    dealer_val, _ = hand_value(dealer_cards)

    # Player bust
    if player_val > 21:
        return 0.0, "Bust"

    # Both have blackjack
    if player_has_bj and dealer_has_bj:
        return 1.0, "Push (both Blackjack)"

    # Player blackjack
    if player_has_bj:
        return 2.5, "Blackjack!"

    # Dealer blackjack
    if dealer_has_bj:
        return 0.0, "Dealer Blackjack"

    # Dealer bust
    if dealer_val > 21:
        return 2.0, "Dealer Bust"

    # Compare values
    if player_val > dealer_val:
        return 2.0, "Win"
    elif player_val == dealer_val:
        return 1.0, "Push"
    else:
        return 0.0, "Loss"
