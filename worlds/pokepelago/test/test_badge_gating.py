"""Guards compute_badge_requirement against the BUG-18 non-monotonicity class.

BUG-18 (Discord 2026-05-30..06-01): badge gates were not monotone within an
evolution line -- a later evolution could become guessable before its own
mid-line pre-evolution. Root cause was the old FAMILY_BASE fallback, which gave
an evolution-only Pokemon the *family root's* encounter tier, skipping every
intermediate evolution (e.g. Arboliva fell back to Smoliv and unlocked before
Dolliv; Hydreigon fell back to Deino and unlocked before Zweilous).

The fix derives gates from an immediate-pre-evolution chain (PRE_EVOLUTION) and
clamps each Pokemon's tier to be at least its pre-evolution's. These tests assert
the invariant directly (no gate below a pre-evolution) plus the specific reported
cases. They import only route_data (no seed/option dependence).
"""
import unittest

from worlds.pokepelago.route_data import (
    compute_badge_requirement,
    BADGE_LEVEL_THRESHOLDS,
    PRE_EVOLUTION,
    EVOLUTION_MIN_LEVEL,
    POKEMON_ROUTES,
)

MAX_TIER = len(BADGE_LEVEL_THRESHOLDS)


class TestBadgeGatingMonotonicity(unittest.TestCase):
    """A Pokemon's badge gate must never be looser than its pre-evolution's."""

    def test_no_pokemon_gated_below_its_pre_evolution(self):
        """The core BUG-18 invariant, asserted across the whole dex."""
        offenders = []
        for mon_id, pre_id in PRE_EVOLUTION.items():
            if compute_badge_requirement(mon_id) < compute_badge_requirement(pre_id):
                offenders.append(
                    (mon_id, compute_badge_requirement(mon_id),
                     pre_id, compute_badge_requirement(pre_id))
                )
        self.assertEqual(
            offenders, [],
            f"{len(offenders)} Pokemon gated below their pre-evolution: {offenders[:20]}"
        )

    def test_reported_repros_fixed(self):
        """The two Discord-reported lines: the later evo gates no earlier than the mid evo."""
        # Smoliv (928) -> Dolliv (929, evolves @25) -> Arboliva (930, evolves @35)
        self.assertGreaterEqual(compute_badge_requirement(930), compute_badge_requirement(929))
        self.assertGreater(compute_badge_requirement(930), compute_badge_requirement(928))
        # Deino (633) -> Zweilous (634, evolves @50) -> Hydreigon (635, evolves @64)
        self.assertGreaterEqual(compute_badge_requirement(635), compute_badge_requirement(634))
        self.assertGreater(compute_badge_requirement(634), compute_badge_requirement(633))

    def test_level_evolution_gates_at_least_its_evolution_level(self):
        """An evolution-only, level-based evo is gated no lower than its evolution level."""
        def level_tier(level):
            for i, t in enumerate(BADGE_LEVEL_THRESHOLDS):
                if level <= t:
                    return i
            return MAX_TIER
        for mon_id, lvl in EVOLUTION_MIN_LEVEL.items():
            # only meaningful for evolution-only mons (no own wild encounters)
            if not POKEMON_ROUTES.get(mon_id):
                self.assertGreaterEqual(
                    compute_badge_requirement(mon_id), level_tier(lvl),
                    f"#{mon_id} evolves at level {lvl} but gates below that level's tier"
                )

    def test_stone_trade_evos_inherit_pre_evolution_tier(self):
        """Stone/trade evos (no level) with no wild encounters match their pre-evo exactly.

        Bellossom (182, Gloom + Sun Stone) is the canonical case from the thread:
        it must not over-gate beyond its pre-evolution Gloom (44).
        """
        for mon_id, pre_id in PRE_EVOLUTION.items():
            is_level_evo = mon_id in EVOLUTION_MIN_LEVEL
            wild = bool(POKEMON_ROUTES.get(mon_id))
            if not is_level_evo and not wild:
                self.assertEqual(
                    compute_badge_requirement(mon_id), compute_badge_requirement(pre_id),
                    f"non-level, non-wild evo #{mon_id} should inherit pre-evo #{pre_id}'s tier"
                )
        # explicit Bellossom check
        self.assertEqual(compute_badge_requirement(182), compute_badge_requirement(44))

    def test_tiers_in_valid_range_and_deterministic(self):
        ids = set(PRE_EVOLUTION) | set(POKEMON_ROUTES) | set(EVOLUTION_MIN_LEVEL)
        for mon_id in ids:
            tier = compute_badge_requirement(mon_id)
            self.assertGreaterEqual(tier, 0)
            self.assertLessEqual(tier, MAX_TIER)
            # idempotent: the internal _seen accumulator must not leak between calls
            self.assertEqual(tier, compute_badge_requirement(mon_id))

    def test_base_form_with_no_data_is_hardest_gated(self):
        """A Pokemon with no pre-evolution and no encounters defaults to the top tier."""
        # synthetic id guaranteed absent from all data
        synthetic = 999999
        self.assertNotIn(synthetic, PRE_EVOLUTION)
        self.assertNotIn(synthetic, POKEMON_ROUTES)
        self.assertEqual(compute_badge_requirement(synthetic), MAX_TIER)


if __name__ == "__main__":
    unittest.main()
