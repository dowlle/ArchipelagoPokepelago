from dataclasses import dataclass
from Options import PerGameCommonOptions, Toggle, Choice

class EnableTypeLocks(Toggle):
    """If true, guessing a Pokémon requires both its specific unlock item and its elemental Type Key."""
    display_name = "Enable Type Locks"
    default = 1

class StartingPokemon(Choice):
    """(Deprecated) This option is currently ignored as all three starters are provided by default."""
    display_name = "Starting Pokémon (Legacy)"
    option_bulbasaur = 0
    option_charmander = 1
    option_squirtle = 2
    default = 0

@dataclass
class PokepelagoOptions(PerGameCommonOptions):
    type_locks: EnableTypeLocks
    starting_pokemon: StartingPokemon