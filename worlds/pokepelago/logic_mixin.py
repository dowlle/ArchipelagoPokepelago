"""LEVER 1 — Incremental accessible-Pokemon counter (LogicMixin).

Replaces the per-call bucket scan in ``CanAccessNPokemon.Resolved._evaluate``
(rules.py) with a running count maintained on ``CollectionState``.

Model (RB / Hollow-Knight "count collected accessibility"):
  * Each milestone group (``"global"`` + one per type) is a list of *requirement
    buckets*. A bucket is a conjunction of gates over a fixed count of Pokemon.
  * A bucket is *satisfied* exactly when every one of its AND-gates is met AND,
    if it has a route OR-group, at least one route item is present.
  * ``state.pp_accessible[player][group_key]`` is the sum of ``count`` over
    currently-satisfied buckets. ``_evaluate`` is then::
        return state.pp_accessible[player][group_key] >= target_count

  * On collect / remove we update ONLY the buckets whose membership flips,
    driven by a static reverse index ``world._pp_index`` (item -> conditions).

Correctness notes (the traps called out by prior work):
  * We do NOT key any memo on ``id(state)`` (ids are reused as fill states are
    GC'd, which hangs). State lives on the CollectionState instance itself and is
    copied explicitly via ``copy_mixin``.
  * Counted gates (``HasAllCounts`` badges / daycare, i.e. ``(item, n)`` with
    n > 1) are handled with exact threshold flip-tracking: a condition flips when
    ``prog[item]`` crosses its own ``n``, not on mere presence.
  * Both collect and remove do exact incremental flip-tracking (symmetric).
  * Lazy per-(state, player) initialization: the first time a player's counter is
    touched after ``world._pp_index`` exists, we do one full scan from current
    ``prog_items`` (this captures precollected items collected before the index
    existed and is the only O(buckets) work per state).
"""
from __future__ import annotations

from typing import TYPE_CHECKING

from worlds.AutoWorld import LogicMixin

if TYPE_CHECKING:
    from BaseClasses import CollectionState
    from worlds.pokepelago import PokepelagoWorld


# Condition kinds in the reverse index.
_AND = 0    # single-item AND gate: satisfied when prog[item] >= threshold
_ROUTE = 1  # member of a bucket's route OR-group: present when prog[item] >= 1


def build_pp_index(world: "PokepelagoWorld") -> None:
    """Build the static reverse index used for incremental counter maintenance.

    Produces, on ``world``:
      * ``_pp_group_buckets[group_key]`` -> list of bucket dicts, each with:
            "count":       Pokemon count for the bucket
            "n_and":       number of single-item AND gates in the bucket
            "has_route":   bool, whether the bucket has a route OR-group
      * ``_pp_index[item_name]`` -> list of (group_key, bucket_idx, kind, threshold)
    Both global and per-type groups are indexed. Buckets with NO gates at all are
    always satisfied; they are pre-counted into ``_pp_base[group_key]`` so they
    never need per-state tracking.
    """
    group_sources: dict[str, list] = {"global": world._milestone_req_groups}
    for type_name, groups in world._type_milestone_req_groups.items():
        group_sources[type_name] = groups

    group_buckets: dict[str, list[dict]] = {}
    index: dict[str, list[tuple]] = {}
    base: dict[str, int] = {}

    for group_key, groups in group_sources.items():
        buckets: list[dict] = []
        always_count = 0
        for region_req, type_reqs, extra_reqs, route_reqs, line_req, count in groups:
            n_and = 0
            has_route = bool(route_reqs)
            local_index: list[tuple] = []  # (item, kind, threshold)

            if region_req:
                n_and += 1
                local_index.append((region_req, _AND, 1))
            for tk in type_reqs:
                n_and += 1
                local_index.append((tk, _AND, 1))
            for item, n in extra_reqs:
                n_and += 1
                local_index.append((item, _AND, n))
            if line_req:
                n_and += 1
                local_index.append((line_req, _AND, 1))
            for rk in route_reqs:
                local_index.append((rk, _ROUTE, 1))

            if n_and == 0 and not has_route:
                # Unconditional bucket: always satisfied, never tracked.
                always_count += count
                continue

            bucket_idx = len(buckets)
            buckets.append({"count": count, "n_and": n_and, "has_route": has_route})
            for item, kind, thr in local_index:
                index.setdefault(item, []).append((group_key, bucket_idx, kind, thr))

        group_buckets[group_key] = buckets
        base[group_key] = always_count

    world._pp_group_buckets = group_buckets
    world._pp_index = index
    world._pp_base = base


