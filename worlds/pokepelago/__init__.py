from BaseClasses import Region, Entrance, ItemClassification, Tutorial
from worlds.AutoWorld import World, WebWorld
from .Items import PokepelagoItem, item_table, pokemon_names
from .Locations import PokepelagoLocation, location_table
from .Options import PokepelagoOptions
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

    def create_item(self, name: str) -> PokepelagoItem:
        if name == "Master Ball":
            classification = ItemClassification.filler
        else:
            classification = ItemClassification.progression
            
        return PokepelagoItem(name, classification, self.item_name_to_id[name], self.player)

    def create_items(self):
        # 1. Starting Items (Starters)
        starters = ["Bulbasaur Unlock", "Charmander Unlock", "Squirtle Unlock"]
        for starter in starters:
            self.multiworld.push_precollected(self.create_item(starter))

        # 2. Add the REST of our progression items (all 151 minus starters)
        progression_items = [f"{name} Unlock" for name in pokemon_names 
                           if f"{name} Unlock" not in starters]
        
        for item_name in progression_items:
            self.multiworld.itempool.append(self.create_item(item_name))

        # 3. Dynamic Filler calculation
        total_locations = len(self.location_name_to_id)
        current_items = len(self.multiworld.itempool)
        
        for _ in range(total_locations - current_items):
            self.multiworld.itempool.append(self.create_item("Master Ball"))

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