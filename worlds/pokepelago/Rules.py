from rule_builder.rules import Has, HasAll, Rule
from rule_builder.options import OptionFilter
from typing import TYPE_CHECKING
import dataclasses

from .data import POKEMON_DATA, GEN_1_TYPES
from .Options import EnableTypeLocks

if TYPE_CHECKING:
    from BaseClasses import CollectionState
    from .__init__ import PokepelagoWorld

@dataclasses.dataclass()
class HasGuessablePokemon(Rule["PokepelagoWorld"], game="Pokepelago"):
    req_count: int
    req_type: str | None = None

    def _instantiate(self, world: "PokepelagoWorld") -> Rule.Resolved:
        # Pre-calculate the required items for each relevant pokemon to speed up _evaluate
        relevant_mons = []
        for mon in world.active_pokemon:
            if self.req_type and self.req_type not in mon["types"]:
                continue
            unlock_item = f"{mon['name']} Unlock"
            type_keys = tuple(f"{t} Type Key" for t in mon["types"])
            relevant_mons.append((unlock_item, type_keys))

        return self.Resolved(
            req_count=self.req_count,
            req_type=self.req_type,
            use_type_locks=bool(world.options.type_locks.value),
            relevant_mons=tuple(relevant_mons),
            player=world.player,
            caching_enabled=True
        )

    class Resolved(Rule.Resolved):
        req_count: int
        req_type: str | None
        use_type_locks: bool
        relevant_mons: tuple[tuple[str, tuple[str, ...]], ...]

        def _evaluate(self, state: "CollectionState") -> bool:
            if not self.use_type_locks:
                # Fast path when type locks are disabled
                if self.req_type:
                    return state.has_group(f"{self.req_type} Pokemon", self.player, self.req_count)
                else:
                    return state.has_group("Pokemon Unlocks", self.player, self.req_count)
                    
            # Slower path when type locks are enabled
            count = 0
            for unlock_item, type_keys in self.relevant_mons:
                if state.has(unlock_item, self.player):
                    if all(state.has(t_key, self.player) for t_key in type_keys):
                        count += 1
                        if count >= self.req_count:
                            return True
            return False

        def item_dependencies(self) -> dict[str, set[int]]:
            deps: dict[str, set[int]] = {}
            for unlock_item, type_keys in self.relevant_mons:
                deps.setdefault(unlock_item, set()).add(id(self))
                if self.use_type_locks:
                    for t_key in type_keys:
                        deps.setdefault(t_key, set()).add(id(self))
            return deps


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
            rule = HasGuessablePokemon(count + STARTER_OFFSET)
            world.set_rule(location, rule)
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
                rule = HasGuessablePokemon(count + offset, req_type=p_type)
                world.set_rule(location, rule)
            except KeyError:
                pass



