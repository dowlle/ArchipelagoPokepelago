"""
Pull encounter, species, and evolution data from PokeAPI GraphQL and generate route_data.py.

Uses 3 bulk GraphQL queries instead of thousands of REST calls:
1. All encounters for Pokemon 1-1025 (~60k records)
2. All species data (is_baby, is_legendary, is_mythical, evolution_chain_id)
3. All evolution records (triggers, items)

Usage:
    python -m worlds.pokepelago.tools.build_route_data
    # Or: .venv/Scripts/python.exe worlds/pokepelago/tools/build_route_data.py

Requires: requests (pip install requests)
"""
import json
import sys
from collections import defaultdict
from pathlib import Path

try:
    import requests
except ImportError:
    print("ERROR: requests not installed. Run: pip install requests")
    sys.exit(1)

GRAPHQL_URL = "https://beta.pokeapi.co/graphql/v1beta"

# Marker for the hand-maintained tail of route_data.py (ROUTE_GROUPS, ROUTE_TO_GROUP,
# compute_badge_requirement + helpers). The generator does not emit those sections;
# _read_preserved_tail copies everything from this line to EOF forward on regen.
TAIL_SENTINEL = "# ==== HAND-MAINTAINED TAIL (preserved across build_route_data.py regen) ===="


def _read_preserved_tail(output_path: "Path") -> "str | None":
    """Return the hand-maintained tail (sentinel line through EOF) of an existing
    route_data.py, or None if the file or the sentinel is missing."""
    if not output_path.exists():
        return None
    existing = output_path.read_text(encoding="utf-8")
    idx = existing.find(TAIL_SENTINEL)
    if idx == -1:
        return None
    return existing[idx:]
MAX_POKEMON_ID = 1025

# Region dex ranges (mirrors data.py)
REGION_RANGES: dict[str, tuple[int, int]] = {
    "Kanto": (1, 151), "Johto": (152, 251), "Hoenn": (252, 386),
    "Sinnoh": (387, 493), "Unova": (494, 649), "Kalos": (650, 721),
    "Alola": (722, 809), "Galar": (810, 898), "Hisui": (899, 905),
    "Paldea": (906, 1025),
}

# Stone item name mapping (PokeAPI name → our short name)
STONE_MAP: dict[str, str] = {
    "fire-stone": "fire", "water-stone": "water", "thunder-stone": "thunder",
    "leaf-stone": "leaf", "moon-stone": "moon", "sun-stone": "sun",
    "shiny-stone": "shiny", "dusk-stone": "dusk", "dawn-stone": "dawn",
    "ice-stone": "ice",
}

# Cache dir for raw GraphQL responses
CACHE_DIR = Path(__file__).parent / ".api_cache"


def get_pokemon_region(mon_id: int) -> str:
    for region_name, (lo, hi) in REGION_RANGES.items():
        if lo <= mon_id <= hi:
            return region_name
    return "Unknown"


# ── GraphQL queries ──────────────────────────────────────────────────────────

def gql_query(query: str, cache_key: str) -> dict:
    """Execute a GraphQL query with file-based caching."""
    CACHE_DIR.mkdir(exist_ok=True)
    cache_file = CACHE_DIR / f"gql_{cache_key}.json"

    if cache_file.exists():
        print(f"  Using cached {cache_key}")
        return json.loads(cache_file.read_text(encoding="utf-8"))

    print(f"  Fetching {cache_key} from GraphQL API...")
    resp = requests.post(GRAPHQL_URL, json={"query": query}, timeout=120)
    resp.raise_for_status()
    data = resp.json()

    if "errors" in data:
        print(f"  GraphQL errors: {data['errors']}")
        sys.exit(1)

    cache_file.write_text(json.dumps(data), encoding="utf-8")
    return data


def fetch_all_encounters() -> list[dict]:
    """Fetch all encounter records for Pokemon 1-1025."""
    query = """
    {
        pokemon_v2_encounter(where: {pokemon_id: {_lte: 1025}}) {
            pokemon_id
            min_level
            pokemon_v2_locationarea {
                name
                pokemon_v2_location {
                    name
                    pokemon_v2_region { name }
                }
            }
            pokemon_v2_version { name }
        }
    }
    """
    data = gql_query(query, "encounters")
    return data["data"]["pokemon_v2_encounter"]


