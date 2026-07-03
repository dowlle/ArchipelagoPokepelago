"""
FEAT-15 local-filler tests for the Pokepelago APWorld.

The local_filler_percent option pre-places a fraction of THIS world's own filler
onto THIS world's own locations before the multiworld fill, keeping it out of other
players' games. The behavior only manifests in a MULTIWORLD (the existing suite is
solo-only), so these tests build 2-player Pokepelago multiworlds.

Covered:
  - completability + fill still succeed with the option on (WorldTestBase classes)
  - items == locations across players (no item dropped or duplicated)
  - localization actually reduces this world's filler reaching OTHER games
  - the max-exploration reachability sweep is NOT throttled under heavy locks
  - dexsanity-off 'auto' is a no-op
  - determinism: same seed -> identical localized placement
  - item_links smoke: pre_fill does not crash and invariants hold when links exist

Hash-randomization determinism is covered separately by test_determinism.py
(subprocess isolation); this file's determinism check is same-process, same-seed.
"""
import unittest
from argparse import Namespace

from BaseClasses import MultiWorld, CollectionState
from Fill import distribute_items_restrictive
from test.bases import WorldTestBase
from test.general import setup_multiworld
from worlds.AutoWorld import AutoWorldRegister, call_all

WORLD_TYPE = AutoWorldRegister.world_types["Pokepelago"]

# Modest configs: enough gating to exercise the sweep, small enough to fill fast.
LOCKS_2R = {
    "regions": {"Kanto", "Johto"},
    "type_locks": 1,
    "region_locks": 1,
    "dexsanity": 1,
    "starter_region": 1,  # Kanto
}
LOCKS_3R = {
    "regions": {"Kanto", "Johto", "Hoenn"},
    "type_locks": 1,
    "region_locks": 1,
    "dexsanity": 1,
    "starter_region": 1,
}


# ── WorldTestBase classes: generation completes + seed is completable (inherited) ──

class TestLocalFiller90(WorldTestBase):
    """All locks, dexsanity, 90% local filler: still fills + completable."""
    game = "Pokepelago"
    options = {**LOCKS_3R, "local_filler_percent": 90}


class TestLocalFiller100(WorldTestBase):
    """100% local filler: no filler travels; still fills + completable."""
    game = "Pokepelago"
    options = {**LOCKS_3R, "local_filler_percent": 100}


class TestLocalFillerAuto(WorldTestBase):
    """auto (the default): still fills + completable."""
    game = "Pokepelago"
    options = {**LOCKS_3R, "local_filler_percent": "auto"}


# ── Helpers ───────────────────────────────────────────────────────────────────────

def _filler_locs(mw, owner_player):
    """Filled real locations OWNED by owner_player whose item is filler (non-adv)."""
    return [loc for loc in mw.get_locations()
            if loc.player == owner_player and loc.address is not None
            and loc.item is not None and not loc.item.advancement]


def _local_filler_fraction(mw, player):
    """After pre_fill (before main fill), fraction of player's own filler that got
    localized onto the player's own locations vs still sitting in the shared pool."""
    localized = [loc for loc in _filler_locs(mw, player) if loc.item.player == player]
    in_pool = [it for it in mw.itempool if it.player == player and not it.advancement]
    total = len(localized) + len(in_pool)
    return (len(localized) / total) if total else 0.0, len(localized), total


def _remote_own_filler(mw, player):
    """After full fill, count this player's filler items placed in OTHER players' worlds."""
    return sum(1 for loc in mw.get_locations()
               if loc.player != player and loc.item is not None
               and loc.item.player == player and not loc.item.advancement)


def _assert_items_equal_locations(test, mw):
    """Every location filled after the fill (items == locations, nothing dropped).
    distribute_items_restrictive works on a copy of multiworld.itempool and never
    clears the original list, so the real signal is zero unfilled locations -- if
    pre_fill had dropped or duplicated an item the fill could not fully complete."""
    unfilled = mw.get_unfilled_locations()
    test.assertEqual(len(unfilled), 0,
                     f"{len(unfilled)} unfilled locations after fill")


