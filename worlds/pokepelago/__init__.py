from BaseClasses import Region, Entrance, ItemClassification, Tutorial
from worlds.AutoWorld import World, WebWorld
from .Items import PokepelagoItem, item_table, pokemon_names, GEN_1_TYPES, item_data_table
from .Locations import PokepelagoLocation, location_table
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
        ["stefan"]
    )]

class PokepelagoWorld(World):
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

    def create_item(self, name: str) -> PokepelagoItem:
        data = item_data_table.get(name)
        if data:
            classification = data[1]
            item_id = data[0]
        else:
            classification = ItemClassification.filler
            item_id = item_table.get(name, 0)
            
        return PokepelagoItem(name, classification, item_id, self.player)

    def create_items(self):
        # 1. Provide all 3 starters and their required type keys
        starters = ["Bulbasaur", "Charmander", "Squirtle"]
        starter_types = {"Grass", "Poison", "Fire", "Water"}

        for name in starters:
            self.multiworld.push_precollected(self.create_item(f"{name} Unlock"))
        
        for p_type in starter_types:
            self.multiworld.push_precollected(self.create_item(f"{p_type} Type Key"))

        # 2. Add remaining Type Keys to the pool if Type Locks are enabled
        if self.options.type_locks.value:
            for p_type in GEN_1_TYPES:
                if p_type not in starter_types:
                    self.multiworld.itempool.append(self.create_item(f"{p_type} Type Key"))

        # 3. Add remaining Pokémon Unlocks to the pool
        for name in pokemon_names:
            if name not in starters:
                self.multiworld.itempool.append(self.create_item(f"{name} Unlock"))

        # 4. Fill remaining locations (including milestones and extra starts) with useful items/fillers
        total_locations = len(self.location_name_to_id)
        useful_fillers = ["Master Ball", "Pokedex", "Pokegear"]
        
        while len(self.multiworld.itempool) < total_locations:
            filler_name = useful_fillers[len(self.multiworld.itempool) % len(useful_fillers)]
            self.multiworld.itempool.append(self.create_item(filler_name))

    def create_regions(self):
        menu_region = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu_region)

        # All non-guess locations (Milestones, Oak's Lab, etc.) are in Menu
        for loc_name, loc_id in self.location_name_to_id.items():
            if not loc_name.startswith("Guess "):
                location = PokepelagoLocation(self.player, loc_name, loc_id, menu_region)
                menu_region.locations.append(location)

        for mon in POKEMON_DATA:
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

    def set_rules(self):
        Rules.set_rules(self)

    def fill_slot_data(self) -> dict:
        return {
            "type_locks": bool(self.options.type_locks.value)
        }