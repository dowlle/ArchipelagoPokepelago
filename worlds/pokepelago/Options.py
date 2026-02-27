from dataclasses import dataclass
from Options import PerGameCommonOptions, Toggle, Choice, Range


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


class GoalPercentage(Range):
    """Percentage of the selected Pokémon generation that must be guessed to complete the game.
    For example, 100 means guess every Pokémon in the selected generation.
    Set to 0 to use the 'Goal Count' option instead."""
    display_name = "Goal Percentage"
    range_start = 0
    range_end = 100
    default = 100


class GoalCount(Range):
    """Fixed number of Pokémon that must be guessed to complete the game.
    Only used when 'Goal Percentage' is set to 0.
    Must be less than or equal to the total number of Pokémon in the selected generation.
    If set higher than the generation total, it will be capped automatically."""
    display_name = "Goal Count"
    range_start = 1
    range_end = 386
    default = 151


@dataclass
class PokepelagoOptions(PerGameCommonOptions):
    pokemon_generations: PokemonGenerations
    type_locks: EnableTypeLocks
    starting_pokemon: StartingPokemon
    goal_percentage: GoalPercentage
    goal_count: GoalCount