def fetch_all_species() -> list[dict]:
    """Fetch species data for Pokemon 1-1025."""
    query = """
    {
        pokemon_v2_pokemonspecies(where: {id: {_lte: 1025}}, order_by: {id: asc}) {
            id
            name
            is_baby
            is_legendary
            is_mythical
            evolution_chain_id
            evolves_from_species_id
        }
    }
    """
    data = gql_query(query, "species")
    return data["data"]["pokemon_v2_pokemonspecies"]


def fetch_all_evolutions() -> list[dict]:
    """Fetch all evolution records with triggers and items."""
    query = """
    {
        pokemon_v2_pokemonevolution {
            evolved_species_id
            min_level
            pokemon_v2_evolutiontrigger { name }
            pokemon_v2_item { name }
        }
    }
    """
    data = gql_query(query, "evolutions")
    return data["data"]["pokemon_v2_pokemonevolution"]


# ── Data processing ──────────────────────────────────────────────────────────

def collapse_location_name(area_name: str) -> str:
    """Collapse sub-area names into parent location names.

    Aggressively merges sub-areas into their parent to reduce route count.
    All Pokemon from sub-areas get unioned into the parent route.
    """
    import re
    result = area_name

    # Floor suffixes: mt-moon-1f, mt-moon-b1f → mt-moon
    result = re.sub(r'-\d+f$', '', result)
    result = re.sub(r'-b\d+f$', '', result)

    # Directional suffixes: route-1-south, route-16-east → route-1, route-16
    result = re.sub(r'-(south|north|east|west|main|upper|lower|inner|outer)$', '', result)
    result = re.sub(r'-(entrance|inside|outside|interior|back|front|top|bottom)$', '', result)

    # Sub-area rooms: lost-cave-room-3 → lost-cave, viridian-forest-zone-1 → viridian-forest
    result = re.sub(r'-room-\d+$', '', result)
    result = re.sub(r'-unknown-area-\d+$', '', result)

    # Named sub-areas in cities: cianwood-city-kirks-house → cianwood-city
    result = re.sub(r'-(pokemon-center|kirks-house|manias-house|bills-house|'
                    r'fighting-dojo|silph-co-\w+|celadon-mansion|ss-anne-dock|'
                    r'cave-gate|square|lab|mart)$', '', result)

    # Safari/park zones: johto-safari-zone-zone-wetland → johto-safari-zone
    result = re.sub(r'-zone-[\w-]+$', '', result)

    # Numbered areas: great-marsh-area-1 → great-marsh, kanto-safari-zone-area-1-east → kanto-safari-zone
    result = re.sub(r'-area-\d+(-\w+)?$', '', result)

    # Hauoli/trainer school etc: alola-route-1-hauoli-outskirts, alola-route-1-trainers-school
    result = re.sub(r'-(hauoli-outskirts|trainers-school)$', '', result)

    return result


