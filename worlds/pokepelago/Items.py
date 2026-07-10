from BaseClasses import Item, ItemClassification
from .data import POKEMON_DATA, GEN_1_TYPES, GAME_REGIONS
from .route_data import ROUTE_DATA, ROUTE_GROUPS, EVOLUTION_FAMILIES

# A random high number to ensure our IDs don't overlap with other games
ITEM_ID_OFFSET = 8574000

# This table acts as the single source of truth for all items in the Pokepelago world.
# We map each item name to its unique ID and its classification (progression, useful, filler).
# This makes scaling the game easy: just add a new item here and the generator handles the rest.
item_data_table = {}

# Item name groups (hints, plando, item_links, start_inventory/local_items can all target a
# group). Built inline as each category below is added to item_data_table so a group can never
# drift from the real item set (the BUG-16 class of bug: hand-duplicated lists rot silently).
ITEM_NAME_GROUPS: dict[str, set[str]] = {}

# 1. Add Pokémon Unlocks (Progression)
# These are required to catch a specific Pokémon and unlock its location path.
# No group here: no per-Pokémon unlock item is ever created by create_items(), only entered
# into this table for ID stability, so a "Pokemon Unlocks" group would be entirely inert.
for i, mon in enumerate(POKEMON_DATA):
    item_data_table[f"{mon['name']} Unlock"] = (ITEM_ID_OFFSET + mon["id"], ItemClassification.progression)

# 2. Add Type Keys (Progression — client-side gating, AP ensures they're reachable early)
# No AP access rules use these; client checks them to determine which types are guessable.
_type_key_names: set[str] = set()
for i, p_type in enumerate(GEN_1_TYPES):
    _type_key_name = f"{p_type} Type Key"
    item_data_table[_type_key_name] = (ITEM_ID_OFFSET + 2000 + i, ItemClassification.progression)
    _type_key_names.add(_type_key_name)
ITEM_NAME_GROUPS["Type Keys"] = _type_key_names

# 3. Add Useful Items
# These help the player but aren't strictly required to finish the game.
_USEFUL_ITEMS = {
    "Master Ball": (ITEM_ID_OFFSET + 3001, ItemClassification.useful),
    "Pokedex":     (ITEM_ID_OFFSET + 3002, ItemClassification.useful),
    "Pokegear":    (ITEM_ID_OFFSET + 3003, ItemClassification.useful),
}
item_data_table.update(_USEFUL_ITEMS)
ITEM_NAME_GROUPS["Useful"] = set(_USEFUL_ITEMS.keys())

# Joke / "nothing" item — purely thematic padding
item_data_table["Magikarp used Splash - but nothing happened!"] = (ITEM_ID_OFFSET + 3019, ItemClassification.filler)

# 4. Add Traps
# These are meant to hinder the player.
_TRAP_ITEMS = {
    "Small Shuffle Trap": (ITEM_ID_OFFSET + 4001, ItemClassification.trap),
    "Big Shuffle Trap":   (ITEM_ID_OFFSET + 4002, ItemClassification.trap),
    "Derpy Mon Trap":     (ITEM_ID_OFFSET + 4003, ItemClassification.trap),
    "Release Trap":       (ITEM_ID_OFFSET + 4004, ItemClassification.trap),
}
item_data_table.update(_TRAP_ITEMS)
ITEM_NAME_GROUPS["Traps"] = set(_TRAP_ITEMS.keys())

# 5. Region Pass items (Progression)
# One pass per game region. IDs: ITEM_ID_OFFSET + 5000 + region_index (8579000–8579009)
_region_pass_names: set[str] = set()
for _i, _region in enumerate(GAME_REGIONS):
    _region_pass_name = f"{_region} Pass"
    item_data_table[_region_pass_name] = (ITEM_ID_OFFSET + 5000 + _i, ItemClassification.progression)
    _region_pass_names.add(_region_pass_name)
ITEM_NAME_GROUPS["Region Passes"] = _region_pass_names

# 6. New gate progression items (6xxx range)
# These implement the new lock option systems: legendary gates, trade evolutions, baby Pokémon,
# fossil Pokémon, ultra beasts, paradox Pokémon, and stone-only evolutions.
_GATE_ITEMS = {
    "Gym Badge":       (ITEM_ID_OFFSET + 6000, ItemClassification.progression),  # progressive: 6/7/8 for legendary tiers
    "Link Cable":      (ITEM_ID_OFFSET + 6001, ItemClassification.progression),  # trade evolution gate
    "Daycare":         (ITEM_ID_OFFSET + 6002, ItemClassification.progression),  # baby Pokémon gate (progressive count)
    "Ultra Wormhole":  (ITEM_ID_OFFSET + 6003, ItemClassification.progression),  # ultra beast gate
    "Time Rift":       (ITEM_ID_OFFSET + 6004, ItemClassification.progression),  # paradox Pokémon gate
    "Fossil Restorer": (ITEM_ID_OFFSET + 6005, ItemClassification.progression),  # fossil Pokémon gate
}
item_data_table.update(_GATE_ITEMS)
ITEM_NAME_GROUPS["Gate Items"] = set(_GATE_ITEMS.keys())

