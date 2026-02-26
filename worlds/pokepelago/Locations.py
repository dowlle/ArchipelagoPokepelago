from BaseClasses import Location
from .Items import pokemon_names

# A random high number for locations (different from the item offset!)
LOCATION_ID_OFFSET = 8573000

# A dictionary of all the locations where items can be hidden.
location_table = {f"Guess {name}": LOCATION_ID_OFFSET + (i + 1) for i, name in enumerate(pokemon_names)}

# We create a custom class for our locations
class PokepelagoLocation(Location):
    game: str = "Pokepelago"