from worlds.generic.Rules import set_rule
from .data import POKEMON_DATA

def set_rules(world):
    player = world.player
    use_type_locks = world.options.type_locks.value

    # Helper function prevents Python's late-binding loop lambda bug!
    def create_rule(unlock_item, type_key):
        if use_type_locks:
            return lambda state: state.has(unlock_item, player) and state.has(type_key, player)
        return lambda state: state.has(unlock_item, player)

    # Loop through all 151 Pokémon
    for mon in POKEMON_DATA:
        loc_name = f"Guess {mon['name']}"
        unlock_item = f"{mon['name']} Unlock"
        
        # We'll use their Primary Type (index 0) for the lock
        primary_type = mon["types"][0]
        type_key = f"{primary_type} Type Key"

        # Apply the rule to the location
        location = world.multiworld.get_location(loc_name, player)
        set_rule(location, create_rule(unlock_item, type_key))

    # Completion condition: Require all 151 Pokémon found
    world.multiworld.completion_condition[player] = lambda state: state.has_group("Pokemon Unlocks", player, 151)