def process_encounters(raw_encounters: list[dict]) -> tuple[
    dict[str, dict],           # routes: route_key → {display_name, region, pokemon: {id: min_level}}
    dict[int, list[str]],      # pokemon_routes: pokemon_id → [route_keys]
]:
    """Process raw encounter data into route structures."""
    routes: dict[str, dict] = {}
    pokemon_routes: dict[int, list[str]] = defaultdict(list)

    for enc in raw_encounters:
        pokemon_id = enc["pokemon_id"]
        min_level = enc["min_level"]
        area = enc["pokemon_v2_locationarea"]
        location = area["pokemon_v2_location"]
        region_data = location["pokemon_v2_region"]

        # Collapse sub-areas into parent location
        route_key = collapse_location_name(area["name"])

        # Determine region from the location's region field
        region_name = region_data["name"].title() if region_data else get_pokemon_region(pokemon_id)

        if route_key not in routes:
            display_name = route_key.replace("-", " ").title()
            routes[route_key] = {
                "display_name": display_name,
                "region": region_name,
                "pokemon": {},
            }

        # Keep lowest encounter level per Pokemon per route
        current = routes[route_key]["pokemon"].get(pokemon_id)
        if current is None or min_level < current:
            routes[route_key]["pokemon"][pokemon_id] = min_level

        if route_key not in pokemon_routes[pokemon_id]:
            pokemon_routes[pokemon_id].append(route_key)

    # ── Route merging: keep only numbered routes, merge everything else ──
    # Named routes (Route 1, Route 101, etc.) are the main progression routes.
    # Caves, cities, forests, etc. merge into "{Region} Wilds".
    # Exceptions: Hisui (5 main areas), Galar (pokearth areas), Paldea (biomes),
    # and virtual routes are kept as-is since they use different naming.
    import re
    KEEP_PATTERNS = [
        re.compile(r'^(kanto|johto|hoenn|sinnoh|unova|kalos|alola)-route-\d+'),  # Numbered routes
        re.compile(r'^(kanto|johto|hoenn|sinnoh|unova|kalos|alola)-sea-route-\d+'),  # Sea routes
        re.compile(r'^(hoenn|kanto)-victory-road'),  # Victory roads (large areas)
        re.compile(r'^(hoenn|johto|kanto)-safari'),   # Safari zones (large areas)
        re.compile(r'^galar-'),     # Galar uses Serebii area names (already good)
        re.compile(r'^hisui-'),     # Hisui has 5 main areas
        re.compile(r'^paldea-'),    # Paldea uses biome names
        re.compile(r'^virtual-'),   # Virtual routes (starters, fossils, etc.)
        re.compile(r'^roaming-'),   # Roaming Pokemon
    ]

    def should_keep(route_key: str) -> bool:
        return any(p.match(route_key) for p in KEEP_PATTERNS)

    # Merge non-route locations into "{Region} Wilds"
    to_merge = [rk for rk in routes if not should_keep(rk)]
    for rk in to_merge:
        info = routes.pop(rk)
        catchall_key = f"{info['region'].lower()}-wilds"
        if catchall_key not in routes:
            routes[catchall_key] = {
                "display_name": f"{info['region']} Wilds",
                "region": info["region"],
                "pokemon": {},
            }
        for pid, lvl in info["pokemon"].items():
            current = routes[catchall_key]["pokemon"].get(pid)
            if current is None or lvl < current:
                routes[catchall_key]["pokemon"][pid] = lvl

    # Rebuild pokemon_routes after merging
    pokemon_routes = defaultdict(list)
    for route_key, info in routes.items():
        for pid in info["pokemon"]:
            if route_key not in pokemon_routes[pid]:
                pokemon_routes[pid].append(route_key)

    return routes, dict(pokemon_routes)


def process_species(raw_species: list[dict]) -> tuple[
    set[int],                  # baby_ids
    set[int],                  # legendary_ids
    set[int],                  # mythical_ids
    dict[int, int],            # species_to_chain: species_id → evolution_chain_id
    dict[int, int],            # pre_evolution: species_id → immediate pre-evo species_id
]:
    """Extract species flags, chain mappings, and the immediate pre-evolution map."""
    baby_ids: set[int] = set()
    legendary_ids: set[int] = set()
    mythical_ids: set[int] = set()
    species_to_chain: dict[int, int] = {}
    pre_evolution: dict[int, int] = {}

    for sp in raw_species:
        sid = sp["id"]
        if sp["is_baby"]:
            baby_ids.add(sid)
        if sp["is_legendary"]:
            legendary_ids.add(sid)
        if sp["is_mythical"]:
            mythical_ids.add(sid)
        if sp["evolution_chain_id"]:
            species_to_chain[sid] = sp["evolution_chain_id"]
        # Immediate parent in the evolution line (None for base forms). Used by
        # compute_badge_requirement to keep badge gates monotone within a line.
        parent = sp.get("evolves_from_species_id")
        if parent and sid <= MAX_POKEMON_ID and parent <= MAX_POKEMON_ID:
            pre_evolution[sid] = parent

    return baby_ids, legendary_ids, mythical_ids, species_to_chain, pre_evolution


