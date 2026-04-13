"""
Discord UI views for gambling games.
BlackjackView provides interactive buttons for Hit, Stand, Double, Split.
"""

import discord

from .blackjack import (
    can_double,
    can_split,
    card_rank,
    dealer_should_hit,
    format_hand,
    format_hand_with_value,
    hand_value,
    is_blackjack,
    is_bust,
    play_dealer,
    resolve_hand,
)


class BlackjackView(discord.ui.View):
    """Interactive view for a blackjack game session."""

    def __init__(
        self,
        *,
        player_id: int,
        kick_username: str,
        guild_id: int,
        bet: int,
        deck: list,
        deck_pos: int,
        player_hands: list,
        dealer_cards: list,
        bets: list,
        server_seed: str,
        client_seed: str,
        nonce: str,
        proof_hash: str,
        save_callback,
        points_callback,
        deduct_callback,
        balance_callback,
    ):
        super().__init__(timeout=120)
        self.player_id = player_id
        self.kick_username = kick_username
        self.guild_id = guild_id
        self.original_bet = bet
        self.deck = deck
        self.deck_pos = deck_pos
        self.player_hands = player_hands  # List of lists (supports split)
        self.dealer_cards = dealer_cards
        self.bets = bets  # Bet per hand
        self.current_hand = 0  # Index into player_hands
        self.server_seed = server_seed
        self.client_seed = client_seed
        self.nonce = nonce
        self.proof_hash = proof_hash
        self.save_callback = save_callback  # async fn(game_data, payout, net)
        self.points_callback = points_callback  # async fn(amount) to award points
        self.deduct_callback = deduct_callback  # async fn(amount) to deduct points
        self.balance_callback = balance_callback  # async fn() -> int current balance
        self.game_over = False
        self.did_split = False
        self._update_buttons()

    def _current_cards(self):
        return self.player_hands[self.current_hand]

    def _draw_card(self):
        card = self.deck[self.deck_pos]
        self.deck_pos += 1
        return card

    def _update_buttons(self):
        """Enable/disable buttons based on current game state."""
        cards = self._current_cards()
        self.hit_button.disabled = self.game_over
        self.stand_button.disabled = self.game_over
        self.double_button.disabled = self.game_over or not can_double(cards)
        # Split: only on first hand, only if pair, and haven't already split
        self.split_button.disabled = self.game_over or self.did_split or self.current_hand != 0 or not can_split(cards)

    def _build_embed(self, final: bool = False) -> discord.Embed:
        """Build the game embed showing current state."""
        if final:
            color = discord.Color.gold()
        else:
            color = discord.Color.blurple()

        embed = discord.Embed(title="🃏 Blackjack", color=color)

        # Dealer hand
        if final:
            dealer_str = format_hand_with_value(self.dealer_cards, hide_second=False)
        else:
            dealer_str = format_hand_with_value(self.dealer_cards, hide_second=True)
        embed.add_field(name="Dealer", value=dealer_str, inline=False)

        # Player hand(s)
        for i, (hand, bet) in enumerate(zip(self.player_hands, self.bets)):
            prefix = ""
            if len(self.player_hands) > 1:
                if not final and i == self.current_hand:
                    prefix = "▶ "
                label = f"Hand {i + 1}"
            else:
                label = "Your Hand"
            hand_str = format_hand_with_value(hand)
            embed.add_field(
                name=f"{prefix}{label} (Bet: {bet:,})",
                value=hand_str,
                inline=False,
            )

        return embed

    def _build_result_embed(self, results: list) -> discord.Embed:
        """Build the final result embed after game resolution."""
        total_payout = sum(p for p, _, _ in results)
        total_bet = sum(self.bets)
        net = total_payout - total_bet

        if net > 0:
            color = discord.Color.green()
            outcome_emoji = "🎉"
        elif net == 0:
            color = discord.Color.gold()
            outcome_emoji = "🤝"
        else:
            color = discord.Color.red()
            outcome_emoji = "💔"

        embed = discord.Embed(title=f"{outcome_emoji} Blackjack - Game Over", color=color)

        # Dealer hand
        dealer_str = format_hand_with_value(self.dealer_cards)
        embed.add_field(name="Dealer", value=dealer_str, inline=False)

        # Player hand results
        for i, ((payout, mult, outcome_str), hand, bet) in enumerate(zip(results, self.player_hands, self.bets)):
            label = f"Hand {i + 1}" if len(self.player_hands) > 1 else "Your Hand"
            hand_str = format_hand_with_value(hand)
            hand_payout = payout - bet
            sign = "+" if hand_payout >= 0 else ""
            embed.add_field(
                name=f"{label} — {outcome_str}",
                value=f"{hand_str}\nBet: {bet:,} → {sign}{hand_payout:,}",
                inline=False,
            )

        # Total result
        sign = "+" if net >= 0 else ""
        embed.add_field(
            name="Result",
            value=f"**{sign}{net:,} points**",
            inline=False,
        )

        # Provably fair footer
        embed.set_footer(text=f"Server Seed: {self.server_seed[:16]}... | Hash: {self.proof_hash[:16]}...")

        return embed

    async def interaction_check(self, interaction: discord.Interaction) -> bool:
        if interaction.user.id != self.player_id:
            await interaction.response.send_message("This isn't your game!", ephemeral=True)
            return False
        return True

    async def on_timeout(self):
        """Auto-stand on timeout."""
        if not self.game_over:
            self.game_over = True
            # Can't edit the message without an interaction, game just ends

    async def _finish_game(self, interaction: discord.Interaction):
        """Play out the dealer and resolve all hands."""
        self.game_over = True

        # Check if all player hands are bust
        all_bust = all(is_bust(hand) for hand in self.player_hands)

        if not all_bust:
            # Dealer plays
            self.dealer_cards, self.deck_pos = play_dealer(self.dealer_cards, self.deck, self.deck_pos)

        # Resolve each hand
        dealer_has_bj = is_blackjack(self.dealer_cards)
        results = []
        total_payout = 0
        for i, (hand, bet) in enumerate(zip(self.player_hands, self.bets)):
            player_has_bj = is_blackjack(hand) and not self.did_split
            mult, outcome_str = resolve_hand(hand, self.dealer_cards, player_has_bj, dealer_has_bj)
            payout = int(bet * mult)
            total_payout += payout
            results.append((payout, mult, outcome_str))

        # Award payout
        if total_payout > 0:
            await self.points_callback(total_payout)

        # Build game data for history
        total_bet = sum(self.bets)
        net = total_payout - total_bet
        game_data = {
            "player_hands": [[int(c) for c in h] for h in self.player_hands],
            "dealer_cards": [int(c) for c in self.dealer_cards],
            "bets": self.bets,
            "results": [(p, m, o) for p, m, o in results],
            "did_split": self.did_split,
        }
        await self.save_callback(game_data, total_payout, net)

        # Update embed
        embed = self._build_result_embed(results)
        self._update_buttons()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Hit", style=discord.ButtonStyle.success, emoji="👆")
    async def hit_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        card = self._draw_card()
        self._current_cards().append(card)

        if is_bust(self._current_cards()):
            # Move to next hand or finish
            if self.current_hand < len(self.player_hands) - 1:
                self.current_hand += 1
                # If split aces, each gets one card only - this hand is done too
                self._update_buttons()
                embed = self._build_embed()
                await interaction.response.edit_message(embed=embed, view=self)
            else:
                await self._finish_game(interaction)
            return

        self._update_buttons()
        embed = self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)

    @discord.ui.button(label="Stand", style=discord.ButtonStyle.secondary, emoji="✋")
    async def stand_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Move to next hand or finish
        if self.current_hand < len(self.player_hands) - 1:
            self.current_hand += 1
            self._update_buttons()
            embed = self._build_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await self._finish_game(interaction)

    @discord.ui.button(label="Double", style=discord.ButtonStyle.primary, emoji="💰")
    async def double_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        # Check balance for extra bet
        current_bet = self.bets[self.current_hand]
        balance = await self.balance_callback()
        if balance < current_bet:
            await interaction.response.send_message(
                f"❌ You need **{current_bet:,}** more points to double. Balance: **{balance:,}**",
                ephemeral=True,
            )
            return

        # Deduct extra bet and double
        await self.deduct_callback(current_bet)
        self.bets[self.current_hand] *= 2
        card = self._draw_card()
        self._current_cards().append(card)

        # Move to next hand or finish
        if self.current_hand < len(self.player_hands) - 1:
            self.current_hand += 1
            self._update_buttons()
            embed = self._build_embed()
            await interaction.response.edit_message(embed=embed, view=self)
        else:
            await self._finish_game(interaction)

    @discord.ui.button(label="Split", style=discord.ButtonStyle.danger, emoji="✂️")
    async def split_button(self, interaction: discord.Interaction, button: discord.ui.Button):
        hand = self._current_cards()

        # Check balance for extra bet
        current_bet = self.bets[0]
        balance = await self.balance_callback()
        if balance < current_bet:
            await interaction.response.send_message(
                f"❌ You need **{current_bet:,}** more points to split. Balance: **{balance:,}**",
                ephemeral=True,
            )
            return

        # Deduct extra bet for second hand
        await self.deduct_callback(current_bet)

        # Split into two hands
        card1 = hand[0]
        card2 = hand[1]

        self.player_hands[0] = [card1, self._draw_card()]
        self.player_hands.append([card2, self._draw_card()])
        self.bets.append(self.bets[0])  # Same bet for second hand
        self.did_split = True

        # If split aces, each gets one card only — auto-stand both
        if card_rank(card1) == 0:  # Aces
            await self._finish_game(interaction)
            return

        self._update_buttons()
        embed = self._build_embed()
        await interaction.response.edit_message(embed=embed, view=self)
