"""BUG-25 (F1): a degenerate micro-region must never be *rolled* as the only region.

Hisui has 7 Pokemon against 72+ for every other region, so as the sole active region it
supplies ~37 locations that are nearly all self-gated and a heavy lock stack FillErrors
(see the 0.6.3 index fuzz, seeds 883 / 3248). _select_active_regions therefore drops
sub-threshold regions from single-unit random draws, while leaving multi-region draws and
the manual `regions:` list completely alone.
"""
import random
import unittest

from test.bases import WorldTestBase
from worlds.pokepelago.data import (GAME_REGIONS, GAME_GENERATIONS, REGION_MON_COUNTS,
                                    MICRO_REGION_MON_THRESHOLD)

MICRO_REGIONS = [r for r in GAME_REGIONS if REGION_MON_COUNTS[r] < MICRO_REGION_MON_THRESHOLD]


class TestMicroRegionData(WorldTestBase):
    """The threshold has to actually single out Hisui, or the fix means nothing."""
    game = "Pokepelago"

    def test_hisui_is_the_only_micro_region(self):
        self.assertEqual(MICRO_REGIONS, ["Hisui"])
        self.assertEqual(REGION_MON_COUNTS["Hisui"], 7)
        # Next smallest must sit clear of the threshold, so the line isn't arbitrary.
        others = sorted(v for r, v in REGION_MON_COUNTS.items() if r != "Hisui")
        self.assertGreater(others[0], MICRO_REGION_MON_THRESHOLD)


class _SelectionProbe:
    """Drives _select_active_regions directly with a seeded RNG, no full generation."""

    def __init__(self, seed, rrc, grouping):
        from worlds.pokepelago import PokepelagoWorld
        self.random = random.Random(seed)
        self.options = self  # the method only reads options.<name>.value
        self.random_region_count = _Val(rrc)
        self.group_hisui_galar = _Val(grouping)
        self.regions = _Val(frozenset())
        self._select = PokepelagoWorld._select_active_regions.__get__(self)

    def roll(self):
        self._select()
        return self.active_regions


class _Val:
    def __init__(self, value):
        self.value = value


class TestMicroRegionNeverRolledAlone(WorldTestBase):
    game = "Pokepelago"

    def test_single_unit_roll_never_yields_a_micro_region(self):
        """rrc=1, grouping off: the 883 / 3248 repro path. 2000 draws, no lone Hisui."""
        seen = set()
        for seed in range(2000):
            rolled = _SelectionProbe(seed, 1, 0).roll()
            self.assertEqual(len(rolled), 1)
            self.assertNotIn(rolled[0], MICRO_REGIONS,
                             f"seed {seed} rolled lone micro-region {rolled}")
            seen.add(rolled[0])
        # The other nine regions all stay reachable: we filtered, not collapsed.
        self.assertEqual(seen, set(GAME_REGIONS) - set(MICRO_REGIONS))

    def test_micro_region_still_rollable_in_multi_region_sets(self):
        """Hisui must remain a legal pick whenever 2+ regions are drawn."""
        hits = 0
        for seed in range(500):
            if "Hisui" in _SelectionProbe(seed, 3, 0).roll():
                hits += 1
        self.assertGreater(hits, 0, "Hisui vanished from multi-region rolls")

    def test_fully_random_count_never_yields_a_lone_micro_region(self):
        """rrc=-1 rolls the count too; the count==1 branch must still be filtered."""
        singles = 0
        for seed in range(2000):
            rolled = _SelectionProbe(seed, -1, 0).roll()
            if len(rolled) == 1:
                singles += 1
                self.assertNotIn(rolled[0], MICRO_REGIONS,
                                 f"seed {seed} rolled lone micro-region {rolled}")
        self.assertGreater(singles, 0, "no single-region rolls sampled, test is vacuous")

    def test_grouped_single_unit_rolls_are_unaffected(self):
        """With grouping on, Gen 8 = Galar + Hisui (96 mons) is above the threshold."""
        gen8 = next(g for g in GAME_GENERATIONS if "Hisui" in g)
        self.assertGreaterEqual(sum(REGION_MON_COUNTS[r] for r in gen8),
                                MICRO_REGION_MON_THRESHOLD)
        hits = 0
        for seed in range(500):
            rolled = _SelectionProbe(seed, 1, 1).roll()
            if "Hisui" in rolled:
                hits += 1
                self.assertIn("Galar", rolled)
        self.assertGreater(hits, 0, "Gen 8 never rolled, grouped pool was filtered wrongly")


class TestManualMicroRegionSoloStillHonored(WorldTestBase):
    """F4: an explicit `regions: [Hisui]` is still honored, locks left as chosen.

    This is the documented residual corner. Locks are off here so the world generates;
    the point under test is that the manual list is not filtered or overridden.
    """
    game = "Pokepelago"
    options = {
        "regions": {"Hisui"},
        "random_region_count": 0,
        "type_locks": 0,
        "region_locks": 0,
        "line_locks": 0,
    }

    def test_manual_solo_hisui_is_respected(self):
        self.assertEqual(self.world.active_regions, ["Hisui"])


class TestManualMicroRegionHeavyLocksRejected(unittest.TestCase):
    """F4 hardening (2026-08-31): an explicit solo micro-region plus two or more lock
    options is rejected up front with OptionError (which generation tooling treats as
    invalid YAML), instead of proceeding into a likely mid-fill FillError."""

    def test_solo_hisui_with_two_locks_raises_option_error(self):
        from Options import OptionError
        from test.general import setup_multiworld
        from worlds.pokepelago import PokepelagoWorld
        with self.assertRaises(OptionError) as ctx:
            setup_multiworld(PokepelagoWorld, options={
                "regions": {"Hisui"},
                "random_region_count": 0,
                "type_locks": 1,
                "line_locks": 1,
            })
        self.assertIn("only active region", str(ctx.exception))