class PokepelagoLogicMixin(LogicMixin):
    """CollectionState mixin maintaining the per-player accessible-Pokemon counters.

    Storage (all keyed by player, then group_key):
      * pp_accessible[player][group_key] -> int running count of accessible Pokemon
      * pp_unmet_and[player][group_key]  -> list[int] unmet AND-gates per bucket
      * pp_route_present[player][group_key] -> list[int] present route items per bucket
      * pp_inited[player] -> bool, whether the full scan has run for this player
    """

    pp_accessible: dict[int, dict[str, int]]
    pp_unmet_and: dict[int, dict[str, list[int]]]
    pp_route_present: dict[int, dict[str, list[int]]]
    pp_inited: dict[int, bool]

    def init_mixin(self, parent) -> None:
        self.pp_accessible = {}
        self.pp_unmet_and = {}
        self.pp_route_present = {}
        self.pp_inited = {}

    def copy_mixin(self, other: "PokepelagoLogicMixin") -> "PokepelagoLogicMixin":
        # Deep-copy the mutable per-player structures (Counter/list copies).
        other.pp_accessible = {p: d.copy() for p, d in self.pp_accessible.items()}
        other.pp_unmet_and = {p: {g: lst[:] for g, lst in gd.items()}
                              for p, gd in self.pp_unmet_and.items()}
        other.pp_route_present = {p: {g: lst[:] for g, lst in gd.items()}
                                  for p, gd in self.pp_route_present.items()}
        other.pp_inited = self.pp_inited.copy()
        return other


def pp_ensure(state: "PokepelagoLogicMixin", world: "PokepelagoWorld", player: int) -> bool:
    """Lazily initialize the counters for ``player`` from current prog_items.

    Returns True if the player's counters are ready to use (i.e. the world has a
    built index), False otherwise (caller should fall back to a direct scan —
    only possible before set_rules, where milestone rules are never evaluated).
    """
    if state.pp_inited.get(player):
        return True
    group_buckets = getattr(world, "_pp_group_buckets", None)
    if group_buckets is None:
        return False

    prog = state.prog_items[player]
    accessible: dict[str, int] = {}
    unmet_and: dict[str, list[int]] = {}
    route_present: dict[str, list[int]] = {}
    base = world._pp_base
    index = world._pp_index

    # Start every bucket at "all AND gates unmet, no route present".
    for group_key, buckets in group_buckets.items():
        unmet_and[group_key] = [b["n_and"] for b in buckets]
        route_present[group_key] = [0] * len(buckets)
        accessible[group_key] = base[group_key]

    # Walk only items the player actually has, crediting their conditions.
    for item, qty in prog.items():
        if qty <= 0:
            continue
        conds = index.get(item)
        if not conds:
            continue
        for group_key, bucket_idx, kind, thr in conds:
            if kind == _AND:
                if qty >= thr:
                    unmet_and[group_key][bucket_idx] -= 1
            else:  # _ROUTE
                route_present[group_key][bucket_idx] += 1

    # Credit buckets that ended up satisfied.
    for group_key, buckets in group_buckets.items():
        ua = unmet_and[group_key]
        rp = route_present[group_key]
        acc = accessible[group_key]
        for bi, b in enumerate(buckets):
            if ua[bi] == 0 and (not b["has_route"] or rp[bi] >= 1):
                acc += b["count"]
        accessible[group_key] = acc

    state.pp_accessible[player] = accessible
    state.pp_unmet_and[player] = unmet_and
    state.pp_route_present[player] = route_present
    state.pp_inited[player] = True
    return True


def pp_apply(state: "PokepelagoLogicMixin", world: "PokepelagoWorld", player: int,
             item_name: str, delta: int) -> None:
    """Incrementally update counters after ``prog_items[player][item_name]`` changed.

    ``delta`` is the signed change already applied to prog_items (+count on
    collect, -count on remove). Only buckets referencing ``item_name`` move.
    """
    # If the counter was not yet initialized for this player, pp_ensure does a full
    # scan of the CURRENT prog_items — which already reflects this item's new count
    # (the base collect/remove ran before us). In that case the delta is already
    # baked in and applying it again would double-count, so we return early.
    already_inited = state.pp_inited.get(player, False)
    if not pp_ensure(state, world, player):
        return
    if not already_inited:
        return
    conds = world._pp_index.get(item_name)
    if not conds:
        return

    prog = state.prog_items[player]
    new_qty = prog.get(item_name, 0)        # Counter: absent -> 0
    old_qty = new_qty - delta

    accessible = state.pp_accessible[player]
    unmet_and = state.pp_unmet_and[player]
    route_present = state.pp_route_present[player]
    group_buckets = world._pp_group_buckets

    for group_key, bucket_idx, kind, thr in conds:
        buckets = group_buckets[group_key]
        b = buckets[bucket_idx]
        ua = unmet_and[group_key]
        rp = route_present[group_key]

        was_sat = ua[bucket_idx] == 0 and (not b["has_route"] or rp[bucket_idx] >= 1)

        if kind == _AND:
            old_met = old_qty >= thr
            new_met = new_qty >= thr
            if new_met and not old_met:
                ua[bucket_idx] -= 1
            elif old_met and not new_met:
                ua[bucket_idx] += 1
        else:  # _ROUTE
            old_present = old_qty >= 1
            new_present = new_qty >= 1
            if new_present and not old_present:
                rp[bucket_idx] += 1
            elif old_present and not new_present:
                rp[bucket_idx] -= 1

        now_sat = ua[bucket_idx] == 0 and (not b["has_route"] or rp[bucket_idx] >= 1)

        if now_sat and not was_sat:
            accessible[group_key] += b["count"]
        elif was_sat and not now_sat:
            accessible[group_key] -= b["count"]
