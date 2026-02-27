from dataclasses import dataclass
from Options import PerGameCommonOptions, Toggle, Choice

class EnableTypeLocks(Toggle):
    """If true, guessing a Pokémon requires both its specific unlock item and its elemental Type Key."""
    display_name = "Enable Type Locks"
    default = 1

class PokemonGenerations(Choice):
    """Select how many generations of Pokémon to include in the randomizer.
    Gen 1 (Kanto) = 151
    Gen 2 (Johto) = 251 
    Gen 3 (Hoenn) = 386"""
    display_name = "Pokemon Generations"
    option_gen1 = 0
    option_gen2 = 1
    option_gen3 = 2
    default = 0

class StartingPokemon(Choice):
    """(Deprecated) This option is currently ignored as all three starters are provided by default."""
    display_name = "Starting Pokémon (Legacy)"
    option_bulbasaur = 0
    option_charmander = 1
    option_squirtle = 2
    default = 0

@dataclass
class PokepelagoOptions(PerGameCommonOptions):
    pokemon_generations: PokemonGenerations
    type_locks: EnableTypeLocks
    starting_pokemon: StartingPokemon