def process_evolutions(
    raw_evolutions: list[dict],
    species_to_chain: dict[int, int],
) -> tuple[
    dict[int, frozenset[int]],  # families: base_id → all IDs
    dict[int, int],             # family_base: any_id → base_id
    set[int],                   # trade_evo_ids
    dict[str, set[int]],        # stone_evo_groups
    dict[int, int],             # evolution_min_level: evolved_id → min level (level-up evos only)
]:
    """Build evolution families, identify trade evos and stone evos."""
    # Group species by chain_id to build families
    chain_members: dict[int, set[int]] = defaultdict(set)
    for species_id, chain_id in species_to_chain.items():
        if species_id <= MAX_POKEMON_ID:
            chain_members[chain_id].add(species_id)

    # Base form is the lowest ID in each chain
    families: dict[int, frozenset[int]] = {}
    family_base: dict[int, int] = {}
    for chain_id, members in chain_members.items():
        base_id = min(members)
        families[base_id] = frozenset(members)
        for pid in members:
            family_base[pid] = base_id

    # Extract trade evos, stone evos, and level-up evolution levels from triggers
    trade_evo_ids: set[int] = set()
    stone_evo_groups: dict[str, set[int]] = defaultdict(set)
    evolution_min_level: dict[int, int] = {}

    for evo in raw_evolutions:
        evolved_id = evo["evolved_species_id"]
        if evolved_id > MAX_POKEMON_ID:
            continue

        trigger = evo.get("pokemon_v2_evolutiontrigger", {})
        trigger_name = trigger.get("name", "") if trigger else ""

        item = evo.get("pokemon_v2_item", {})
        item_name = item.get("name", "") if item else ""

        if trigger_name == "trade":
            trade_evo_ids.add(evolved_id)

        if trigger_name == "use-item" and item_name in STONE_MAP:
            stone_evo_groups[STONE_MAP[item_name]].add(evolved_id)

        # Level required for a level-up evolution. Only level-up evolutions with an
        # explicit min_level get an entry; stone/trade/friendship/other-trigger
        # evolutions are intentionally absent (they have no level gate, so the
        # evolved form simply inherits its pre-evolution's badge tier). When a
        # species has multiple level-up rows, keep the lowest level.
        if trigger_name == "level-up" and evo.get("min_level"):
            lvl = evo["min_level"]
            if evolved_id not in evolution_min_level or lvl < evolution_min_level[evolved_id]:
                evolution_min_level[evolved_id] = lvl

    return families, family_base, trade_evo_ids, dict(stone_evo_groups), evolution_min_level


# ── Output writers ───────────────────────────────────────────────────────────