def _build_with_links(options_list, item_links_list, seed=777):
    """Faithful Main.py ordering for an item_links multiworld: set_item_links ->
    gen steps through generate_basic -> link_items -> pre_fill. Returns the
    multiworld with pre_fill done (caller runs the main fill)."""
    world_type = AutoWorldRegister.world_types["Pokepelago"]
    players = len(options_list)
    mw = MultiWorld(players)
    mw.game = {p: "Pokepelago" for p in range(1, players + 1)}
    mw.player_name = {p: f"Tester{p}" for p in range(1, players + 1)}
    mw.set_seed(seed)
    args = Namespace()
    for p, overrides in enumerate(options_list, 1):
        merged = dict(overrides)
        merged["item_links"] = item_links_list[p - 1]
        for key, option in world_type.options_dataclass.type_hints.items():
            cur = getattr(args, key, {})
            cur[p] = option.from_any(merged.get(key, option.default))
            setattr(args, key, cur)
    mw.set_options(args)
    mw.set_item_links()
    mw.state = CollectionState(mw)
    for step in ("generate_early", "create_regions", "create_items", "set_rules",
                 "connect_entrances", "generate_basic"):
        call_all(mw, step)
    mw.link_items()
    call_all(mw, "pre_fill")
    return mw


# ── Behavior tests ────────────────────────────────────────────────────────────────

class TestLocalFillerMultiworld(unittest.TestCase):

    def test_items_equal_locations_two_players(self):
        """90% local on a 2-Pokepelago multiworld still fills cleanly."""
        mw = setup_multiworld([WORLD_TYPE, WORLD_TYPE],
                              options=[{**LOCKS_2R, "local_filler_percent": 90}] * 2,
                              seed=101)
        distribute_items_restrictive(mw)
        _assert_items_equal_locations(self, mw)

    def test_localization_reduces_remote_filler(self):
        """Turning local_filler_percent up strictly reduces this world's filler that
        floods the other player's world."""
        base = {**LOCKS_2R}
        mw_off = setup_multiworld([WORLD_TYPE, WORLD_TYPE],
                                  options=[{**base, "local_filler_percent": 0}] * 2, seed=202)
        distribute_items_restrictive(mw_off)
        remote_off = _remote_own_filler(mw_off, 1)

        mw_hi = setup_multiworld([WORLD_TYPE, WORLD_TYPE],
                                 options=[{**base, "local_filler_percent": 90}] * 2, seed=202)
        distribute_items_restrictive(mw_hi)
        remote_hi = _remote_own_filler(mw_hi, 1)

        _assert_items_equal_locations(self, mw_off)
        _assert_items_equal_locations(self, mw_hi)
        self.assertGreater(remote_off, 0, "baseline should flood some filler out")
        self.assertLess(remote_hi, remote_off,
                        f"90% local ({remote_hi}) should send out less than 0% ({remote_off})")

    def test_sweep_not_throttled_under_locks(self):
        """The max-exploration sweep must let a locks-heavy world localize near its
        target. Without the sweep, bare-state reachability is ~2% and localization
        collapses; this guards that regression."""
        mw = setup_multiworld([WORLD_TYPE, WORLD_TYPE],
                              options=[{**LOCKS_2R, "local_filler_percent": 90}] * 2, seed=303)
        frac, localized, total = _local_filler_fraction(mw, 1)
        self.assertGreater(total, 50, "expected a large filler pool with dexsanity on")
        self.assertGreaterEqual(
            frac, 0.8,
            f"only {frac:.0%} localized ({localized}/{total}); the reachability sweep "
            f"is likely throttling under locks")

    def test_dexsanity_off_auto_is_noop(self):
        """auto with dexsanity off resolves to 0% and localizes nothing."""
        mw = setup_multiworld([WORLD_TYPE, WORLD_TYPE],
                              options=[{"dexsanity": 0, "local_filler_percent": "auto"}] * 2,
                              seed=404)
        w1 = mw.worlds[1]
        self.assertEqual(w1._effective_local_filler_percent(), 0)
        localized = [loc for loc in _filler_locs(mw, 1) if loc.item.player == 1]
        self.assertEqual(localized, [], "nothing should be localized when auto -> 0")

    def test_determinism_same_seed(self):
        """Same seed -> identical localized placement (same-process)."""
        def placement(seed):
            mw = setup_multiworld([WORLD_TYPE, WORLD_TYPE],
                                  options=[{**LOCKS_2R, "local_filler_percent": 90}] * 2,
                                  seed=seed)
            return {loc.name: loc.item.name
                    for loc in _filler_locs(mw, 1) if loc.item.player == 1}
        self.assertEqual(placement(505), placement(505))

    def test_item_links_smoke(self):
        """pre_fill must not crash and invariants must hold when item_links group
        some of this world's filler (Master Ball) across both players."""
        link = [{"name": "shared_mb", "item_pool": ["Master Ball"],
                 "replacement_item": None, "link_replacement": True}]
        mw = _build_with_links([{**LOCKS_2R, "local_filler_percent": 90}] * 2,
                               [link, link], seed=606)
        distribute_items_restrictive(mw)
        _assert_items_equal_locations(self, mw)
