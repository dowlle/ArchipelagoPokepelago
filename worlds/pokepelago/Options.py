from dataclasses import dataclass
from Options import PerGameCommonOptions

# This is where we will add settings later, like "Enable Type Locks"
# or "Max Generation". For now, we just inherit the basic Archipelago options.
@dataclass
class PokepelagoOptions(PerGameCommonOptions):
    pass