def write_route_data(
    routes: dict[str, dict],
    pokemon_routes: dict[int, list[str]],
    families: dict[int, frozenset[int]],
    family_base: dict[int, int],
    trade_evo_ids: set[int],
    stone_evo_groups: dict[str, set[int]],
    baby_ids: set[int],
    legendary_ids: set[int],
    mythical_ids: set[int],
    orphans_by_region: dict[str, set[int]],
    pre_evolution: dict[int, int],
    evolution_min_level: dict[int, int],
) -> None:
    """Write the generated route_data.py file."""
    output_path = Path(__file__).parent.parent / "route_data.py"
    lines: list[str] = []

    lines += [
        '"""',
        "Auto-generated by tools/build_route_data.py from PokeAPI GraphQL.",
        "Do not edit manually — re-run the build script to update.",
        "",
        "Run: python -m worlds.pokepelago.tools.build_route_data",
        '"""',
        "",
        "# Default badge -> max level thresholds (0 badges = up to lv10, 8 badges = all)",
        "BADGE_LEVEL_THRESHOLDS: list[int] = [10, 20, 30, 40, 50, 60, 70, 100]",
        "",
    ]

    # Route data
    lines += ["", "# Route encounters: route_key -> {display_name, region, pokemon: {id: min_level}}"]
    lines += [f"ROUTE_DATA: dict[str, dict] = {{"]
    for route_key in sorted(routes.keys()):
        route = routes[route_key]
        pokemon_str = ", ".join(f"{pid}: {lvl}" for pid, lvl in sorted(route["pokemon"].items()))
        lines += [
            f'    "{route_key}": {{',
            f'        "display_name": "{route["display_name"]}",',
            f'        "region": "{route["region"]}",',
            f'        "pokemon": {{{pokemon_str}}},',
            f"    }},",
        ]
    lines += ["}", ""]

    # Pokemon → routes
    lines += ["", "# Pokemon ID -> list of route keys where it can be encountered"]
    lines += ["POKEMON_ROUTES: dict[int, list[str]] = {"]
    for pid in sorted(pokemon_routes.keys()):
        r_list = ", ".join(f'"{r}"' for r in sorted(pokemon_routes[pid]))
        lines += [f"    {pid}: [{r_list}],"]
    lines += ["}", ""]

    # Evolution families
    lines += ["", "# Evolution families: base_pokemon_id -> frozenset of all IDs in the family"]
    lines += ["EVOLUTION_FAMILIES: dict[int, frozenset[int]] = {"]
    for base_id in sorted(families.keys()):
        ids_str = ", ".join(str(i) for i in sorted(families[base_id]))
        lines += [f"    {base_id}: frozenset([{ids_str}]),"]
    lines += ["}", ""]

    # Family base reverse lookup
    lines += ["", "# Any Pokemon ID -> base form ID of its evolution family"]
    lines += ["FAMILY_BASE: dict[int, int] = {"]
    for pid in sorted(family_base.keys()):
        lines += [f"    {pid}: {family_base[pid]},"]
    lines += ["}", ""]

    # Immediate pre-evolution map (species_id -> the species it evolves FROM).
    # Base forms are absent. Drives the monotone clamp in compute_badge_requirement.
    lines += ["", "# Any Pokemon ID -> the species ID it evolves directly FROM (base forms absent)"]
    lines += ["PRE_EVOLUTION: dict[int, int] = {"]
    for pid in sorted(pre_evolution.keys()):
        lines += [f"    {pid}: {pre_evolution[pid]},"]
    lines += ["}", ""]

    # Level required for level-up evolutions (stone/trade/friendship evos absent).
    lines += ["", "# Evolved Pokemon ID -> level required for a level-up evolution (level-up evos only)"]
    lines += ["EVOLUTION_MIN_LEVEL: dict[int, int] = {"]
    for pid in sorted(evolution_min_level.keys()):
        lines += [f"    {pid}: {evolution_min_level[pid]},"]
    lines += ["}", ""]

    # API-derived categorization sets
    lines += ["", "# ── API-derived categorization sets ──"]
    lines += ["# Auto-generated from PokeAPI. Compare with hand-maintained sets in data.py.", ""]
    _write_frozenset(lines, "API_BABY_IDS", baby_ids)
    _write_frozenset(lines, "API_LEGENDARY_IDS", legendary_ids)
    _write_frozenset(lines, "API_MYTHICAL_IDS", mythical_ids)
    _write_frozenset(lines, "API_TRADE_EVO_IDS", trade_evo_ids)
    lines += [""]
    lines += ["API_STONE_EVO_GROUPS: dict[str, frozenset[int]] = {"]
    for stone in sorted(stone_evo_groups.keys()):
        ids_str = ", ".join(str(i) for i in sorted(stone_evo_groups[stone]))
        lines += [f'    "{stone}": frozenset([{ids_str}]),']
    lines += ["}", ""]

    # Orphans
    lines += ["", "# ── Orphan Pokemon (no encounter data, need virtual routes) ──"]
    all_orphans: set[int] = set()
    for region_name, orphans in sorted(orphans_by_region.items()):
        if orphans:
            all_orphans.update(orphans)
            ids_str = ", ".join(str(i) for i in sorted(orphans))
            lines += [f"# {region_name} ({len(orphans)} orphans): [{ids_str}]"]
    lines += [f"# Total orphans: {len(all_orphans)}", ""]
    _write_frozenset(lines, "ORPHAN_IDS", all_orphans)
    lines += [""]

    # Preserve the hand-maintained tail (ROUTE_GROUPS, ROUTE_TO_GROUP, and
    # compute_badge_requirement + helpers). The generator does NOT emit those, so
    # without this they would be wiped on every regen. Everything from the sentinel
    # line to EOF in the existing file is copied forward verbatim.
    tail = _read_preserved_tail(output_path)
    if tail is None:
        raise SystemExit(
            f"ERROR: {output_path} has no '{TAIL_SENTINEL}' sentinel.\n"
            f"The generator does not emit ROUTE_GROUPS / ROUTE_TO_GROUP / "
            f"compute_badge_requirement; writing now would drop them. Restore the "
            f"sentinel and the hand-maintained tail in route_data.py first, then re-run."
        )

    generated = "\n".join(lines).rstrip("\n")
    output_path.write_text(generated + "\n\n" + tail, encoding="utf-8")
    print(f"\nWrote {output_path} (generated {len(lines)} lines + preserved tail)")


def _write_frozenset(lines: list[str], name: str, ids: set[int]) -> None:
    ids_str = ", ".join(str(i) for i in sorted(ids))
    lines += [f"{name}: frozenset[int] = frozenset([{ids_str}])"]


