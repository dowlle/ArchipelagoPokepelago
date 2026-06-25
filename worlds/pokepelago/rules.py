"""
Custom rule_builder rules for Pokepelago.

CanAccessNPokemon: checks whether >= N Pokemon are logically accessible,
used for milestone locations and the victory condition.
"""
from __future__ import annotations

import dataclasses
from typing import TYPE_CHECKING, ClassVar

from typing_extensions import override

from BaseClasses import CollectionState
from NetUtils import JSONMessagePart
from rule_builder.rules import Rule

if TYPE_CHECKING:
    from worlds.pokepelago import PokepelagoWorld


@dataclasses.dataclass()
class CanAccessNPokemon(Rule["PokepelagoWorld"], game="Pokepelago"):
    """Rule that checks if the player can logically access at least `target_count` Pokemon.

    Works by summing pre-grouped requirement buckets: each bucket has a region pass,
    type key set, extra gate set, and a count of Pokemon sharing those exact requirements.
    """

    target_count: int
    group_key: str = "global"
    """'global' for overall milestones, or a type name (e.g. 'Fire') for type milestones."""

    @override
    def _instantiate(self, world: "PokepelagoWorld") -> Rule.Resolved:
        if self.group_key == "global":
            groups = world._milestone_req_groups
        else:
            groups = world._type_milestone_req_groups.get(self.group_key, [])

        # Convert to a hashable tuple-of-tuples for the frozen Resolved dataclass.
        # Format: (region_req, type_reqs, extra_reqs, route_reqs, line_req, count)
        frozen_groups = tuple(
            (rr,
             tuple(sorted(tr)) if tr else (),
             tuple(sorted(er)) if er else (),
             tuple(sorted(rtr)) if rtr else (),
             lr,
             c)
            for rr, tr, er, rtr, lr, c in groups
        )

        return self.Resolved(
            target_count=self.target_count,
            req_groups=frozen_groups,
            group_key=self.group_key,
            player=world.player,
            caching_enabled=getattr(world, "rule_caching_enabled", False),
        )

    class Resolved(Rule.Resolved):
        target_count: int
        req_groups: tuple
        """Tuple of (region_req, type_reqs, extra_reqs, route_reqs, line_req, count) buckets."""
        group_key: str = "global"
        """Which milestone group this rule counts ('global' or a type name). Used to
        read the matching incrementally-maintained counter (LEVER 1)."""

        force_recalculate: ClassVar[bool] = True
        """Milestone rules depend on aggregate item state — always re-evaluate.
        (Only relevant if the world used the rule_builder cache; it does not.
        LEVER 1 maintains its own O(1) counter instead.)"""

        @override
        def _evaluate(self, state: CollectionState) -> bool:
            # LEVER 1: O(1) read of the incrementally-maintained accessible counter.
            # The counter is kept current by PokepelagoWorld.collect/remove via the
            # PokepelagoLogicMixin (logic_mixin.py). pp_ensure lazily runs a one-time
            # full scan if this state's counter is not initialized yet. If the world
            # has no index built (only before set_rules, where milestone rules are
            # never evaluated), pp_ensure returns False and we fall back to the scan.
            from .logic_mixin import pp_ensure
            world = state.multiworld.worlds[self.player]
            if pp_ensure(state, world, self.player):
                return state.pp_accessible[self.player][self.group_key] >= self.target_count
            return self._scan_evaluate(state)

        def _scan_evaluate(self, state: CollectionState) -> bool:
            """Original per-call bucket scan. Kept as the pre-index fallback and as the
            arithmetic oracle the incremental counter is validated against."""
            accessible = 0
            prog = state.prog_items[self.player]
            for region_req, type_reqs, extra_reqs, route_reqs, line_req, count in self.req_groups:
                if region_req and prog[region_req] < 1:
                    continue
                if type_reqs:
                    if any(prog[tk] < 1 for tk in type_reqs):
                        continue
                if extra_reqs:
                    if any(prog[item] < n for item, n in extra_reqs):
                        continue
                if route_reqs:
                    if not any(prog[rk] >= 1 for rk in route_reqs):
                        continue
                if line_req and prog[line_req] < 1:
                    continue
                accessible += count
                if accessible >= self.target_count:
                    return True
            return False

        @override
        def item_dependencies(self) -> dict[str, set[int]]:
            items: dict[str, set[int]] = {}
            self_id = {id(self)}
            for region_req, type_reqs, extra_reqs, route_reqs, line_req, _ in self.req_groups:
                if region_req:
                    items.setdefault(region_req, set()).update(self_id)
                for tk in type_reqs:
                    items.setdefault(tk, set()).update(self_id)
                for item, _ in extra_reqs:
                    items.setdefault(item, set()).update(self_id)
                for rk in route_reqs:
                    items.setdefault(rk, set()).update(self_id)
                if line_req:
                    items.setdefault(line_req, set()).update(self_id)
            return items

        @override
        def explain_str(self, state: CollectionState | None = None) -> str:
            if state is None:
                return f"Need {self.target_count} accessible Pokemon"
            accessible = 0
            prog = state.prog_items[self.player]
            for region_req, type_reqs, extra_reqs, route_reqs, line_req, count in self.req_groups:
                if region_req and prog[region_req] < 1:
                    continue
                if type_reqs and any(prog[tk] < 1 for tk in type_reqs):
                    continue
                if extra_reqs and any(prog[item] < n for item, n in extra_reqs):
                    continue
                if route_reqs and not any(prog[rk] >= 1 for rk in route_reqs):
                    continue
                if line_req and prog[line_req] < 1:
                    continue
                accessible += count
            met = accessible >= self.target_count
            status = "Met" if met else "Not met"
            return f"{status}: {accessible}/{self.target_count} Pokemon accessible"

        @override
        def explain_json(self, state: CollectionState | None = None) -> list[JSONMessagePart]:
            if state is None:
                return [{"type": "text", "text": f"Need {self.target_count} accessible Pokemon"}]

            accessible = 0
            prog = state.prog_items[self.player]
            for region_req, type_reqs, extra_reqs, route_reqs, line_req, count in self.req_groups:
                if region_req and prog[region_req] < 1:
                    continue
                if type_reqs and any(prog[tk] < 1 for tk in type_reqs):
                    continue
                if extra_reqs and any(prog[item] < n for item, n in extra_reqs):
                    continue
                if route_reqs and not any(prog[rk] >= 1 for rk in route_reqs):
                    continue
                if line_req and prog[line_req] < 1:
                    continue
                accessible += count

            met = accessible >= self.target_count
            color = "green" if met else "salmon"
            return [
                {"type": "color", "color": color, "text": str(accessible)},
                {"type": "text", "text": f"/{self.target_count} Pokemon accessible"},
            ]
