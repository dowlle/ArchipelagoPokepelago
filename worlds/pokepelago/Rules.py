from .Items import pokemon_names

def set_rules(world):
    player = world.player
    
    # Each location requires its corresponding unlock item
    for name in pokemon_names:
        world.multiworld.get_location(f"Guess {name}", player).access_rule = \
            lambda state, n=name: state.has(f"{n} Unlock", player)

    # Victory condition: Guess all 151 Pokémon
    world.multiworld.completion_condition[player] = lambda state: \
        all(state.has(f"{name} Unlock", player) for name in pokemon_names)
