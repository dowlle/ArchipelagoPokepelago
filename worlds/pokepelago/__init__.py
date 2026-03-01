import logging
from BaseClasses import Region, Entrance, ItemClassification, Tutorial
from worlds.AutoWorld import World, WebWorld
from rule_builder.cached_world import CachedRuleBuilderWorld
from .Items import PokepelagoItem, item_table, pokemon_names, GEN_1_TYPES, item_data_table
from .Locations import PokepelagoLocation, location_table, milestones
from .Options import PokepelagoOptions
from .data import POKEMON_DATA
from . import Rules

class PokepelagoWeb(WebWorld):
    tutorials = [Tutorial(
        "Pokepelago Setup Guide",
        "A guide to setting up the Pokepelago Archipelago world.",
        "English",
        "setup_en.md",
        "setup/en",
        ["Appie"]
    )]

class PokepelagoWorld(CachedRuleBuilderWorld):
    """
    Pokepelago: A collection-based world where you catch 'em all by guessing their names.
    """
    game: str = "Pokepelago"
    options_dataclass = PokepelagoOptions
    options: PokepelagoOptions
    topology_present: bool = True
    web = PokepelagoWeb()

    # Pokepelago's tier entrance rules use state.has() on event items ("Caught Pokemon")
    # that accumulate during the sweep itself. AP's default BFS only checks each entrance
    # ONCE per sweep cycle - if a tier entrance fails on the first check (because the player
    # has only 3 caught pokemon at sweep start), it is never re-evaluated even as more
    # Caught Pokemon events are collected. Setting this to False makes AP re-check every
    # entrance whenever any region is reached, which is the correct behavior here.
    # Performance cost is acceptable given the alternative is a permanent deadlock.
    explicit_indirect_conditions: bool = False

    item_name_to_id = item_table
    location_name_to_id = location_table
    
    # We define item groups for each Pokémon type to facilitate milestone logic.
    # A Pokémon can belong to multiple groups if it has multiple types.
    item_name_groups = {
        "Pokemon Unlocks": {f"{name} Unlock" for name in pokemon_names},
        "Type Unlocks": {f"{p_type} Type Key" for p_type in GEN_1_TYPES},
        **{f"{p_type} Pokemon": {f"{mon['name']} Unlock" for mon in POKEMON_DATA if p_type in mon['types']} 
           for p_type in GEN_1_TYPES}
    }

    def generate_early(self):
        gen_option = self.options.pokemon_generations.value
        limit = {
            0: 151,
            1: 251,
            2: 386,
            3: 493,
            4: 649,
            5: 721,
            6: 809,
            7: 898,
            8: 1025
        }.get(gen_option, 151)
        self.active_pokemon = [mon for mon in POKEMON_DATA if mon["id"] <= limit]
        self.active_pokemon_names = [mon["name"] for mon in self.active_pokemon]

        # Total new Pokémon guessable (all active minus the 3 precollected starters)
        total_guessable = len(self.active_pokemon) - 3

        # Determine raw goal count from options
        if self.options.goal_type.value == 0:  # percentage
            raw_goal = max(1, round(len(self.active_pokemon) * self.options.goal_percentage.value / 100))
        else:  # count
            raw_goal = min(self.options.goal_count.value, len(self.active_pokemon))

        # The goal is expressed as the number of Pokémon guessed AFTER the starters,
        # so we snap to the closest available "Guessed X Pokemon" milestone that is
        # <= total_guessable. The milestones list (from Locations.py) is already sorted.
        valid_milestones = [m for m in milestones if m <= total_guessable]

        # Find the closest milestone to raw_goal (but cap at max valid milestone)
        capped_goal = min(raw_goal, max(valid_milestones))
        self.goal_count = min(valid_milestones, key=lambda m: abs(m - capped_goal))

    def create_item(self, name: str) -> PokepelagoItem:
        data = item_data_table.get(name)
        if data:
            classification = data[1]
            item_id = data[0]
        else:
            classification = ItemClassification.filler
            item_id = item_table.get(name, 0)
            
        return PokepelagoItem(name, classification, item_id, self.player)

    def create_event_item(self, name: str) -> PokepelagoItem:
        """Create an event item (ID=None) for server-side goal/release tracking."""
        return PokepelagoItem(name, ItemClassification.progression, None, self.player)

    def create_items(self):
        # 1. Provide all 3 starters and their required type keys
        starters = ["Bulbasaur", "Charmander", "Squirtle"]
        starter_types = {"Grass", "Poison", "Fire", "Water"}

        for name in starters:
            self.multiworld.push_precollected(self.create_item(f"{name} Unlock"))
            self.multiworld.push_precollected(self.create_event_item("Caught Pokemon"))
            for t in next(m for m in self.active_pokemon if m["name"] == name)["types"]:
                self.multiworld.push_precollected(self.create_event_item(f"Caught {t} Pokemon"))
        
        for p_type in starter_types:
            self.multiworld.push_precollected(self.create_item(f"{p_type} Type Key"))

        # Track items added to the pool by this player specifically.
        # We must NOT use len(self.multiworld.itempool) because that is the global
        # pool shared by ALL players. When other games run create_items() before us,
        # their items inflate the count and prevent us from adding our fillers.
        my_items_in_pool = 0

        # 2. Add remaining Type Keys to the pool if Type Locks are enabled
        if self.options.type_locks.value:
            for p_type in GEN_1_TYPES:
                if p_type not in starter_types:
                    self.multiworld.itempool.append(self.create_item(f"{p_type} Type Key"))
                    my_items_in_pool += 1

        # 3. Add remaining Pokémon Unlocks to the pool
        for name in self.active_pokemon_names:
            if name not in starters:
                self.multiworld.itempool.append(self.create_item(f"{name} Unlock"))
                my_items_in_pool += 1
                
        print(f"MY ITEMS IN POOL AFTER POKEMON: {my_items_in_pool}")

        # 4. Fill remaining locations with useful items/fillers and traps.
        # NOTE: event locations (ID=None, like "Pokepelago Victory") are server-side only and
        # do NOT need a pool item — only real sendable locations need to be filled.
        total_locations = sum(1 for loc in self.multiworld.get_locations(self.player) if loc.address is not None)
        useful_fillers = ["Master Ball", "Pokedex", "Pokegear"]
        trap_fillers = ["Small Shuffle Trap", "Big Shuffle Trap", "Derpy Mon Trap", "Release Trap"]
        
        trap_chance = self.options.trap_chance.value
        
        while my_items_in_pool < total_locations:
            if self.random.randint(1, 100) <= trap_chance:
                # Add a trap
                filler_name = self.random.choice(trap_fillers)
            else:
                # Add a useful item
                filler_name = useful_fillers[my_items_in_pool % len(useful_fillers)]
                
            self.multiworld.itempool.append(self.create_item(filler_name))
            my_items_in_pool += 1

    def create_regions(self):
        # Tier thresholds: the number of "Caught Pokemon" required to enter each tier.
        TIER_THRESHOLDS = {0: 0, 1: 50, 2: 150, 3: 400, 4: 800}

        # 1. Create Tiered Architecture
        menu_region = Region("Menu", self.player, self.multiworld)
        tier0 = Region("Tier 0", self.player, self.multiworld)
        tier1 = Region("Tier 1", self.player, self.multiworld)
        tier2 = Region("Tier 2", self.player, self.multiworld)
        tier3 = Region("Tier 3", self.player, self.multiworld)
        tier4 = Region("Tier 4", self.player, self.multiworld)
        tiers = [tier0, tier1, tier2, tier3, tier4]

        self.multiworld.regions.extend([menu_region, tier0, tier1, tier2, tier3, tier4])

        # 2. Parallel Connections: Menu -> each Tier directly
        # All tier entrances originate from Menu so they are evaluated in the same BFS
        # cycle as other Menu exits. With explicit_indirect_conditions = False, these
        # entrances are re-evaluated as Caught Pokemon events accumulate during sweep,
        # progressively unlocking higher tiers. A sequential chain (T0->T1->T2...) would
        # require indirect conditions to work correctly with event-based rules, and would
        # not provide meaningful additional pruning benefits over this parallel model.
        for t, threshold in [(tier0, 0), (tier1, 50), (tier2, 150), (tier3, 400), (tier4, 800)]:
            ent = Entrance(self.player, f"Menu To {t.name}", menu_region)
            menu_region.exits.append(ent)
            ent.connect(t)
            if threshold > 0:
                ent.access_rule = lambda state, thresh=threshold: state.has("Caught Pokemon", self.player, thresh)

        # 3. Location Assignment (Milestone and Starting locations)
        # TYPE_MILESTONE_STEPS [1,2,5,10,20,35,50] distributed evenly across 5 tiers.
        # Based on index position rather than raw value to ensure a balanced spread.
        TYPE_STEP_TO_TIER = {1: 0, 2: 0, 5: 1, 10: 1, 20: 2, 35: 3, 50: 4}

        # Compute how many of each type are catchable (excludable starters pre-collected).
        # A type milestone "Caught N X Pokemon" is only valid if N <= catchable count for X.
        STARTER_NAMES = {"Bulbasaur", "Charmander", "Squirtle"}
        type_catchable = {}
        for mon in self.active_pokemon:
            for t in mon["types"]:
                type_catchable[t] = type_catchable.get(t, 0) + 1
        # Subtract starters (pre-collected, so they don't count as new catches)
        for mon in self.active_pokemon:
            if mon["name"] in STARTER_NAMES:
                for t in mon["types"]:
                    if t in type_catchable:
                        type_catchable[t] -= 1

        for loc_name, loc_id in self.location_name_to_id.items():
            if loc_name.startswith("Guess "):
                # Pokemon Guess locations are handled below in the per-pokemon loop.
                continue

            target_region = menu_region  # Default: starting locations go on Menu (no gate).

            if loc_name.startswith("Guessed "):
                count = int(loc_name.split(" ")[1])
                # Skip milestones beyond the active pokemon pool.
                if count > len(self.active_pokemon) - 3:
                    continue
                if count < 50:        target_region = tier0
                elif count < 150:     target_region = tier1
                elif count < 400:     target_region = tier2
                elif count < 800:     target_region = tier3
                else:                 target_region = tier4

                # Sanity check: the tier's entrance threshold must not exceed the location's
                # rule requirement (+3 for starters). If it does, the location is unreachable.
                tier_idx = tiers.index(target_region)
                tier_threshold = TIER_THRESHOLDS[tier_idx]
                rule_requires = count + 3  # +3 for pre-collected starters
                if tier_threshold > rule_requires:
                    logging.warning(
                        f"[Pokepelago] Sanity: '{loc_name}' in Tier {tier_idx} "
                        f"(entrance needs {tier_threshold} catches) but its rule only needs "
                        f"{rule_requires} catches. Location may be unreachable — check tier assignment."
                    )

            elif loc_name.startswith("Caught "):
                # Type milestone: "Caught {step} {Type} Pokemon"
                # Parse: "Caught 10 Fire Pokemon" -> step=10, p_type="Fire"
                parts = loc_name.split(" ")
                step = int(parts[1])
                p_type = parts[2]
                # Skip if this generation doesn't have enough of this type to reach the step.
                if step > type_catchable.get(p_type, 0):
                    continue
                target_region = tiers[TYPE_STEP_TO_TIER.get(step, 0)]

            location = PokepelagoLocation(self.player, loc_name, loc_id, target_region)
            target_region.locations.append(location)

        # 4. Pokemon Regions Assignment
        # Each Pokemon gets its own sub-region connected from the appropriate tier.
        # Tiering is by Pokedex ID as a proxy for generation/game-era difficulty.
        # Starters always land in Tier 0 (unconditionally accessible).
        for mon in self.active_pokemon:
            mon_name = mon["name"]
            mon_region = Region(f"Region {mon_name}", self.player, self.multiworld)
            self.multiworld.regions.append(mon_region)

            loc_name = f"Guess {mon_name}"
            loc_id = self.location_name_to_id[loc_name]
            location = PokepelagoLocation(self.player, loc_name, loc_id, mon_region)
            mon_region.locations.append(location)

            mon_id = mon["id"]
            if mon_name in STARTER_NAMES:
                mon_tier = tier0
            else:
                if mon_id < 100:    mon_tier = tier0
                elif mon_id < 300:  mon_tier = tier1
                elif mon_id < 600:  mon_tier = tier2
                elif mon_id < 900:  mon_tier = tier3
                else:               mon_tier = tier4

            entrance = Entrance(self.player, f"Catch {mon_name}", mon_tier)
            mon_tier.exits.append(entrance)
            entrance.connect(mon_region)

            # Place proxy event items inside the pokemon's region.
            # These fire automatically when the player enters the region (i.e., catches the pokemon),
            # incrementing the "Caught Pokemon" and "Caught {Type} Pokemon" counters used by rules.
            # We use the standard AP pattern: event Location (address=None) + locked event Item.
            if mon_name not in STARTER_NAMES:
                caught_event_loc = PokepelagoLocation(
                    self.player, f"Caught {mon_name} Event", None, mon_region)
                caught_event_loc.place_locked_item(self.create_event_item("Caught Pokemon"))
                mon_region.locations.append(caught_event_loc)

                for t in mon["types"]:
                    type_event_loc = PokepelagoLocation(
                        self.player, f"Caught {mon_name} {t} Event", None, mon_region)
                    type_event_loc.place_locked_item(self.create_event_item(f"Caught {t} Pokemon"))
                    mon_region.locations.append(type_event_loc)

        # Victory event location (ID=None marks it as a server-side event, not a sendable check).
        # The Victory item placed here is what triggers the server's release/goal-completion mechanism.
        victory_location = PokepelagoLocation(self.player, "Pokepelago Victory", None, menu_region)
        menu_region.locations.append(victory_location)

    def set_rules(self):
        Rules.set_rules(self)

        # Canonical Archipelago goal pattern: place a locked "Victory" event item at an event
        # location whose access rule enforces the goal. The server's release/completion mechanism
        # triggers when state.has("Victory") becomes true — can_reach() alone doesn't do this.
        goal = self.goal_count + 3  # +3 because starters are pre-collected and also count
        goal_rule = lambda state: state.has("Caught Pokemon", self.player, goal)

        victory_location = self.multiworld.get_location("Pokepelago Victory", self.player)
        victory_location.access_rule = goal_rule
        victory_item = self.create_event_item("Victory")
        victory_location.place_locked_item(victory_item)

        self.multiworld.completion_condition[self.player] = \
            lambda state: state.has("Victory", self.player)

    def fill_slot_data(self) -> dict:
        return {
            "type_locks": bool(self.options.type_locks.value),
            "pokemon_generations": self.options.pokemon_generations.value,
            "goal_count": self.goal_count,
        }