def write_validation_report(
    trade_evo_ids: set[int],
    stone_evo_groups: dict[str, set[int]],
    baby_ids: set[int],
    legendary_ids: set[int],
    mythical_ids: set[int],
) -> None:
    """Compare API data with hand-maintained sets in data.py."""
    report_path = Path(__file__).parent / "validation_report.txt"

    try:
        sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))
        from worlds.pokepelago.data import (
            BABY_IDS, TRADE_EVO_IDS, LEGENDARY_SUB_IDS, LEGENDARY_BOX_IDS,
            LEGENDARY_MYTHIC_IDS, STONE_EVO_GROUPS,
        )
    except ImportError:
        print("  WARNING: Could not import data.py for validation")
        return

    lines: list[str] = [
        "Validation Report: API data vs hand-maintained sets in data.py",
        "=" * 70, "",
    ]

    _compare(lines, "BABY_IDS", BABY_IDS, baby_ids)
    _compare(lines, "TRADE_EVO_IDS", TRADE_EVO_IDS, trade_evo_ids)
    _compare(lines, "LEGENDARY_MYTHIC_IDS", LEGENDARY_MYTHIC_IDS, mythical_ids)
    _compare(lines, "LEGENDARY_SUB+BOX_IDS", LEGENDARY_SUB_IDS | LEGENDARY_BOX_IDS, legendary_ids)

    for stone in sorted(set(list(STONE_EVO_GROUPS.keys()) + list(stone_evo_groups.keys()))):
        current = STONE_EVO_GROUPS.get(stone, frozenset())
        api = stone_evo_groups.get(stone, set())
        _compare(lines, f"STONE[{stone}]", current, api)

    lines += [
        "", "Cannot auto-detect (manual curation required):",
        "  - Ultra Beast status", "  - Paradox Pokemon status",
        "  - Fossil Pokemon status", "  - Legendary sub vs box tier",
    ]

    report_path.write_text("\n".join(lines), encoding="utf-8")
    print(f"Wrote {report_path}")


def _compare(lines: list[str], name: str, current: frozenset | set, api: set) -> None:
    current_set = set(current)
    missing = current_set - api
    extra = api - current_set
    lines += [f"{name}: current={len(current_set)}, api={len(api)}"]
    if missing:
        lines += [f"  In current but NOT in API: {sorted(missing)}"]
    if extra:
        lines += [f"  In API but NOT in current: {sorted(extra)}"]
    if not missing and not extra:
        lines += [f"  MATCH"]
    lines += [""]


# ── Main ─────────────────────────────────────────────────────────────────────

def merge_serebii_data(
    routes: dict[str, dict],
    pokemon_routes: dict[int, list[str]],
) -> tuple[int, int]:
    """Merge Serebii encounter data into the PokeAPI routes.

    For routes in both sources: union Pokemon lists, keep lowest levels.
    For Serebii-only routes: add as new routes.
    Returns (routes_added, pokemon_added) counts.
    """
    serebii_file = Path(__file__).parent / "serebii_encounters.json"
    if not serebii_file.exists():
        print("  No serebii_encounters.json found — skipping merge")
        return 0, 0

    serebii_data = json.loads(serebii_file.read_text(encoding="utf-8"))
    routes_added = 0
    pokemon_before = len(pokemon_routes)

    for route_key, route_info in serebii_data.items():
        pokemon_map = {int(pid): lvl for pid, lvl in route_info["pokemon"].items()}

        if route_key in routes:
            # Existing route: merge Pokemon, keep lowest level
            for pid, level in pokemon_map.items():
                current = routes[route_key]["pokemon"].get(pid)
                if current is None or level < current:
                    routes[route_key]["pokemon"][pid] = level
        else:
            # New route from Serebii
            routes[route_key] = {
                "display_name": route_info["display_name"],
                "region": route_info["region"],
                "pokemon": pokemon_map,
            }
            routes_added += 1

        # Update reverse lookup
        for pid in pokemon_map:
            if pid <= MAX_POKEMON_ID:
                if pid not in pokemon_routes:
                    pokemon_routes[pid] = []
                if route_key not in pokemon_routes[pid]:
                    pokemon_routes[pid].append(route_key)

    pokemon_added = len(pokemon_routes) - pokemon_before
    return routes_added, pokemon_added


