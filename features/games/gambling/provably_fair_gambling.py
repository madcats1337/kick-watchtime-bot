"""
Provably Fair utilities for gambling games.
Extends the core provably fair SHA-256 algorithm for gambling-specific needs.
"""

import hashlib
import secrets
from typing import Any, Dict, List, Tuple


def generate_gambling_seeds(kick_username: str, game_id: int, game_type: str) -> Dict[str, str]:
    """
    Generate provably fair seeds for a gambling game.

    Returns:
        Dict with server_seed, client_seed, nonce, proof_hash, random_value
    """
    server_seed = secrets.token_hex(32)
    client_seed = f"{kick_username}:{game_id}:{game_type}"
    nonce = str(game_id)

    combined = f"{server_seed}:{client_seed}:{nonce}"
    proof_hash = hashlib.sha256(combined.encode()).hexdigest()

    random_int = int(proof_hash[:8], 16)
    random_value = (random_int % 10000) / 100.0

    return {
        "server_seed": server_seed,
        "client_seed": client_seed,
        "nonce": nonce,
        "proof_hash": proof_hash,
        "random_value": round(random_value, 2),
    }


def generate_deck_shuffle(server_seed: str, client_seed: str) -> List[int]:
    """
    Generate a deterministic 52-card deck shuffle using provably fair hashing.

    For each card position i (0-51), compute:
        hash_i = SHA256(server_seed:client_seed:i)
    Sort card indices by their hash values to produce the shuffle order.

    Args:
        server_seed: 64-char hex server seed
        client_seed: Client seed string

    Returns:
        List of 52 integers (0-51) in shuffled order.
        Card mapping: index // 4 = rank (0=A, 1=2, ..., 12=K), index % 4 = suit
    """
    card_hashes: List[Tuple[str, int]] = []
    for i in range(52):
        combined = f"{server_seed}:{client_seed}:{i}"
        h = hashlib.sha256(combined.encode()).hexdigest()
        card_hashes.append((h, i))

    card_hashes.sort(key=lambda x: x[0])
    return [card_index for _, card_index in card_hashes]


def verify_gambling_result(server_seed: str, client_seed: str, nonce: str, expected_hash: str) -> bool:
    """Verify a gambling result by recomputing the hash."""
    combined = f"{server_seed}:{client_seed}:{nonce}"
    computed_hash = hashlib.sha256(combined.encode()).hexdigest()
    return computed_hash == expected_hash


def verify_deck_shuffle(server_seed: str, client_seed: str, expected_deck: List[int]) -> bool:
    """Verify a deck shuffle by recomputing it."""
    computed_deck = generate_deck_shuffle(server_seed, client_seed)
    return computed_deck == expected_deck
