from collections import Counter
from typing import Any

from BaseClasses import Region, Entrance, ItemClassification, Tutorial, CollectionState
from rule_builder.rules import Has, HasAll, HasAllCounts, HasAny
from worlds.AutoWorld import World, WebWorld
from .Items import (PokepelagoItem, item_table, item_data_table, GEN_1_TYPES, FILLER_ITEM_CATEGORIES,
                    ROUTE_KEY_NAMES, LINE_UNLOCK_NAMES)
from .Locations import (PokepelagoLocation, location_table, milestones, starting_locations,
                        TYPE_MILESTONE_STEPS, DEXSANITY_OFF_EXTRA_STEPS, ROUTE_MILESTONE_NAMES)
from .Options import PokepelagoOptions, pokepelago_option_groups, _LEGACY_REGION_MAP
from .data import (POKEMON_DATA, GAME_REGIONS, GAME_GENERATIONS, REGION_RANGES, REGION_MON_COUNTS,
                   MICRO_REGION_MON_THRESHOLD, STARTERS_BY_REGION, get_pokemon_region,
                   LEGENDARY_SUB_IDS, LEGENDARY_BOX_IDS, LEGENDARY_MYTHIC_IDS,
                   BABY_IDS, TRADE_EVO_IDS, FOSSIL_IDS, ULTRA_BEAST_IDS, PARADOX_IDS,
                   STONE_EVO_GROUPS)
from .route_data import (ROUTE_DATA, ROUTE_GROUPS, ROUTE_TO_GROUP, POKEMON_ROUTES,
                         FAMILY_BASE, BADGE_LEVEL_THRESHOLDS, compute_badge_requirement)
from .rules import CanAccessNPokemon
# LEVER 1: importing logic_mixin registers PokepelagoLogicMixin via AutoLogicRegister
# (it must be imported before any CollectionState is constructed) and exposes the
# index builder + incremental-update helpers used by collect/remove below.
from .logic_mixin import build_pp_index, pp_apply

# Derive from GAME_REGIONS so it stays in sync automatically
_REGION_BY_INDEX: dict[int, str] = {i + 1: r for i, r in enumerate(GAME_REGIONS)}


class PokepelagoWeb(WebWorld):
    option_groups = pokepelago_option_groups
    tutorials = [Tutorial(
        "Pokepelago Setup Guide",
        "A guide to setting up the Pokepelago Archipelago world.",
        "English",
        "setup_en.md",
        "setup/en",
        ["Appie"]
    )]

