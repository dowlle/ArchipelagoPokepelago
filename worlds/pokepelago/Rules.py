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
    for mon in world.active_pokemon:
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
    for mon in world.active_pokemon:
        if mon["name"] in STARTER_NAMES:
            for t in mon["types"]:
                if t in TYPE_OFFSETS:
                    TYPE_OFFSETS[t] += 1

    # 2. Rules for Global Milestones
    milestones = [1, 5, 10] + list(range(20, 391, 10)) + [148, 248, 383]
    milestones = sorted(list(set(milestones)))
    
    def create_global_rule(req_count):
        if use_type_locks:
            return lambda state: sum(
                1 for mon in world.active_pokemon 
                if state.has(f"{mon['name']} Unlock", player) 
                and all(state.has(f"{t} Type Key", player) for t in mon["types"])
            ) >= req_count
        return lambda state: state.has_group("Pokemon Unlocks", player, req_count)

    for count in milestones:
        loc_name = f"Guessed {count} Pokemon"
        try:
            location = world.multiworld.get_location(loc_name, player)
            set_rule(location, create_global_rule(count + STARTER_OFFSET))
        except KeyError:
            pass

    # 3. Rules for Type-Specific Milestones
    type_milestone_counts = [1, 2, 5, 10, 15, 20, 30, 40, 50]
    
    def create_type_rule(req_type, req_count):
        if use_type_locks:
            return lambda state: sum(
                1 for mon in world.active_pokemon 
                if req_type in mon["types"] 
                and state.has(f"{mon['name']} Unlock", player) 
                and all(state.has(f"{t} Type Key", player) for t in mon["types"])
            ) >= req_count
        return lambda state: state.has_group(f"{req_type} Pokemon", player, req_count)

    for p_type in GEN_1_TYPES:
        offset = TYPE_OFFSETS.get(p_type, 0)
        for count in type_milestone_counts:
            loc_name = f"Caught {count} {p_type} Pokemon"
            try:
                location = world.multiworld.get_location(loc_name, player)
                set_rule(location, create_type_rule(p_type, count + offset))
            except KeyError:
                pass


