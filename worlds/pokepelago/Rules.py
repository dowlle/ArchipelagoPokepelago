from rule_builder.rules import Has, HasAll
from rule_builder.options import OptionFilter
from typing import TYPE_CHECKING

from .data import GEN_1_TYPES
from .Options import EnableTypeLocks

if TYPE_CHECKING:
    from .__init__ import PokepelagoWorld

def set_rules(world: "PokepelagoWorld"):
    player = world.player
    use_type_locks = world.options.type_locks.value

    type_locks_disabled = [OptionFilter(EnableTypeLocks, 0)]
    
    # 1. Rules for ENTRANCES
    for mon in world.active_pokemon:
        mon_name = mon["name"]
        unlock_item = f"{mon_name} Unlock"
        type_keys = [f"{t} Type Key" for t in mon["types"]]
        
        entrance_name = f"Catch {mon_name}"
        entrance = world.multiworld.get_entrance(entrance_name, player)
        
        # Rule: You need the Pokemon Unlock AND (either Type Locks are off OR you have all the Type Keys)
        rule = Has(unlock_item) & (HasAll(*type_keys) | type_locks_disabled)
        world.set_rule(entrance, rule)

    # Dynamic Starting Offsets
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
    from .Locations import milestones
    
    for count in milestones:
        loc_name = f"Guessed {count} Pokemon"
        try:
            location = world.multiworld.get_location(loc_name, player)
            rule = Has("Caught Pokemon", count + STARTER_OFFSET)
            world.set_rule(location, rule)
        except KeyError:
            pass

    # 3. Rules for Type-Specific Milestones
    from .Locations import TYPE_MILESTONE_STEPS
    type_milestone_counts = TYPE_MILESTONE_STEPS
    
    for p_type in GEN_1_TYPES:
        offset = TYPE_OFFSETS.get(p_type, 0)
        for count in type_milestone_counts:
            loc_name = f"Caught {count} {p_type} Pokemon"
            try:
                location = world.multiworld.get_location(loc_name, player)
                rule = Has(f"Caught {p_type} Pokemon", count + offset)
                world.set_rule(location, rule)
            except KeyError:
                pass