# Evolutionary stones (6010–6019) — gate stone-only evolved Pokémon
_STONE_ITEMS = {
    "Fire Stone":      (ITEM_ID_OFFSET + 6010, ItemClassification.progression),
    "Water Stone":     (ITEM_ID_OFFSET + 6011, ItemClassification.progression),
    "Thunder Stone":   (ITEM_ID_OFFSET + 6012, ItemClassification.progression),
    "Leaf Stone":      (ITEM_ID_OFFSET + 6013, ItemClassification.progression),
    "Moon Stone":      (ITEM_ID_OFFSET + 6014, ItemClassification.progression),
    "Sun Stone":       (ITEM_ID_OFFSET + 6015, ItemClassification.progression),
    "Shiny Stone":     (ITEM_ID_OFFSET + 6016, ItemClassification.progression),
    "Dusk Stone":      (ITEM_ID_OFFSET + 6017, ItemClassification.progression),
    "Dawn Stone":      (ITEM_ID_OFFSET + 6018, ItemClassification.progression),
    "Ice Stone":       (ITEM_ID_OFFSET + 6019, ItemClassification.progression),
}
item_data_table.update(_STONE_ITEMS)
ITEM_NAME_GROUPS["Evolution Stones"] = set(_STONE_ITEMS.keys())

# Cosmetic filler — grouped with the other collector's Useful items despite the filler classification
item_data_table["Shiny Charm"] = (ITEM_ID_OFFSET + 6020, ItemClassification.filler)
ITEM_NAME_GROUPS["Useful"].add("Shiny Charm")

# 7. Route Key items (Progression) — one per route GROUP + one per ungrouped route.
# Grouped routes share a single key (e.g. "Melemele Island Key" covers Routes 1-3).
# Virtual and roaming routes are not grouped and keep individual keys.
# IDs: ITEM_ID_OFFSET + 7000 + sequential index. Filtered per-game in create_items().
ROUTE_KEY_OFFSET = 7000
_grouped_route_keys = set()
for _g in ROUTE_GROUPS.values():
    _grouped_route_keys.update(_g["routes"])

# Build combined list: groups first, then ungrouped individual routes
ROUTE_KEY_NAMES: dict[str, str] = {}  # group_key or route_key -> item name
_all_route_keys_sorted = sorted(ROUTE_GROUPS.keys()) + sorted(
    rk for rk in ROUTE_DATA if rk not in _grouped_route_keys
)
for _i, _key in enumerate(_all_route_keys_sorted):
    if _key in ROUTE_GROUPS:
        _display = ROUTE_GROUPS[_key]["display_name"]
    else:
        _display = ROUTE_DATA[_key]["display_name"]
    _item_name = f"{_display} Key"
    item_data_table[_item_name] = (ITEM_ID_OFFSET + ROUTE_KEY_OFFSET + _i, ItemClassification.progression)
    ROUTE_KEY_NAMES[_key] = _item_name
ITEM_NAME_GROUPS["Route Keys"] = set(ROUTE_KEY_NAMES.values())

# 8. Line Unlock items (Progression) — one per evolution family
# IDs: ITEM_ID_OFFSET + 9000 + base_pokemon_id. Filtered per-game in create_items().
LINE_UNLOCK_OFFSET = 9000
_name_map = {m["id"]: m["name"] for m in POKEMON_DATA}
LINE_UNLOCK_NAMES: dict[int, str] = {}  # base_id → item name
for _base_id in sorted(EVOLUTION_FAMILIES.keys()):
    _base_name = _name_map.get(_base_id, f"Pokemon {_base_id}")
    _item_name = f"{_base_name} Line"
    item_data_table[_item_name] = (ITEM_ID_OFFSET + LINE_UNLOCK_OFFSET + _base_id, ItemClassification.progression)
    LINE_UNLOCK_NAMES[_base_id] = _item_name
ITEM_NAME_GROUPS["Line Unlocks"] = set(LINE_UNLOCK_NAMES.values())

# Offsets exported for reference (client uses ITEM_ID_OFFSET + these to identify items)
GYM_BADGE_OFFSET = 6000
STONE_OFFSETS: dict = {
    "fire": 6010, "water": 6011, "thunder": 6012, "leaf": 6013, "moon": 6014,
    "sun": 6015, "shiny": 6016, "dusk": 6017, "dawn": 6018, "ice": 6019,
}
SHINY_TOKEN_OFFSET = 6020

# For backward compatibility with other files that might still use item_table (name -> id)
item_table = {name: data[0] for name, data in item_data_table.items()}
pokemon_names = [mon["name"] for mon in POKEMON_DATA]

class PokepelagoItem(Item):
    game: str = "Pokepelago"


# Maps filler category names (used by FillerWeights option) to the items they contain.
# Traps are excluded here — they are controlled separately by the trap_chance option.
FILLER_ITEM_CATEGORIES: dict = {
    "master_ball": ["Master Ball"],
    "key_items":   ["Pokedex", "Pokegear"],
    "splash":      ["Magikarp used Splash - but nothing happened!"],
}