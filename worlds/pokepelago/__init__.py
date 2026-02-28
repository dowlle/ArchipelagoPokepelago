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
        menu_region = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu_region)

        # All non-guess locations (Milestones, Oak's Lab, etc.) are in Menu
        for loc_name, loc_id in self.location_name_to_id.items():
            if loc_name.startswith("Guess "):
                continue
                
            if loc_name.startswith("Guessed "):
                count = int(loc_name.split(" ")[1])
                if count > len(self.active_pokemon) - 3:
                    continue
                    
            if loc_name.startswith("Caught "):
                parts = loc_name.split(" ")
                count = int(parts[1])
                p_type = parts[2]
                type_max = sum(1 for m in self.active_pokemon if p_type in m["types"])
                STARTER_NAMES = {"Bulbasaur", "Charmander", "Squirtle"}
                starters_of_type = sum(1 for m in self.active_pokemon if m["name"] in STARTER_NAMES and p_type in m["types"])
                if count > (type_max - starters_of_type):
                    continue

            location = PokepelagoLocation(self.player, loc_name, loc_id, menu_region)
            menu_region.locations.append(location)

        for mon in self.active_pokemon:
            mon_name = mon["name"]
            mon_region = Region(f"Region {mon_name}", self.player, self.multiworld)
            self.multiworld.regions.append(mon_region)

            loc_name = f"Guess {mon_name}"
            loc_id = self.location_name_to_id[loc_name]
            location = PokepelagoLocation(self.player, loc_name, loc_id, mon_region)
            mon_region.locations.append(location)

            entrance = Entrance(self.player, f"Catch {mon_name}", menu_region)
            menu_region.exits.append(entrance)
            entrance.connect(mon_region)

        # Victory event location (ID=None marks it as a server-side event, not a sendable check).
        # The Victory item placed here is what triggers the server's release/goal-completion mechanism.
        victory_location = PokepelagoLocation(self.player, "Pokepelago Victory", None, menu_region)
        menu_region.locations.append(victory_location)

    def set_rules(self):
        Rules.set_rules(self)

        # Canonical Archipelago goal pattern: place a locked "Victory" event item at an event
        # location whose access rule enforces the goal. The server's release/completion mechanism
        # triggers when state.has("Victory") becomes true — can_reach() alone doesn't do this.
        use_type_locks = self.options.type_locks.value
        goal = self.goal_count + 3  # +3 because starters are pre-collected and also count

        if use_type_locks:
            goal_rule = lambda state: sum(
                1 for mon in self.active_pokemon
                if state.has(f"{mon['name']} Unlock", self.player)
                and all(state.has(f"{t} Type Key", self.player) for t in mon["types"])
            ) >= goal
        else:
            goal_rule = lambda state: state.has_group("Pokemon Unlocks", self.player, goal)

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