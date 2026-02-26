from worlds.generic.Rules import set_rule
from .data import POKEMON_DATA, GEN_1_TYPES

def set_rules(world):
    player = world.player
    use_type_locks = world.options.type_locks.value

    # Closure ensures we capture mon_name, unlock_item, and type_keys correctly 
    # for each entrance/location during the loop.
    def create_entrance_rule(unlock_item, type_keys):
        if use_type_locks:
            return lambda state: state.has(unlock_item, player) and \
                                 all(state.has(f"{t} Type Key", player) for t in type_keys)
        return lambda state: state.has(unlock_item, player)

    # 1. Rules for ENTRANCES
    for mon in POKEMON_DATA:
        mon_name = mon["name"]
        unlock_item = f"{mon_name} Unlock"
        mon_types = mon["types"]
        
        entrance_name = f"Catch {mon_name}"
        entrance = world.multiworld.get_entrance(entrance_name, player)
        set_rule(entrance, create_entrance_rule(unlock_item, mon_types))

    # Dynamic Starting Offsets:
    # 3 Starters are pre-collected: Bulbasaur (Grass/Poison), Charmander (Fire), Squirtle (Water).
    # We should calculate these based on the actual starters to be robust.
    STARTER_NAMES = ["Bulbasaur", "Charmander", "Squirtle"]
    STARTER_OFFSET = len(STARTER_NAMES)
    
    # Calculate type offsets (how many of each type we start with)
    TYPE_OFFSETS = {t: 0 for t in GEN_1_TYPES}
    for mon in POKEMON_DATA:
        if mon["name"] in STARTER_NAMES:
            for t in mon["types"]:
                if t in TYPE_OFFSETS:
                    TYPE_OFFSETS[t] += 1

    # 2. Rules for Global Milestones
    milestones = [1, 5, 10, 20, 30, 40, 50, 60, 70, 80, 90, 100, 110, 120, 130, 140, 148]
    for count in milestones:
        loc_name = f"Guessed {count} Pokemon"
        try:
            location = world.multiworld.get_location(loc_name, player)
            # Offset by starting inventory (3)
            set_rule(location, lambda state, c=count: state.has_group("Pokemon Unlocks", player, c + STARTER_OFFSET))
        except KeyError:
            pass

    # 3. Rules for Type-Specific Milestones
    type_milestone_counts = [1, 2, 5, 10, 15, 20, 30, 40, 50]
    for p_type in GEN_1_TYPES:
        offset = TYPE_OFFSETS.get(p_type, 0)
        for count in type_milestone_counts:
            loc_name = f"Caught {count} {p_type} Pokemon"
            try:
                location = world.multiworld.get_location(loc_name, player)
                if use_type_locks:
                    # You need the count + offset AND the key to 'catch' them for the milestone.
                    set_rule(location, lambda state, pt=p_type, c=count, o=offset: \
                        state.has_group(f"{pt} Pokemon", player, c + o) and \
                        state.has(f"{pt} Type Key", player))
                else:
                    set_rule(location, lambda state, pt=p_type, c=count, o=offset: \
                        state.has_group(f"{pt} Pokemon", player, c + o))
            except KeyError:
                pass

    # Win Condition
    if use_type_locks:
        world.multiworld.completion_condition[player] = lambda state: \
            state.has_group("Pokemon Unlocks", player, 151) and \
            state.has_group("Type Unlocks", player, 16)
    else:
        world.multiworld.completion_condition[player] = lambda state: \
            state.has_group("Pokemon Unlocks", player, 151)