def add_virtual_routes(
    routes: dict[str, dict],
    pokemon_routes: dict[int, list[str]],
    families: dict[int, frozenset[int]],
    family_base: dict[int, int],
    mythical_ids: set[int],
) -> int:
    """Add virtual routes for Pokemon unobtainable through wild encounters.

    Categories:
    - Professor's Lab (per region): starters and their evolutions
    - Fossil Lab: fossil revival evolutions without wild encounters
    - Mystery Gift: mythical/event-only Pokemon
    - Location-based: legendaries and special Pokemon at their in-game locations
    """
    from worlds.pokepelago.data import POKEMON_DATA, STARTERS_BY_REGION, FOSSIL_IDS

    added = 0

    def _add_route(key: str, display: str, region: str, pokemon_ids: set[int], level: int = 5) -> None:
        nonlocal added
        pokemon_ids = {pid for pid in pokemon_ids if pid <= MAX_POKEMON_ID}
        if not pokemon_ids:
            return
        routes[key] = {
            "display_name": display,
            "region": region,
            "pokemon": {pid: level for pid in pokemon_ids},
        }
        for pid in pokemon_ids:
            if pid not in pokemon_routes:
                pokemon_routes[pid] = []
            if key not in pokemon_routes[pid]:
                pokemon_routes[pid].append(key)
        added += 1

    # ── Starters: Professor's Lab per region ──
    all_starter_family_ids: dict[str, set[int]] = {}
    for region, names in STARTERS_BY_REGION.items():
        if not names:
            continue
        region_starter_ids: set[int] = set()
        name_lower = {n.lower() for n in names}
        for mon in POKEMON_DATA:
            if mon["name"].lower() in name_lower:
                base = family_base.get(mon["id"], mon["id"])
                family = families.get(base, frozenset([mon["id"]]))
                region_starter_ids.update(family)
        # Include ALL starter family members (starters are given in the lab,
        # even if they also appear wild elsewhere — lab is the canonical route)
        if region_starter_ids:
            _add_route(f"virtual-professors-lab-{region.lower()}", f"Professor's Lab ({region})", region, region_starter_ids)
            all_starter_family_ids[region] = region_starter_ids

    # ── Fossils: Fossil Lab ──
    # Only fossil evolutions that are still orphaned (base fossils may have routes)
    fossil_orphans = {pid for pid in FOSSIL_IDS if pid not in pokemon_routes and pid <= MAX_POKEMON_ID}
    if fossil_orphans:
        _add_route("virtual-fossil-lab", "Fossil Lab", "Kanto", fossil_orphans, level=20)

    # ── Mythicals: Mystery Gift ──
    mythical_orphans = {pid for pid in mythical_ids if pid not in pokemon_routes and pid <= MAX_POKEMON_ID}
    if mythical_orphans:
        _add_route("virtual-mystery-gift", "Mystery Gift", "Kanto", mythical_orphans, level=50)

    # ── Location-based virtual routes for remaining true orphans ──

    # Galar: Energy Plant (box legendaries)
    _add_route("virtual-energy-plant", "Energy Plant", "Galar",
               {888, 889, 890}, level=70)  # Zacian, Zamazenta, Eternatus

    # Galar: Tower of Two Fists (Isle of Armor)
    _add_route("virtual-tower-of-two-fists", "Tower of Two Fists", "Galar",
               {891, 892}, level=60)  # Kubfu, Urshifu

    # Galar: Split-Decision Ruins (Crown Tundra)
    _add_route("virtual-split-decision-ruins", "Split-Decision Ruins", "Galar",
               {894, 895}, level=70)  # Regieleki, Regidrago

    # Hisui: Crimson Mirelands post-game
    _add_route("virtual-hisui-post-game", "Ancient Retreat", "Hisui",
               {905}, level=70)  # Enamorus

    # Paldea: Area Zero (Paradox Pokemon + box legendaries)
    _add_route("virtual-area-zero", "Area Zero", "Paldea",
               {984, 985, 986, 987, 988, 989,    # Ancient Paradox
                990, 991, 992, 993, 994, 995,      # Future Paradox
                1005, 1006,                         # Roaring Moon, Iron Valiant
                1007, 1008},                        # Koraidon, Miraidon
               level=50)

    # Paldea: Paldean Shrines (Ruinous Quartet)
    _add_route("virtual-paldean-shrines", "Paldean Shrines", "Paldea",
               {1001, 1002, 1003, 1004}, level=60)  # Wo-Chien, Chien-Pao, Ting-Lu, Chi-Yu

    # Paldea: Kitakami Wilds (Teal Mask DLC)
    _add_route("virtual-kitakami-wilds", "Kitakami Wilds", "Paldea",
               {1012, 1013,                         # Poltchageist, Sinistcha
                1014, 1015, 1016, 1017},             # Okidogi, Munkidori, Fezandipiti, Ogerpon
               level=50)

    # Paldea: Blueberry Academy (Indigo Disk DLC)
    _add_route("virtual-blueberry-academy", "Blueberry Academy", "Paldea",
               {1009, 1010,                         # Walking Wake, Iron Leaves
                1020, 1021, 1022, 1023,              # Gouging Fire, Raging Bolt, Iron Boulder, Iron Crown
                1024},                               # Terapagos
               level=60)

    # Paldea: Paldea Overworld (Gimmighoul roaming coins)
    _add_route("virtual-paldea-overworld", "Paldea Overworld", "Paldea",
               {999, 1000}, level=5)  # Gimmighoul, Gholdengo

    return added


