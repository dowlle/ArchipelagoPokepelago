"""Export route/line/badge data as JSON for the PokepelagoClient."""
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent.parent))

from worlds.pokepelago.route_data import (
    ROUTE_DATA, ROUTE_GROUPS, ROUTE_TO_GROUP, POKEMON_ROUTES,
    FAMILY_BASE, EVOLUTION_FAMILIES, BADGE_LEVEL_THRESHOLDS,
    compute_badge_requirement,
)
from worlds.pokepelago.Items import ROUTE_KEY_NAMES, LINE_UNLOCK_NAMES
from worlds.pokepelago.data import POKEMON_DATA

name_map = {m["id"]: m["name"] for m in POKEMON_DATA}

# Route info: individual routes (for display) + group entries (for gate checks)
route_info = {}
for rk, rd in ROUTE_DATA.items():
    route_info[rk] = {
        "name": rd["display_name"],
        "region": rd["region"],
        "count": len(rd["pokemon"]),
    }
# Add group entries so the client can display group names and match regions
for gk, ginfo in ROUTE_GROUPS.items():
    total_pokemon = sum(
        len(ROUTE_DATA[rk]["pokemon"]) for rk in ginfo["routes"] if rk in ROUTE_DATA
    )
    route_info[gk] = {
        "name": ginfo["display_name"],
        "region": ginfo["region"],
        "count": total_pokemon,
    }

# Pokemon → route keys (for gate checks)
# Resolve individual routes to their group key so the client can match
# received group-based Route Key items to Pokemon accessibility.
pokemon_routes: dict[str, list[str]] = {}
for pid, routes in POKEMON_ROUTES.items():
    resolved: list[str] = []
    seen: set[str] = set()
    for rk in routes:
        # Translate to group key if grouped, else keep individual key
        lookup = ROUTE_TO_GROUP.get(rk, rk)
        if lookup not in seen:
            resolved.append(lookup)
            seen.add(lookup)
    if resolved:
        pokemon_routes[str(pid)] = resolved

# Pokemon → base form ID (for line locks)
family_base = {str(pid): base for pid, base in FAMILY_BASE.items()}

# Route key → item name (for matching received items)
route_key_items = ROUTE_KEY_NAMES  # route_key → "Route Name Key"

# Base ID → line unlock item name
line_unlock_items = {str(base): name for base, name in LINE_UNLOCK_NAMES.items()}

# Per-Pokemon min encounter level (for badge level display)
pokemon_levels = {}
for pid, routes in POKEMON_ROUTES.items():
    min_level = 100
    for rk in routes:
        rd = ROUTE_DATA.get(rk)
        if rd:
            lvl = rd["pokemon"].get(pid)
            if lvl and lvl < min_level:
                min_level = lvl
    # Also check base form levels for evo-only Pokemon
    base = FAMILY_BASE.get(pid, pid)
    if base != pid:
        for rk in POKEMON_ROUTES.get(base, []):
            rd = ROUTE_DATA.get(rk)
            if rd:
                lvl = rd["pokemon"].get(base)
                if lvl and lvl < min_level:
                    min_level = lvl
    if min_level < 100:
        pokemon_levels[str(pid)] = min_level

# Authoritative per-Pokemon badge requirement under badge-level gating, computed by the
# SAME function generation uses (route_data.compute_badge_requirement). The client reads
# this directly instead of recomputing from pokemonLevels, so client guessability and the
# multiworld's access rules can't disagree for cross-gen evolutions (BUG-17). Only non-zero
# tiers are emitted to keep the map small; the client treats a missing id as 0.
badge_requirements = {}
for m in POKEMON_DATA:
    req = compute_badge_requirement(m["id"])
    if req:
        badge_requirements[str(m["id"])] = req

output = {
    "routeInfo": route_info,
    "pokemonRoutes": pokemon_routes,
    "familyBase": family_base,
    "routeKeyItems": route_key_items,
    "lineUnlockItems": line_unlock_items,
    "pokemonLevels": pokemon_levels,
    "badgeLevelThresholds": BADGE_LEVEL_THRESHOLDS,
    "badgeRequirements": badge_requirements,
}

if __name__ == "__main__":
    out_path = Path("D:/pythonProjects/PokepelagoClient/src/data/route_data.json")
    out_path.write_text(json.dumps(output, separators=(",", ":")), encoding="utf-8")
    size_kb = out_path.stat().st_size / 1024
    print(f"Wrote {out_path} ({size_kb:.0f} KB)")

    # Also human-readable version for inspection
    out_pretty = Path("D:/pythonProjects/PokepelagoClient/src/data/route_data_pretty.json")
    out_pretty.write_text(json.dumps(output, indent=2), encoding="utf-8")
    print(f"Wrote {out_pretty} ({out_pretty.stat().st_size / 1024:.0f} KB)")