class PokepelagoWorld(World):
    """
    Pokepelago: A collection-based world where you catch 'em all by guessing their names.
    Each game region acts as a zone gated by a Region Pass item.
    Type Keys gate access to Pokemon of that type (creates cross-player dependencies).
    """
    game: str = "Pokepelago"
    options_dataclass = PokepelagoOptions
    options: PokepelagoOptions
    topology_present: bool = True
    web = PokepelagoWeb()

    item_name_to_id = item_table
    location_name_to_id = location_table

    # ── Core generation pipeline ────────────────────────────────────────────────

    def generate_early(self) -> None:
        # Universal Tracker re-generation: restore derived state from slot data
        passthrough = getattr(self.multiworld, "re_gen_passthrough", {}).get("Pokepelago")
        if passthrough:
            self._generate_early_from_passthrough(passthrough)
            return

        # Backward compat: merge legacy include_kanto/johto/… toggles into regions set
        o = self.options
        legacy_regions = {region for opt_name, region in _LEGACY_REGION_MAP.items()
                          if getattr(o, opt_name).value}
        if legacy_regions:
            o.regions.value = o.regions.value | legacy_regions

        # Route/line locks require dexsanity (not enough milestone locations to hold all keys)
        if (o.route_locks_enabled.value or o.line_locks.value) and not o.dexsanity.value:
            o.dexsanity.value = 1

        self._select_active_regions()
        self._prune_invalid_gates()

        # Line locks and route locks compose independently and are no longer auto-disabled:
        # route locks gate by where a Pokemon is found, line locks gate by evolution family.
        # (T1) The old "redundant with route_locks_enabled" kill was a correctness bug: the
        # two gating axes are orthogonal, not redundant. (T2) The 55% progression-vs-location
        # heuristic now only *warns*; it never silently mutates the user's chosen options.
        # The L1 incremental accessible-counter makes the honest all-locks config cheap to
        # generate, so neither workaround is needed for performance any longer.
        if o.line_locks.value and not o.route_locks_enabled.value:
            import logging
            # Estimate progression item count vs location count and warn (no mutation).
            # If line unlocks push progression above 55% of locations, fill may struggle.
            active_ids = set()
            for region in self.active_regions:
                lo, hi = REGION_RANGES[region]
                active_ids.update(m["id"] for m in POKEMON_DATA if lo <= m["id"] <= hi)
            n_families = len({FAMILY_BASE.get(pid, pid) for pid in active_ids})
            n_locations = len(active_ids) + 30  # dexsanity locations + ~30 milestones
            # Estimate other progression: ~18 type keys + ~9 region passes + ~20 gates
            est_other_prog = 47 if len(self.active_regions) > 1 else 20
            est_total_prog = n_families + est_other_prog
            if est_total_prog > n_locations * 0.55:
                logging.warning(
                    f"Pokepelago: line_locks is on with an estimated {est_total_prog} progression "
                    f"items vs {n_locations} locations = {est_total_prog/n_locations:.0%} (over 55%); "
                    f"fill may be tight. Options left as chosen."
                )

        self._select_starter()
        self._compute_goal_count()
        self._rebuild_derived_state()

    def _select_active_regions(self) -> None:
        """Build active_regions from options (random or manual selection)."""
        rrc = self.options.random_region_count.value
        if rrc == 0:  # disabled — use manual Regions option
            self.active_regions = [
                region for region in GAME_REGIONS if region in self.options.regions.value
            ]
            if not self.active_regions:
                self.active_regions = ["Kanto"]
            return

        # Random selection: pick from generations (grouped) or individual regions
        use_gen_grouping = bool(self.options.group_hisui_galar.value)
        if use_gen_grouping:
            pool = GAME_GENERATIONS
            max_count = len(GAME_GENERATIONS)
        else:
            pool = [[r] for r in GAME_REGIONS]
            max_count = len(GAME_REGIONS)

        if rrc == -1:  # fully random count + selection
            count = self.random.randint(1, max_count)
        else:
            count = min(rrc, max_count)

        # BUG-25 (F1): never *offer* a lone micro-region. A region under
        # MICRO_REGION_MON_THRESHOLD mons (only Hisui's 7 today) has ~37 locations, nearly
        # all of them self-gated, so as the sole active region it cannot seed a heavy lock
        # stack's progression chain and fill raises "No more spots to place N items".
        # Any set of 2+ regions is safe (the partner region supplies hundreds of ungated
        # locations), so the filter applies only to single-unit rolls: Hisui stays fully
        # rollable in every 2+ combination and the distribution is otherwise untouched.
        # This changes what random selection offers, never the player's chosen locks, so
        # PERF-15's "locks stay genuinely on" decision is intact. The manual `regions:`
        # list is deliberately NOT filtered: an explicit Hisui-solo request is honored.
        if count == 1:
            viable = [group for group in pool
                      if sum(REGION_MON_COUNTS[r] for r in group) >= MICRO_REGION_MON_THRESHOLD]
            if viable:  # if every unit were micro-sized, fall back to the full pool
                pool = viable

        selected = self.random.sample(pool, count)
        self.active_regions = sorted(
            [region for group in selected for region in group],
            key=GAME_REGIONS.index
        )

    def _prune_invalid_gates(self) -> None:
        """Disable lock gates that don't apply to the active Pokemon pool.

        Locks for categories with 0 matching Pokemon just waste progression item slots
        and can cause FillErrors on small regions. Also ensures enough starting locations
        when multiple gates are active.
        """
        o = self.options
        active_ids = set()
        for region in self.active_regions:
            lo, hi = REGION_RANGES[region]
            active_ids.update(m["id"] for m in POKEMON_DATA if lo <= m["id"] <= hi)

        # Disable category gates that have no matching active Pokemon
        if o.ultra_beast_locks.value and not (active_ids & ULTRA_BEAST_IDS):
            o.ultra_beast_locks.value = 0
        if o.paradox_locks.value and not (active_ids & PARADOX_IDS):
            o.paradox_locks.value = 0
        if o.fossil_locks.value and not (active_ids & FOSSIL_IDS):
            o.fossil_locks.value = 0
        if o.trade_locks.value and not (active_ids & TRADE_EVO_IDS):
            o.trade_locks.value = 0
        if o.baby_locks.value and not (active_ids & BABY_IDS):
            o.baby_locks.value = 0
        if o.stone_locks.value and not any(active_ids & ids for ids in STONE_EVO_GROUPS.values()):
            o.stone_locks.value = 0

        # Badge gating with very few Pokemon is pointless (levels don't differentiate)
        if o.badge_level_gating.value and len(active_ids) < MICRO_REGION_MON_THRESHOLD:
            o.badge_level_gating.value = 0

        # Ensure enough starting locations when multiple gates are active
        gate_count = sum(bool(v) for v in [
            o.type_locks.value, o.region_locks.value, o.route_locks_enabled.value,
            o.line_locks.value, o.badge_level_gating.value, o.legendary_locks.value,
            o.trade_locks.value, o.baby_locks.value, o.fossil_locks.value,
            o.ultra_beast_locks.value, o.paradox_locks.value, o.stone_locks.value,
        ])
        if gate_count >= 2:
            min_starts = min(gate_count, 8)
            o.starting_location_count.value = max(o.starting_location_count.value, min_starts)

        # BUG-25 (F4): the residual hand-crafted case. Random selection can no longer roll a
        # lone micro-region (see _select_active_regions), but an explicit
        # `regions: [Hisui]` + `random_region_count: 0` is still honored on purpose, and with
        # a heavy lock stack it can genuinely FillError. Warn with the mitigation instead of
        # thinning the locks: per PERF-15 the world never silently disables a chosen lock.
        if (len(self.active_regions) == 1
                and len(active_ids) < MICRO_REGION_MON_THRESHOLD
                and gate_count >= 2):
            import logging
            logging.warning(
                f"Pokepelago: '{self.active_regions[0]}' is your only active region and has just "
                f"{len(active_ids)} Pokemon, while {gate_count} lock options are on. That region "
                f"supplies roughly {len(active_ids) + 30} locations, almost all of them behind the "
                f"very keys that need placing, so generation may fail with a FillError "
                f"('No more spots to place N items'). Fixes: add a second region to 'regions' "
                f"(Galar is the natural partner for Hisui; note 'group_hisui_galar' only affects "
                f"random selection, not this manual list), or turn some lock options off. "
                f"Options left as chosen."
            )

    def _select_starter(self) -> None:
        """Choose starting region and starter Pokemon.

        Supports two modes:
        - Regional (option 0-3): pick from STARTERS_BY_REGION for the starting region
        - Random (option 4): pick 1-3 starters from ALL active base-form Pokemon,
          with optional weighting toward traditional lab starters
        """
        sr_value = self.options.starter_region.value
        chosen_region = _REGION_BY_INDEX.get(sr_value)
        if sr_value == 0 or chosen_region not in self.active_regions:
            self.starting_region = self.random.choice(self.active_regions)
        else:
            self.starting_region = chosen_region

        idx = self.options.starter_pokemon.value

        if idx == 4:  # random_starter: pick from all regional starters across active regions
            self._select_random_starters(lab_only=True)
            return
        if idx == 5:  # random_any: pick from all active base-form Pokemon
            self._select_random_starters(lab_only=False)
            return

        # Regional mode: pick from STARTERS_BY_REGION
        starter_list = STARTERS_BY_REGION.get(self.starting_region, [])
        if starter_list:
            if idx == 0:  # any = random from region starters
                chosen = self.random.choice(starter_list)
            else:
                chosen = starter_list[min(idx - 1, len(starter_list) - 1)]
            self.starter_names: set[str] = {chosen}
            self.chosen_starter: str | None = chosen
        else:
            # No starters for this region (e.g. Hisui): use first Pokemon as virtual starter
            lo, hi = REGION_RANGES[self.starting_region]
            fallback = next((m for m in POKEMON_DATA if lo <= m["id"] <= hi), None)
            if fallback:
                self.starter_names = {fallback["name"]}
                self.chosen_starter = fallback["name"]
            else:
                self.starter_names = set()
                self.chosen_starter = None

    def _select_random_starters(self, lab_only: bool = False) -> None:
        """Pick 1-3 random starters.

        lab_only=True: pick from regional starters across all active regions.
        lab_only=False: pick from ALL active base-form Pokemon with routes.
        """
        active_ids = set(self._iter_active_ids())

        # Build candidate pool
        candidates: list[dict] = []
        lab_pokemon_names: set[str] = set()
        for region in self.active_regions:
            for name in STARTERS_BY_REGION.get(region, []):
                lab_pokemon_names.add(name.lower())

        # Pokemon that should never be random starters (gated behind extra items)
        excluded_ids = (
            LEGENDARY_SUB_IDS | LEGENDARY_BOX_IDS | LEGENDARY_MYTHIC_IDS |
            BABY_IDS | TRADE_EVO_IDS | FOSSIL_IDS | ULTRA_BEAST_IDS | PARADOX_IDS
        )
        for ids in STONE_EVO_GROUPS.values():
            excluded_ids = excluded_ids | ids

        if lab_only:
            # Only regional starters from active regions (exclude gated ones)
            for mon in POKEMON_DATA:
                if mon["id"] not in active_ids:
                    continue
                if mon["id"] in excluded_ids:
                    continue
                if mon["name"].lower() in lab_pokemon_names:
                    candidates.append(mon)
        else:
            # All active base-form Pokemon with routes (exclude gated ones)
            for mon in POKEMON_DATA:
                if mon["id"] not in active_ids:
                    continue
                if mon["id"] in excluded_ids:
                    continue
                base = FAMILY_BASE.get(mon["id"], mon["id"])
                if base != mon["id"]:
                    continue
                if mon["id"] not in POKEMON_ROUTES:
                    continue
                candidates.append(mon)

        # Fallback chain: if the preferred candidate pool is empty, relax constraints
        # progressively to guarantee at least one starter when active regions contain
        # any routed Pokemon. Without this, gated-only region sets (e.g. Hisui-only)
        # silently yield 0 starters, which cascades into FillErrors because no Type
        # Keys / Route Keys / Line Unlocks / Region Passes get pre-collected to
        # bootstrap the progression chain.
        if not candidates and lab_only:
            # Relax 1: fall through to non-lab base-form selection
            return self._select_random_starters(lab_only=False)

        if not candidates:
            # Relax 2: same base-form + route filter but allow gated categories
            # (legendaries, trade evos, fossils, UBs, paradoxes, stone evos)
            for mon in POKEMON_DATA:
                if mon["id"] not in active_ids:
                    continue
                base = FAMILY_BASE.get(mon["id"], mon["id"])
                if base != mon["id"]:
                    continue
                if mon["id"] not in POKEMON_ROUTES:
                    continue
                candidates.append(mon)

        if not candidates:
            # Relax 3: allow non-base forms (e.g. Hisui-only where every Pokemon is
            # a regional evolution whose base form lives in a non-active region)
            for mon in POKEMON_DATA:
                if mon["id"] not in active_ids:
                    continue
                if mon["id"] not in POKEMON_ROUTES:
                    continue
                candidates.append(mon)

        if not candidates:
            self.starter_names = set()
            self.chosen_starter = None
            return

        count = min(self.options.starter_count.value, len(candidates))

        # Weight selection: prefer lab starters if option is on
        if self.options.prefer_lab_starters.value:
            weights = [5.0 if mon["name"].lower() in lab_pokemon_names else 1.0 for mon in candidates]
        else:
            weights = [1.0] * len(candidates)

        # Weighted sampling without replacement
        chosen: list[dict] = []
        remaining = list(zip(candidates, weights))
        for _ in range(count):
            if not remaining:
                break
            cands, wgts = zip(*remaining)
            picked = self.random.choices(list(cands), weights=list(wgts), k=1)[0]
            chosen.append(picked)
            remaining = [(c, w) for c, w in remaining if c["id"] != picked["id"]]

        self.starter_names = {mon["name"] for mon in chosen}
        self.chosen_starter = chosen[0]["name"] if chosen else None

    def _compute_goal_count(self) -> None:
        """Compute how many Pokemon the player needs to catch for victory."""
        total = sum(1 for _ in self._iter_active_ids())
        if self.options.goal_type.value == 0:  # percentage
            raw_goal = max(1, round(total * self.options.goal_percentage.value / 100))
        else:  # count
            raw_goal = min(self.options.goal_count.value, total)
        self.goal_count = min(raw_goal, total)

    def _iter_active_ids(self):
        """Yield all Pokemon IDs in the active regions."""
        for region in self.active_regions:
            lo, hi = REGION_RANGES[region]
            yield from range(lo, hi + 1)

    def _rebuild_derived_state(self) -> None:
        """Compute active Pokemon, lock categories, and milestone requirement groups.

        Called from both generate_early() and _generate_early_from_passthrough()
        to eliminate code duplication.
        """
        active_ids: set[int] = set(self._iter_active_ids())

        self.active_pokemon = [mon for mon in POKEMON_DATA if mon["id"] in active_ids]
        self.active_pokemon_names = [mon["name"] for mon in self.active_pokemon]
        self._mon_lookup: dict[str, dict] = {mon["name"]: mon for mon in self.active_pokemon}

        # Lock category sets: which active Pokemon fall into each gate category
        self._active_legendary_subs   = active_ids & LEGENDARY_SUB_IDS
        self._active_legendary_boxes  = active_ids & LEGENDARY_BOX_IDS
        self._active_legendary_mythics = active_ids & LEGENDARY_MYTHIC_IDS
        self._active_babies   = active_ids & BABY_IDS
        self._active_trades   = active_ids & TRADE_EVO_IDS
        self._active_fossils  = active_ids & FOSSIL_IDS
        self._active_ubs      = active_ids & ULTRA_BEAST_IDS
        self._active_paradoxes = active_ids & PARADOX_IDS
        self._active_stones: dict[str, set[int]] = {
            stone: active_ids & ids for stone, ids in STONE_EVO_GROUPS.items() if active_ids & ids
        }

        # Route locks: build active route keys using ROUTE_GROUPS for grouped routes
        # and individual entries for ungrouped (virtual/roaming) routes.
        # _active_routes maps the key used in ROUTE_KEY_NAMES (group_key or route_key) → item_name
        self._active_routes: dict[str, str] = {}  # group_key or route_key → item_name
        if self.options.route_locks_enabled.value:
            active_region_set = set(self.active_regions)
            # Activate groups whose region matches and that contain active Pokemon
            for group_key, group_info in ROUTE_GROUPS.items():
                if group_info["region"] not in active_region_set:
                    continue
                # Group is active if any constituent route has an active Pokemon
                has_active = any(
                    pid in active_ids
                    for rk in group_info["routes"] if rk in ROUTE_DATA
                    for pid in ROUTE_DATA[rk]["pokemon"]
                )
                if has_active:
                    item_name = ROUTE_KEY_NAMES.get(group_key)
                    if item_name:
                        self._active_routes[group_key] = item_name
            # Activate ungrouped routes (virtual, roaming) individually
            _grouped_route_keys = set(ROUTE_TO_GROUP.keys())
            for route_key, route_info in ROUTE_DATA.items():
                if route_key in _grouped_route_keys:
                    continue  # handled by groups above
                if route_info["region"] not in active_region_set:
                    continue
                if any(pid in active_ids for pid in route_info["pokemon"]):
                    item_name = ROUTE_KEY_NAMES.get(route_key)
                    if item_name:
                        self._active_routes[route_key] = item_name

        # Line locks: active families are those with at least one member in active pool
        self._active_lines: dict[int, str] = {}  # base_id → item_name
        if self.options.line_locks.value:
            for pid in active_ids:
                base_id = FAMILY_BASE.get(pid, pid)
                if base_id not in self._active_lines:
                    item_name = LINE_UNLOCK_NAMES.get(base_id)
                    if item_name:
                        self._active_lines[base_id] = item_name

        # Pokemon → route key item names lookup (for rule building)
        # Maps each Pokemon to the GROUP key item(s) it needs (OR logic: any one suffices)
        self._pokemon_route_items: dict[int, list[str]] = {}
        if self.options.route_locks_enabled.value:
            for pid in active_ids:
                routes = POKEMON_ROUTES.get(pid, [])
                # For evo-only Pokemon, inherit base form's routes
                base_id = FAMILY_BASE.get(pid, pid)
                if not routes and base_id != pid:
                    routes = POKEMON_ROUTES.get(base_id, [])
                # Translate individual route keys to their group (or keep as-is for ungrouped)
                item_names: set[str] = set()
                for rk in routes:
                    lookup_key = ROUTE_TO_GROUP.get(rk, rk)  # group_key if grouped, else route_key
                    if lookup_key in self._active_routes:
                        item_names.add(self._active_routes[lookup_key])
                if item_names:
                    self._pokemon_route_items[pid] = sorted(item_names)

        self._compute_milestone_requirements()

    def _compute_milestone_requirements(self) -> None:
        """Pre-compute requirement groups for milestone access rules.

        Groups Pokemon by their combined (region_pass, type_keys, extra_gates) requirements
        and counts how many Pokemon share each group. This lets milestone rules efficiently
        check how many Pokemon are logically accessible without iterating all 1000+ Pokemon.
        """
        region_locks = bool(self.options.region_locks.value)
        type_locks = bool(self.options.type_locks.value)

        route_locks_on = bool(self.options.route_locks_enabled.value)
        line_locks_on = bool(self.options.line_locks.value)

        global_req_counter: Counter = Counter()
        type_req_counters: dict[str, Counter] = {t: Counter() for t in GEN_1_TYPES}

        for mon in self.active_pokemon:
            region = get_pokemon_region(mon["id"])
            region_req = f"{region} Pass" if (region_locks and region != self.starting_region) else None
            type_reqs = frozenset(f"{t} Type Key" for t in mon["types"]) if type_locks else frozenset()
            extra_reqs = self._extra_reqs(mon["id"])

            # Route locks: need ANY of the Pokemon's route key items (OR logic)
            route_reqs: frozenset = frozenset()
            if route_locks_on:
                items = self._pokemon_route_items.get(mon["id"], [])
                if items:
                    route_reqs = frozenset(items)

            # Line locks: need the family's Line Unlock item
            line_req: str | None = None
            if line_locks_on:
                base_id = FAMILY_BASE.get(mon["id"], mon["id"])
                line_req = self._active_lines.get(base_id)

            key = (region_req, type_reqs, extra_reqs, route_reqs, line_req)
            global_req_counter[key] += 1
            for t in mon["types"]:
                if t in type_req_counters:
                    type_req_counters[t][key] += 1

        self._milestone_req_groups = [
            (rr, tr, er, rtr, lr, c) for (rr, tr, er, rtr, lr), c in global_req_counter.items()
        ]
        self._type_milestone_req_groups: dict[str, list] = {
            t: [(rr, tr, er, rtr, lr, c) for (rr, tr, er, rtr, lr), c in counter.items()]
            for t, counter in type_req_counters.items()
        }
        self._active_type_counts: dict[str, int] = {
            t: sum(counter.values()) for t, counter in type_req_counters.items()
        }

        # LEVER 1: build the static reverse index (item -> bucket conditions) that
        # lets collect/remove maintain the running accessible-Pokemon counter in O(1)
        # amortized instead of re-scanning all buckets on every _evaluate.
        build_pp_index(self)

    def _extra_reqs(self, mon_id: int) -> frozenset:
        """Return extra gate requirements for a Pokemon beyond region/type/route/line locks.

        Returns a frozenset of (item_name, required_count) tuples. An empty frozenset
        means no extra gate applies. Route locks (HasAny) and Line locks (Has) are
        handled separately in set_rules() since they use different rule types.
        """
        o = self.options
        reqs: list = []

        # Badge gating: max(level-based badges, legendary tier badges)
        badge_req = 0
        if o.badge_level_gating.value:
            # Shared with the client data export so both sides agree (BUG-17).
            badge_req = compute_badge_requirement(mon_id)

        if o.legendary_locks.value:
            if mon_id in self._active_legendary_mythics:
                badge_req = max(badge_req, 8)
            elif mon_id in self._active_legendary_boxes:
                badge_req = max(badge_req, 7)
            elif mon_id in self._active_legendary_subs:
                badge_req = max(badge_req, 6)

        if badge_req > 0:
            reqs.append(("Gym Badge", badge_req))

        if o.trade_locks.value and mon_id in self._active_trades:
            reqs.append(("Link Cable", 1))
        if o.baby_locks.value and mon_id in self._active_babies:
            reqs.append(("Daycare", o.daycare_count.value))
        if o.fossil_locks.value and mon_id in self._active_fossils:
            reqs.append(("Fossil Restorer", 1))
        if o.ultra_beast_locks.value and mon_id in self._active_ubs:
            reqs.append(("Ultra Wormhole", 1))
        if o.paradox_locks.value and mon_id in self._active_paradoxes:
            reqs.append(("Time Rift", 1))
        if o.stone_locks.value:
            for stone, ids in self._active_stones.items():
                if mon_id in ids:
                    reqs.append((f"{stone.title()} Stone", 1))
                    break
        return frozenset(reqs)

    # ── Item helpers ────────────────────────────────────────────────────────────

    def get_filler_item_name(self) -> str:
        return "Magikarp used Splash - but nothing happened!"

    def create_item(self, name: str) -> PokepelagoItem:
        data = item_data_table.get(name)
        if data:
            classification = data[1]
            item_id = data[0]
        else:
            classification = ItemClassification.filler
            item_id = item_table.get(name, 0)
        # FEAT-14: optionally demote Pokedex/Pokegear from useful to filler so they
        # stop crowding the useful tier. Master Ball is intentionally unaffected.
        if name in ("Pokedex", "Pokegear") and self.options.pokegear_pokedex_filler.value:
            classification = ItemClassification.filler
        return PokepelagoItem(name, classification, item_id, self.player)

    def create_event_item(self, name: str) -> PokepelagoItem:
        return PokepelagoItem(name, ItemClassification.progression, None, self.player)

    # ── LEVER 1: incremental accessible-counter maintenance ──────────────────────
    # Override collect/remove to keep state.pp_accessible[player][group_key] current.
    # We snapshot the item's count around the base implementation so the delta is
    # exact even for progressive/multi-count items, then flip only the buckets that
    # reference this item. State containers live on CollectionState (the LogicMixin);
    # the static reverse index lives on the world (self._pp_index).

    def collect(self, state: "CollectionState", item: PokepelagoItem) -> bool:
        prog = state.prog_items[self.player]
        before = prog.get(item.name, 0)
        changed = super().collect(state, item)
        if changed:
            after = prog.get(item.name, 0)
            delta = after - before
            if delta:
                pp_apply(state, self, self.player, item.name, delta)
        return changed

    def remove(self, state: "CollectionState", item: PokepelagoItem) -> bool:
        prog = state.prog_items[self.player]
        before = prog.get(item.name, 0)
        changed = super().remove(state, item)
        if changed:
            after = prog.get(item.name, 0)
            delta = after - before
            if delta:
                pp_apply(state, self, self.player, item.name, delta)
        return changed

    # ── Item pool creation ──────────────────────────────────────────────────────

    def create_items(self) -> None:
        # Determine which types the starters cover
        starter_types: set[str] = set()
        for name in self.starter_names:
            if mon := self._mon_lookup.get(name):
                starter_types.update(mon["types"])

        active_types: set[str] = set()
        for mon in self.active_pokemon:
            active_types.update(mon["types"])

        my_items_in_pool = 0

        # Pre-collect starter Type Keys (not placed in pool)
        for p_type in sorted(starter_types):
            self.multiworld.push_precollected(self.create_item(f"{p_type} Type Key"))

        # Pre-collect starter's Route Key, Line Unlock, and Region Pass
        starter_precollected_routes: set[str] = set()
        starter_precollected_lines: set[int] = set()
        starter_precollected_regions: set[str] = set()
        for name in sorted(self.starter_names):
            mon = self._mon_lookup.get(name)
            if not mon:
                continue
            mid = mon["id"]
            # Region pass: pre-collect if starter is in a non-starting region
            if self.options.region_locks.value:
                mon_region = get_pokemon_region(mid)
                if mon_region != self.starting_region and mon_region in self.active_regions:
                    if mon_region not in starter_precollected_regions:
                        self.multiworld.push_precollected(self.create_item(f"{mon_region} Pass"))
                        starter_precollected_regions.add(mon_region)
            # Route key: pre-collect one route key for any route the starter appears on
            if self.options.route_locks_enabled.value:
                route_items = self._pokemon_route_items.get(mid, [])
                if route_items:
                    self.multiworld.push_precollected(self.create_item(route_items[0]))
                    starter_precollected_routes.add(route_items[0])
            # Line unlock: pre-collect the starter's family line
            if self.options.line_locks.value:
                base_id = FAMILY_BASE.get(mid, mid)
                line_item = self._active_lines.get(base_id)
                if line_item:
                    self.multiworld.push_precollected(self.create_item(line_item))
                    starter_precollected_lines.add(base_id)

        # Non-starter Type Keys as progression items
        if self.options.type_locks.value:
            for p_type in GEN_1_TYPES:
                if p_type not in starter_types and p_type in active_types:
                    self.multiworld.itempool.append(self.create_item(f"{p_type} Type Key"))
                    my_items_in_pool += 1

        # Region Passes for non-starting regions (minus pre-collected starter regions)
        if self.options.region_locks.value:
            for region in self.active_regions:
                if region != self.starting_region and region not in starter_precollected_regions:
                    self.multiworld.itempool.append(self.create_item(f"{region} Pass"))
                    my_items_in_pool += 1

        o = self.options

        # Route Key items (one per active route, minus starter's pre-collected key)
        if o.route_locks_enabled.value:
            for route_key, item_name in sorted(self._active_routes.items()):
                if item_name not in starter_precollected_routes:
                    self.multiworld.itempool.append(self.create_item(item_name))
                    my_items_in_pool += 1

        # Line Unlock items (one per active evolution family, minus starter's pre-collected line)
        # Line locks force dexsanity ON in generate_early(), so locations are sufficient
        if o.line_locks.value:
            for base_id, item_name in sorted(self._active_lines.items()):
                if base_id not in starter_precollected_lines:
                    self.multiworld.itempool.append(self.create_item(item_name))
                    my_items_in_pool += 1

        # Gym Badges: added if legendary_locks OR badge_level_gating is on
        has_badge_need = (
            (o.legendary_locks.value and (self._active_legendary_subs or self._active_legendary_boxes or self._active_legendary_mythics))
            or o.badge_level_gating.value
        )
        if has_badge_need:
            for _ in range(8):
                self.multiworld.itempool.append(self.create_item("Gym Badge"))
                my_items_in_pool += 1

        if o.trade_locks.value and self._active_trades:
            self.multiworld.itempool.append(self.create_item("Link Cable"))
            my_items_in_pool += 1

        if o.baby_locks.value and self._active_babies:
            for _ in range(o.daycare_count.value):
                self.multiworld.itempool.append(self.create_item("Daycare"))
                my_items_in_pool += 1

        if o.fossil_locks.value and self._active_fossils:
            self.multiworld.itempool.append(self.create_item("Fossil Restorer"))
            my_items_in_pool += 1

        if o.ultra_beast_locks.value and self._active_ubs:
            self.multiworld.itempool.append(self.create_item("Ultra Wormhole"))
            my_items_in_pool += 1

        if o.paradox_locks.value and self._active_paradoxes:
            self.multiworld.itempool.append(self.create_item("Time Rift"))
            my_items_in_pool += 1

        if o.stone_locks.value:
            for stone in sorted(self._active_stones):
                self.multiworld.itempool.append(self.create_item(f"{stone.title()} Stone"))
                my_items_in_pool += 1

        # Shiny Charms: cosmetic filler items (~5% of active Pokemon count)
        self.shiny_count = 0
        if o.include_shinies.value and self.active_pokemon:
            self.shiny_count = max(1, len(self.active_pokemon) // 20)
            for _ in range(self.shiny_count):
                self.multiworld.itempool.append(self.create_item("Shiny Charm"))
                my_items_in_pool += 1

        # Fill remaining locations with weighted filler/traps
        total_locations = sum(
            1 for loc in self.multiworld.get_locations(self.player) if loc.address is not None
        )
        trap_key_to_name = {
            "small_shuffle": "Small Shuffle Trap",
            "big_shuffle":   "Big Shuffle Trap",
            "derpy_mon":     "Derpy Mon Trap",
            "release":       "Release Trap",
        }
        trap_names = list(trap_key_to_name.values())
        raw_trap_weights = [self.options.trap_weights.value.get(k, 0) for k in trap_key_to_name]
        if sum(raw_trap_weights) == 0:
            raw_trap_weights = [1] * len(trap_names)
        trap_chance = self.options.trap_chance.value

        category_names = list(FILLER_ITEM_CATEGORIES.keys())
        category_weights = [self.options.filler_weights.value.get(cat, 0) for cat in category_names]
        if sum(category_weights) == 0:
            category_weights = [1] * len(category_names)

        while my_items_in_pool < total_locations:
            if self.random.randint(1, 100) <= trap_chance:
                filler_name = self.random.choices(trap_names, weights=raw_trap_weights, k=1)[0]
            else:
                chosen_category = self.random.choices(category_names, weights=category_weights, k=1)[0]
                filler_name = self.random.choice(FILLER_ITEM_CATEGORIES[chosen_category])
            self.multiworld.itempool.append(self.create_item(filler_name))
            my_items_in_pool += 1

    # ── Local filler pre-fill (FEAT-15: keep our filler out of other games) ───────

    def _effective_local_filler_percent(self) -> int:
        """Resolve local_filler_percent, including the 'auto' (-1) forced-minimum
        mode that scales with how inflated this world's filler pool is."""
        raw = self.options.local_filler_percent.value
        if raw >= 0:
            return raw
        # auto: Dexsanity off -> no flood -> 0. Dexsanity on -> 50% baseline, +10%
        # per region beyond the first, capped at 90% so some filler still travels.
        if not self.options.dexsanity.value:
            return 0
        n_regions = len(self.active_regions)
        return min(90, 50 + 10 * max(0, n_regions - 1))

    def pre_fill(self) -> None:
        """Lock a configurable fraction of THIS world's own filler onto THIS world's
        own locations before the multiworld fill, removing it from the shared pool so
        it stops flooding other players' games. Only filler is localized; progression
        and useful gate items stay in the pool.

        Localizing is only safe when the REST of the multiworld has room to absorb
        this world's own progression. Because we lock filler into our own (possibly
        gated) locations, our own keys must be placeable elsewhere; if they can't be
        (a solo game, or a multiworld whose only other worlds have too few locations,
        e.g. the fuzzer's Empty static world), locking filler here would starve our
        own progression and the fill would raise a FillError. So we require the other
        players to have at least as many unfilled locations as we have advancement
        items, plus a buffer. This generalizes the TUNIC ``local_fill`` players>1
        guard, which silently assumes the other worlds actually carry locations.
        """
        pct = self._effective_local_filler_percent()
        if pct <= 0 or self.multiworld.players <= 1:
            return

        mw = self.multiworld
        player = self.player

        # How much of our own progression could be forced elsewhere, and how much
        # room the rest of the multiworld has for it. If the rest can't hold our
        # progression, do not localize -- our own gated locations must stay free.
        own_advancement = sum(1 for it in mw.itempool
                              if it.player == player and it.advancement)
        other_unfilled = sum(1 for loc in mw.get_unfilled_locations()
                             if loc.player != player and loc.address is not None)
        if other_unfilled < own_advancement + 8:
            return

        # Item names Pokepelago treats as filler from the PLAYER'S point of view.
        # This deliberately INCLUDES Pokedex/Pokegear/Master Ball and Shiny Charm
        # even though AP classifies some of them as `useful`, because those are
        # exactly the items the community calls filler. Traps are derived from the
        # item table so new traps are picked up automatically. Progression items
        # (Type Keys, Region Passes, Line Unlocks, gate items) are NEVER in this set.
        localizable: set = set()
        for names in FILLER_ITEM_CATEGORIES.values():
            localizable.update(names)
        localizable.update(name for name, (_id, cls) in item_data_table.items()
                           if cls == ItemClassification.trap)
        localizable.add("Shiny Charm")

        # Our own localizable filler still in the pool. Matched by name AND the
        # (not advancement) safety net so a future reclassification can never let a
        # progression item slip into the localized set.
        my_filler = [it for it in mw.itempool
                     if it.player == player and not it.advancement and it.name in localizable]
        if not my_filler:
            return

        # Reserve a couple of immediately-reachable (sphere-1) locations so we never
        # lock filler into every early location this world exposes to the multiworld
        # bootstrap. Skip plando/priority locations too (they are claimed elsewhere).
        sphere_one = mw.get_reachable_locations(CollectionState(mw), player)
        reserved = set()
        if sphere_one:
            reserved = set(self.random.sample(sphere_one, min(2, len(sphere_one))))
        priority = self.options.priority_locations.value
        my_locations = [loc for loc in mw.get_unfilled_locations(player)
                        if loc.address is not None and loc not in reserved
                        and loc.name not in priority]
        if not my_locations:
            return

        # Localize ceil(pct%) of our filler, bounded by available local locations.
        target = (len(my_filler) * pct + 99) // 100  # ceil
        n = min(target, len(my_locations))
        if n <= 0:
            return

        self.random.shuffle(my_filler)
        self.random.shuffle(my_locations)
        placed_ids = set()
        loc_iter = iter(my_locations)
        for item in my_filler[:n]:
            for loc in loc_iter:
                if loc.item is None:  # another world may have pre-filled it
                    loc.place_locked_item(item)
                    placed_ids.add(id(item))
                    break

        # Remove everything we actually locked from the shared pool. Anything we
        # could not place stays in the pool untouched (preserves items == locations).
        if placed_ids:
            mw.itempool[:] = [it for it in mw.itempool if id(it) not in placed_ids]

    # ── Region & rule creation ──────────────────────────────────────────────────

    def create_regions(self) -> None:
        menu_region = Region("Menu", self.player, self.multiworld)
        self.multiworld.regions.append(menu_region)

        # One AP Region per active game region
        game_regions: dict = {}
        gate_regions = (self.options.region_locks.value and self.options.dexsanity.value)
        for region_name in self.active_regions:
            ap_region = Region(f"{region_name} Region", self.player, self.multiworld)
            self.multiworld.regions.append(ap_region)
            game_regions[region_name] = ap_region

            rule = Has(f"{region_name} Pass") if (gate_regions and region_name != self.starting_region) else None
            self.create_entrance(menu_region, ap_region, rule=rule, name=f"Menu To {region_name}")

        # Starting locations and global milestone locations → Menu region
        start_loc_count = self.options.starting_location_count.value
        active_starting_locs = set(starting_locations[:start_loc_count])

        for loc_name, loc_id in self.location_name_to_id.items():
            if loc_name.startswith("Guess ") or loc_name.startswith("Caught ") or loc_name.startswith("Cleared "):
                continue  # Per-Pokemon, type milestones, route milestones handled below

            if loc_name in starting_locations and loc_name not in active_starting_locs:
                continue  # Excluded by starting_location_count option

            if loc_name.startswith("Guessed "):
                count = int(loc_name.split(" ")[1])
                if count > len(self.active_pokemon) - len(self.starter_names):
                    continue
                # Extra early milestones (3, 4) only when dexsanity is off
                if count in DEXSANITY_OFF_EXTRA_STEPS and self.options.dexsanity.value:
                    continue

            location = PokepelagoLocation(self.player, loc_name, loc_id, menu_region)
            menu_region.locations.append(location)

        # Type-specific milestone locations (e.g. "Caught 5 Fire Pokemon")
        type_steps = TYPE_MILESTONE_STEPS
        if not self.options.dexsanity.value:
            type_steps = sorted(set(TYPE_MILESTONE_STEPS + DEXSANITY_OFF_EXTRA_STEPS))
        self._created_type_milestones: dict[str, list[int]] = {}
        for p_type in GEN_1_TYPES:
            max_catchable = self._active_type_counts.get(p_type, 0)
            steps_for_type: list[int] = []
            for step in type_steps:
                if step <= max_catchable:
                    loc_name = f"Caught {step} {p_type} Pokemon"
                    loc_id = self.location_name_to_id.get(loc_name)
                    if loc_id is not None:
                        location = PokepelagoLocation(self.player, loc_name, loc_id, menu_region)
                        menu_region.locations.append(location)
                        steps_for_type.append(step)
            if steps_for_type:
                self._created_type_milestones[p_type] = steps_for_type

        # Route completion milestones: only create if needed to absorb excess items
        # With dexsanity ON + regular milestones, there are usually enough locations.
        # Only add route milestones if progression items would exceed available locations.
        # (Computed later in create_items if needed — placeholder for now)

        if self.options.dexsanity.value:
            # Per-Pokemon sub-regions connected from their game region
            for mon in self.active_pokemon:
                mon_name = mon["name"]
                mon_region_name = get_pokemon_region(mon["id"])
                parent_region = game_regions.get(mon_region_name, menu_region)

                mon_sub_region = Region(f"Region {mon_name}", self.player, self.multiworld)
                self.multiworld.regions.append(mon_sub_region)

                loc_name = f"Guess {mon_name}"
                loc_id = self.location_name_to_id[loc_name]
                location = PokepelagoLocation(self.player, loc_name, loc_id, mon_sub_region)
                mon_sub_region.locations.append(location)

                entrance = Entrance(self.player, f"Catch {mon_name}", parent_region)
                parent_region.exits.append(entrance)
                entrance.connect(mon_sub_region)

        # Victory event location
        victory_location = PokepelagoLocation(self.player, "Pokepelago Victory", None, menu_region)
        menu_region.locations.append(victory_location)

    def set_rules(self) -> None:
        player = self.player

        # Per-Pokemon access rules (type keys + extra gates + route + line in a single pass)
        if self.options.dexsanity.value:
            type_locks = bool(self.options.type_locks.value)
            route_locks = bool(self.options.route_locks_enabled.value)
            line_locks = bool(self.options.line_locks.value)

            for mon in self.active_pokemon:
                parts = []
                if type_locks:
                    type_keys = [f"{t} Type Key" for t in mon["types"]]
                    parts.append(HasAll(*type_keys))
                extra = self._extra_reqs(mon["id"])
                if extra:
                    parts.append(HasAllCounts({item: n for item, n in extra}))
                if route_locks:
                    route_items = self._pokemon_route_items.get(mon["id"])
                    if route_items:
                        parts.append(HasAny(*route_items))
                if line_locks:
                    base_id = FAMILY_BASE.get(mon["id"], mon["id"])
                    line_item = self._active_lines.get(base_id)
                    if line_item:
                        parts.append(Has(line_item))
                if parts:
                    rule = parts[0]
                    for p in parts[1:]:
                        rule = rule & p
                    loc = self.multiworld.get_location(f"Guess {mon['name']}", player)
                    self.set_rule(loc, rule)

        # Global milestone access rules
        for loc in self.multiworld.get_locations(player):
            if loc.address is not None and loc.name.startswith("Guessed "):
                count = int(loc.name.split(" ")[1])
                self.set_rule(loc, CanAccessNPokemon(count))

        # Type-specific milestone access rules
        for loc in self.multiworld.get_locations(player):
            if loc.address is not None and loc.name.startswith("Caught "):
                parts = loc.name.split(" ")
                count = int(parts[1])
                p_type = parts[2]
                if self._type_milestone_req_groups.get(p_type):
                    self.set_rule(loc, CanAccessNPokemon(count, group_key=p_type))

        # Victory rule
        victory_location = self.multiworld.get_location("Pokepelago Victory", player)
        self.set_rule(victory_location, CanAccessNPokemon(self.goal_count))
        victory_location.place_locked_item(self.create_event_item("Victory"))
        self.set_completion_rule(Has("Victory"))

    # ── Slot data ───────────────────────────────────────────────────────────────

    def fill_slot_data(self) -> dict[str, Any]:
        o = self.options
        return {
            "apworld_version": self.world_version.as_simple_string(),
            "type_locks": bool(o.type_locks.value),
            "region_locks": bool(o.region_locks.value),
            "route_locks": bool(o.route_locks_enabled.value),
            "line_locks": bool(o.line_locks.value),
            "badge_level_gating": bool(o.badge_level_gating.value),
            "active_regions": {r: list(REGION_RANGES[r]) for r in self.active_regions},
            "starting_region": self.starting_region,
            "goal_count": self.goal_count,
            "dexsanity": bool(o.dexsanity.value),
            "starting_locations": o.starting_location_count.value,
            "milestones": list(milestones),
            "starter_count": o.starting_location_count.value,
            "legendary_locks":   bool(o.legendary_locks.value),
            "trade_locks":       bool(o.trade_locks.value),
            "baby_locks":        bool(o.baby_locks.value),
            "daycare_count":     int(o.daycare_count.value),
            "fossil_locks":      bool(o.fossil_locks.value),
            "ultra_beast_locks": bool(o.ultra_beast_locks.value),
            "paradox_locks":     bool(o.paradox_locks.value),
            "stone_locks":       bool(o.stone_locks.value),
            "include_shinies":   bool(o.include_shinies.value),
            "master_ball_bypass_gates": bool(o.master_ball_bypass_gates.value),
            "stop_autosubmit_on_goal": bool(o.stop_autosubmit_on_goal.value),
            # DEVEX-15: ship the exact gate classification this APWorld used so the client
            # gates identically to the generating server (no client-bundled drift, and old
            # clients stay correct against future reclassifications). Always present.
            "gate_categories": {
                "legendary_sub":   sorted(LEGENDARY_SUB_IDS),
                "legendary_box":   sorted(LEGENDARY_BOX_IDS),
                "legendary_mythic": sorted(LEGENDARY_MYTHIC_IDS),
                "baby":            sorted(BABY_IDS),
                "trade_evo":       sorted(TRADE_EVO_IDS),
                "fossil":          sorted(FOSSIL_IDS),
                "ultra_beast":     sorted(ULTRA_BEAST_IDS),
                "paradox":         sorted(PARADOX_IDS),
                "stone_evo":       {stone: sorted(ids) for stone, ids in STONE_EVO_GROUPS.items()},
            },
            "shiny_count":       self.shiny_count,
            "starting_starter":  self.chosen_starter,
            "starting_starters": sorted(self.starter_names),
            "random_region_count": int(o.random_region_count.value),
            "type_milestones": self._created_type_milestones,
        }

    # ── Universal Tracker support ───────────────────────────────────────────────

    @staticmethod
    def interpret_slot_data(slot_data: dict[str, Any]) -> dict[str, Any]:
        """Return slot_data so the UT can re-generate with the same derived state."""
        return slot_data

    def _generate_early_from_passthrough(self, passthrough: dict[str, Any]) -> None:
        """Restore derived state from UT passthrough data instead of re-randomizing."""
        o = self.options

        # Restore options from passthrough so the rest of generation is consistent
        o.dexsanity.value = int(passthrough["dexsanity"])
        o.type_locks.value = int(passthrough["type_locks"])
        o.region_locks.value = int(passthrough["region_locks"])
        o.route_locks_enabled.value = int(passthrough.get("route_locks", 0))
        o.line_locks.value = int(passthrough.get("line_locks", 0))
        o.badge_level_gating.value = int(passthrough.get("badge_level_gating", 0))
        o.starting_location_count.value = passthrough["starter_count"]
        o.legendary_locks.value = int(passthrough["legendary_locks"])
        o.trade_locks.value = int(passthrough["trade_locks"])
        o.baby_locks.value = int(passthrough["baby_locks"])
        o.daycare_count.value = passthrough["daycare_count"]
        o.fossil_locks.value = int(passthrough["fossil_locks"])
        o.ultra_beast_locks.value = int(passthrough["ultra_beast_locks"])
        o.paradox_locks.value = int(passthrough["paradox_locks"])
        o.stone_locks.value = int(passthrough["stone_locks"])
        o.include_shinies.value = int(passthrough["include_shinies"])

        # Restore derived region/starter state (originally chosen via randomness)
        self.active_regions = list(passthrough["active_regions"].keys())
        self.starting_region = passthrough["starting_region"]
        self.goal_count = passthrough["goal_count"]
        self.chosen_starter = passthrough.get("starting_starter")
        starters_list = passthrough.get("starting_starters")
        if starters_list:
            self.starter_names = set(starters_list)
        elif self.chosen_starter:
            self.starter_names = {self.chosen_starter}
        else:
            self.starter_names = set()

        # Rebuild all derived state from restored regions (shared with generate_early)
        self._rebuild_derived_state()
