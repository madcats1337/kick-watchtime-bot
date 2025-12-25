"""
Provably Fair Utilities for Slot Reward System
Implements SHA-256 based provably fair random value generation
"""

import secrets
import hashlib
from typing import Dict, Any


def generate_provably_fair_result(kick_username: str, slot_request_id: int, slot_call: str, 
                                   chance_percent: float) -> Dict[str, Any]:
    """
    Generate a provably fair random result for slot reward determination.
    
    Algorithm:
    1. Generate server_seed (64 char hex string using cryptographically secure RNG)
    2. Construct client_seed: "kick_username:id:slot_call"
    3. Set nonce: slot_request_id
    4. Concatenate: "server_seed:client_seed:nonce"
    5. Compute SHA-256 hash
    6. Convert first 8 hex chars to integer (0-4294967295)
    7. Reduce to 0.00-99.99: (integer % 10000) / 100
    8. Compare with chance_percent to determine if reward is won
    
    Args:
        kick_username: Username from Kick
        slot_request_id: Database ID of the slot request
        slot_call: Name of the slot requested
        chance_percent: Win chance percentage (0-100)
    
    Returns:
        Dictionary containing:
        - won: Boolean indicating if reward was won
        - server_seed: Generated server seed (64 chars)
        - client_seed: Constructed client seed
        - nonce: Request ID as string
        - proof_hash: Full SHA-256 hash
        - random_value: Derived value (0.00-99.99)
        - chance: The chance percentage used
    """
    # Generate cryptographically secure server seed
    server_seed = secrets.token_hex(32)  # 64 character hex string
    
    # Construct client seed: username:id:slot_call
    client_seed = f"{kick_username}:{slot_request_id}:{slot_call}"
    
    # Nonce is the slot request ID
    nonce = str(slot_request_id)
    
    # Combine seeds with colons
    combined = f"{server_seed}:{client_seed}:{nonce}"
    
    # Compute SHA-256 hash
    proof_hash = hashlib.sha256(combined.encode()).hexdigest()
    
    # Convert first 8 hex characters to integer
    random_int = int(proof_hash[:8], 16)  # 0 to 4,294,967,295
    
    # Reduce to 0.00 - 99.99
    random_value = (random_int % 10000) / 100.0
    
    # Determine if won (strictly less than chance_percent)
    won = random_value < chance_percent
    
    return {
        'won': won,
        'server_seed': server_seed,
        'client_seed': client_seed,
        'nonce': nonce,
        'proof_hash': proof_hash,
        'random_value': round(random_value, 2),
        'chance': chance_percent
    }


def verify_provably_fair_result(server_seed: str, client_seed: str, nonce: str,
                                 expected_hash: str, expected_random_value: float) -> bool:
    """
    Verify a provably fair result by recomputing the hash and random value.
    
    Args:
        server_seed: Original server seed
        client_seed: Original client seed
        nonce: Original nonce
        expected_hash: Expected proof hash
        expected_random_value: Expected random value
    
    Returns:
        True if verification succeeds, False otherwise
    """
    try:
        # Recompute hash
        combined = f"{server_seed}:{client_seed}:{nonce}"
        computed_hash = hashlib.sha256(combined.encode()).hexdigest()
        
        # Verify hash matches
        if computed_hash != expected_hash:
            return False
        
        # Recompute random value
        random_int = int(computed_hash[:8], 16)
        computed_random_value = round((random_int % 10000) / 100.0, 2)
        
        # Verify random value matches (with small floating point tolerance)
        if abs(computed_random_value - expected_random_value) > 0.01:
            return False
        
        return True
    except Exception:
        return False
