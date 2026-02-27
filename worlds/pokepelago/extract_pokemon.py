import json

# Input file from Client
json_path = r"f:/pythonProjects/PokepelagoClient/src/data/pokemon_metadata.json"
output_path = r"f:/pythonProjects/ArchipelagoPokepelago/worlds/pokepelago/pokemon_data_gen3.txt"

with open(json_path, 'r', encoding='utf-8') as f:
    metadata = json.load(f)

# Generation 3 ends at 386 (Deoxys)
pokemon_list = []
for i in range(1, 387):
    str_id = str(i)
    if str_id in metadata:
        mon = metadata[str_id]
        
        # Format types nicely with uppercase first letter
        types = [t.capitalize() for t in mon.get('types', [])]
        
        # Escape quotes if necessary in name (e.g. Farfetch'd)
        name = mon['name'].replace('\'', '\\\'') if '\'' in mon['name'] else mon['name']
        name_str = f'"{name}"' if "'" not in name else f'"{name}"' # Just use double quotes for the string
        
        pokemon_list.append(f'    {{"id": {i}, "name": {name_str}, "types": {json.dumps(types)}}},')

with open(output_path, 'w', encoding='utf-8') as out_f:
    out_f.write("POKEMON_DATA = [\n")
    for line in pokemon_list:
        out_f.write(line + "\n")
    out_f.write("]\n")

print(f"Successfully wrote {len(pokemon_list)} Pokémon to {output_path}")
