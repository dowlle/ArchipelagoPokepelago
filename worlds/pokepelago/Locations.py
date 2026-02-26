from BaseClasses import Location
from .data import POKEMON_DATA

# A random high number for locations (different from the item offset!)
LOCATION_ID_OFFSET = 8573000

# A dictionary of all the locations where items can be hidden.
location_table = {f"Guess {mon['name']}": LOCATION_ID_OFFSET + mon["id"] for mon in POKEMON_DATA}

# We create a custom class for our locations
class PokepelagoLocation(Location):
    game: str = "Pokepelago"