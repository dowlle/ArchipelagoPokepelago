from dataclasses import dataclass
from Options import PerGameCommonOptions, Toggle

# This is where we will add settings later, like "Enable Type Locks"
# or "Max Generation". For now, we just inherit the basic Archipelago options.
class EnableTypeLocks(Toggle):
    """If true, guessing a Pokémon requires both its specific unlock item and its elemental Type Key."""
    display_name = "Enable Type Locks"

@dataclass
class PokepelagoOptions(PerGameCommonOptions):
    type_locks: EnableTypeLocks