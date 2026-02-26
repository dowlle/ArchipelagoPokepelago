from BaseClasses import Region, Entrance, ItemClassification, Tutorial
from worlds.AutoWorld import World, WebWorld
from .Items import PokepelagoItem, item_table, pokemon_names, GEN_1_TYPES, item_data_table
from .Locations import PokepelagoLocation, location_table
from .Options import PokepelagoOptions
from .data import POKEMON_DATA
from . import Rules

class PokepelagoWeb(WebWorld):
    theme = "ocean"
    setup_en = Tutorial(
        "Multiworld Setup Guide",
        "A guide to setting up the Poképelago web client.",
        "English",
        "setup_en.md",
        "setup/en",
        ["dowlle"]
    )
    tutorials = [setup_en]

class PokepelagoWorld(World):
    """
    Poképelago is a Pokémon guessing game randomizer! 
    Unlock Pokémon by finding items in a multiworld, and then guess them 
    in the Poképelago web interface to send checks back to your friends!
    """
    
    game = "Pokepelago"
    web = PokepelagoWeb()
    options_dataclass = PokepelagoOptions
    options: PokepelagoOptions
    topology_present = False
    
    item_name_to_id = item_table
    location_name_to_id = location_table
    item_name_groups = {
        "Pokemon Unlocks": {f"{name} Unlock" for name in pokemon_names},
        "Type Unlocks": {f"{p_type} Type Key" for p_type in GEN_1_TYPES}
    }

    def create_item(self, name: str) -> PokepelagoItem:
        # We now look up the classification directly from our Items.py source of truth.
        # This makes the code much cleaner and easier to maintain.
        data = item_data_table.get(name)
        if data:
            classification = data[1]
            item_id = data[0]
        else:
            # Fallback for unexpected items
            classification = ItemClassification.filler
            item_id = item_table.get(name, 0)
            
        return PokepelagoItem(name, classification, item_id, self.player)

    def create_items(self):
        # 1. Starting Items: We pre-collect the 3 Gen 1 starters.
        # This ensures that even if a player doesn't have them in their YAML,
        # they always have a few Pokémon available to guess at Sphere 0.
        # This prevents logic locks where no Pokémon are initially catchable.
        starters = ["Bulbasaur", "Charmander", "Squirtle"]
        
        for name in starters:
            self.multiworld.push_precollected(self.create_item(f"{name} Unlock"))

        # 2. Type Locks Logic
        if self.options.type_locks.value:
            # IMPORTANT: To avoid a FillError (too many items for 151 locations),
            # we pre-collect ALL Type Keys for now. This keeps them in logic 
            # (letting players guess Pokémon of that type) without overflowing the 151 slots.
            # We explicitly pre-collect them so the multiworld knows they 'exist' from start.
            for p_type in GEN_1_TYPES:
                self.multiworld.push_precollected(self.create_item(f"{p_type} Type Key"))

        # 3. Add remaining Pokémon unlocks to the item pool
        # We skip the 3 starters we already gave the player.
        for name in pokemon_names:
            if name not in starters:
                self.multiworld.itempool.append(self.create_item(f"{name} Unlock"))

        # 4. Fill remaining slots with Useful items (Master Balls, Pokedex, etc.)
        # Since we have 151 locations and only 148 Pokémon left to hide (151 - 3 starters),
        # we need exactly 3 filler items to make the pool fit.
        total_locations = len(self.location_name_to_id)
        
        # We cycle through useful items like Pokedex and Pokegear to fill the gaps.
        # These don't have logic, but make the seed feel more 'complete'.
        useful_fillers = ["Master Ball", "Pokedex", "Pokegear"]
        
        while len(self.multiworld.itempool) < total_locations:
            filler_name = useful_fillers[len(self.multiworld.itempool) % len(useful_fillers)]
            self.multiworld.itempool.append(self.create_item(filler_name))

    def create_regions(self):
        menu_region = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu_region)

        for loc_name, loc_id in self.location_name_to_id.items():
            location = PokepelagoLocation(self.player, loc_name, loc_id, menu_region)
            menu_region.locations.append(location)

        victory_region = Region("Victory", self.player, self.multiworld)
        self.multiworld.regions.append(victory_region)
        
        connection = Entrance(self.player, "Win Game", menu_region)
        menu_region.exits.append(connection)
        connection.connect(victory_region)

    def set_rules(self):
        Rules.set_rules(self)