def main() -> None:
    merge_serebii = "--merge-serebii" in sys.argv

    print("PokeAPI Route Data Builder (GraphQL)")
    if merge_serebii:
        print("  [--merge-serebii] Will merge Serebii Gen 8-9 data")
    print("=" * 60)

    # 3 bulk queries
    raw_encounters = fetch_all_encounters()
    print(f"  Encounters: {len(raw_encounters)} records")

    raw_species = fetch_all_species()
    print(f"  Species: {len(raw_species)} records")

    raw_evolutions = fetch_all_evolutions()
    print(f"  Evolutions: {len(raw_evolutions)} records")

    # Process
    print("\nProcessing encounters...")
    routes, pokemon_routes = process_encounters(raw_encounters)
    print(f"  {len(routes)} routes, {len(pokemon_routes)} Pokemon with encounters")

    # Merge Serebii data if requested
    if merge_serebii:
        print("\nMerging Serebii Gen 8-9 data...")
        routes_added, pokemon_added = merge_serebii_data(routes, pokemon_routes)
        print(f"  {routes_added} new routes added, {pokemon_added} new Pokemon covered")
        print(f"  Total: {len(routes)} routes, {len(pokemon_routes)} Pokemon with encounters")

    print("\nProcessing species...")
    baby_ids, legendary_ids, mythical_ids, species_to_chain, pre_evolution = process_species(raw_species)

    print("Processing evolutions...")
    families, family_base, trade_evo_ids, stone_evo_groups, evolution_min_level = process_evolutions(
        raw_evolutions, species_to_chain
    )
    print(f"  {len(families)} families, {len(trade_evo_ids)} trade evos, {len(stone_evo_groups)} stone types")

    # Virtual routes for orphans
    print("\nAdding virtual routes...")
    virtual_added = add_virtual_routes(routes, pokemon_routes, families, family_base, mythical_ids)
    print(f"  {virtual_added} virtual routes added, {len(pokemon_routes)} Pokemon now with routes")

    # Orphans
    orphans_by_region: dict[str, set[int]] = {}
    for region_name, (lo, hi) in REGION_RANGES.items():
        region_ids = set(range(lo, hi + 1))
        with_routes = {pid for pid in region_ids if pid in pokemon_routes}
        orphans = region_ids - with_routes
        if orphans:
            orphans_by_region[region_name] = orphans

    # Summary
    total_with_routes = len(pokemon_routes)
    total_orphans = MAX_POKEMON_ID - total_with_routes
    print(f"\n{'='*60}")
    print(f"SUMMARY")
    print(f"{'='*60}")
    print(f"Routes: {len(routes)}")
    print(f"Pokemon with encounters: {total_with_routes}/{MAX_POKEMON_ID}")
    print(f"Orphans: {total_orphans}")
    print(f"Evolution families: {len(families)}")
    print(f"Trade evos: {len(trade_evo_ids)}")
    print(f"Stone types: {len(stone_evo_groups)}")
    print(f"Babies: {len(baby_ids)}, Legendaries: {len(legendary_ids)}, Mythicals: {len(mythical_ids)}")
    print()
    for region_name, orphans in sorted(orphans_by_region.items()):
        print(f"  {region_name}: {len(orphans)} orphans")

    # Write
    write_route_data(routes, pokemon_routes, families, family_base,
                     trade_evo_ids, stone_evo_groups, baby_ids, legendary_ids,
                     mythical_ids, orphans_by_region, pre_evolution, evolution_min_level)

    write_validation_report(trade_evo_ids, stone_evo_groups, baby_ids,
                            legendary_ids, mythical_ids)

    print("\nDone!")


if __name__ == "__main__":
    main()
