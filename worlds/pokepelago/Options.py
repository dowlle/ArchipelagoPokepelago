from dataclasses import dataclass
from Options import PerGameCommonOptions, Toggle, Choice, Range, NamedRange, OptionCounter, OptionSet, OptionGroup, Visibility
from .data import GAME_REGIONS


class Dexsanity(Toggle):
    """If enabled, each Pokemon has its own location check ('Guess {Pokemon}').
    Access is gated by whichever lock options are active (Type Keys, Region Passes,
    Route Keys, Line Unlocks, Gym Badges, etc.).
    Disabling removes all per-Pokemon locations, leaving only milestone-based checks.
    Automatically enabled when Route Locks or Line Locks is on."""
    display_name = "Dexsanity"
    default = 1


class EnableTypeLocks(Toggle):
    """If enabled, guessing a Pokemon requires all Type Keys matching its elemental types
    (e.g. Bulbasaur needs both Grass Type Key and Poison Type Key).

    Generation cost: adds one progression item per active type (up to 18).
    Pokemon of a type can only be caught with that Type Key, so most Type Keys
    must go in non-type-gated locations (starting slots + "Guessed N" milestones
    + dexsanity "Guess X" locations). Disabling Dexsanity removes the per-Pokemon
    locations and can squeeze Type Key placement on small regions -- see the
    Hisui-only case in the backlog history and the Line Locks perf note below."""
    display_name = "Enable Type Locks"
    default = 1


class RegionLocks(Toggle):
    """If enabled, non-starting regions require a Region Pass item to access.
    Disabling this makes all selected regions freely accessible from the start."""
    display_name = "Region Locks"
    default = 1


class StartingLocationCount(Range):
    """Number of free 'Oak\'s Lab' starting locations to include (0-8).
    These are immediately accessible checks (Oak\'s Parcel Delivery, Pokedex Received, etc.)
    that kickstart your adventure. Set to 0 to disable them entirely."""
    display_name = "Starting Location Count"
    range_start = 0
    range_end = 8
    default = 4


class Regions(OptionSet):
    """Which game regions to include. Each region adds its Pokemon to the pool.

    Provide a YAML list of region names, for example:
        regions:
          - Kanto
          - Johto
          - Hoenn
    (Inline form also works: regions: [Kanto, Johto, Hoenn].)

    At least one region is always active (defaults to Kanto if the list is empty).
    This manual list is honored by default. It is ONLY ignored if you set
    'random_region_count' to a non-zero value, which randomizes the regions instead.
    Valid regions: Kanto, Johto, Hoenn, Sinnoh, Unova, Kalos, Alola, Galar, Hisui, Paldea."""
    display_name = "Regions"
    valid_keys = frozenset(GAME_REGIONS)
    default = frozenset({"Kanto"})


class RandomRegionCount(NamedRange):
    """Override the manual Regions list with a random selection.
    Set to 0 (or disabled) to use the manual Regions list above (THIS IS THE DEFAULT,
    so your 'regions:' list is honored unless you change this).
    Set to 1-10 to ignore the manual list and randomly pick that many regions
    (or generations if grouping is on).
    Set to random to also randomize how many are picked.
    When 'Group Hisui & Galar' is enabled, this picks from 9 generation units
    (Gen 8 = Galar + Hisui together) instead of 10 individual regions."""
    display_name = "Random Region Count"
    range_start = 0
    range_end = 10
    special_range_names = {"disabled": 0, "random": -1}
    default = 0


class GroupHisuiGalar(Toggle):
    """When enabled, Galar and Hisui are treated as a single 'Gen 8' unit
    for random region selection. Picking Gen 8 always includes both regions.
    When disabled, Galar and Hisui are independent picks.
    Only affects random_region_count; the manual Regions list is unaffected."""
    display_name = "Group Hisui & Galar"
    default = 1


class GoalType(Choice):
    """How the goal is defined.
    Percentage: guess a percentage of the active Pokemon pool (see 'Goal Percentage').
    Count: guess a fixed number of Pokemon (see 'Goal Count')."""
    display_name = "Goal Type"
    option_percentage = 0
    option_count = 1
    default = 0


class GoalPercentage(Range):
    """Percentage of the active Pokemon pool that must be guessed to complete the game.
    Only used when 'Goal Type' is set to 'percentage'.
    For example, 80 with 386 active Pokemon means guessing 309 to win."""
    display_name = "Goal Percentage"
    range_start = 1
    range_end = 100
    default = 80


class GoalCount(Range):
    """Fixed number of Pokemon that must be guessed to complete the game.
    Only used when 'Goal Type' is set to 'count'.
    Automatically capped to the total active Pokemon across selected regions."""
    display_name = "Goal Count"
    range_start = 1
    range_end = 1025
    default = 151


class TrapChance(Range):
    """Percentage chance (0-100) that a filler item slot will be replaced by a trap item.
    0 means no traps; 100 means all filler items will be traps."""
    display_name = "Trap Chance"
    range_start = 0
    range_end = 100
    default = 5


class FillerWeights(OptionCounter):
    """Controls the relative weight of each filler item category.
    Higher values mean that category appears more often. Set a category to 0 to disable it entirely.
    Traps are controlled separately by the 'Trap Chance' option.
    Categories: master_ball, key_items, splash."""
    display_name = "Filler Item Weights"
    valid_keys = frozenset({"master_ball", "key_items", "splash"})
    default = {
        "master_ball": 50,
        "key_items":   100,
        "splash":      50,
    }

    @classmethod
    def from_any(cls, data):
        if isinstance(data, dict):
            merged = dict(cls.default)
            merged.update({k: v for k, v in data.items() if k in cls.valid_keys})
            return cls(merged)
        return super().from_any(data)


class LocalFillerPercent(NamedRange):
    """Percentage of this world's own filler items to force into this world's own
    locations before the multiworld fill runs, keeping them out of other players'
    games. Only filler is localized (Pokedex, Pokegear, Master Ball, Shiny Charm,
    traps, and the splash filler); progression and useful gate items are never
    localized, so the seed stays completable and cross-game progression is
    unaffected. Higher values keep more of Pokepelago's large Dexsanity filler pool
    out of an async/multiworld.

    Dexsanity can create up to ~1025 'Guess {Pokemon}' locations, which forces an
    equally large filler pool; without this, most of that filler floods other games.
    'off' (0) keeps the classic behavior. 'auto' (-1, the default) scales a forced
    minimum by how inflated the pool is: 0 when Dexsanity is off, otherwise 50% for
    one region and +10% per additional region, capped at 90% so some filler still
    travels to the rest of the multiworld."""
    display_name = "Local Filler Percent"
    range_start = 0
    range_end = 100
    special_range_names = {"off": 0, "auto": -1}
    default = -1


class TrapWeights(OptionCounter):
    """Controls the relative weight of each trap type when a trap slot is filled.
    Higher values mean that trap appears more often. Set a trap to 0 to disable it entirely.
    The overall chance of a trap appearing is controlled by 'Trap Chance'.
    Traps: small_shuffle, big_shuffle, derpy_mon, release."""
    display_name = "Trap Weights"
    valid_keys = frozenset({"small_shuffle", "big_shuffle", "derpy_mon", "release"})
    default = {
        "small_shuffle": 10,
        "big_shuffle":   5,
        "derpy_mon":     25,
        "release":       25,
    }

    @classmethod
    def from_any(cls, data):
        if isinstance(data, dict):
            merged = dict(cls.default)
            merged.update({k: v for k, v in data.items() if k in cls.valid_keys})
            return cls(merged)
        return super().from_any(data)


class StarterRegion(Choice):
    """Which game region your adventure starts in.
    Determines which Pokemon starters are available and which Type Keys begin pre-collected.
    'any': a random active region is chosen each seed.
    Specific region: must also be included in the Regions option.
    If the chosen region is not active, falls back to a random active region."""
    display_name = "Starter Region"
    option_any    = 0
    option_kanto  = 1
    option_johto  = 2
    option_hoenn  = 3
    option_sinnoh = 4
    option_unova  = 5
    option_kalos  = 6
    option_alola  = 7
    option_galar  = 8
    option_hisui  = 9
    option_paldea = 10
    default = 0


class StarterPokemon(Choice):
    """Which starter Pokemon to begin with.
    'any': a random starter from the starting region's list.
    'first'/'second'/'third': by position in the starting region's list.
    'random_starter': picks randomly from ALL regional starters across active regions.
    'random_any': picks from ALL active base-form Pokemon (fully random).
    Starter Count controls how many starters are chosen (1-3) for random modes."""
    display_name = "Starter Pokemon"
    option_any    = 0
    option_first  = 1
    option_second = 2
    option_third  = 3
    option_random_starter = 4
    option_random_any = 5
    default = 0


class StarterCount(Range):
    """How many starter Pokemon to begin with (1-3).
    Each starter pre-collects its Type Keys, Route Key, Line Unlock, and
    Region Pass (if the starter is in a non-starting region).
    More starters = more open early game with wider type/route/line coverage.
    Only used when Starter Pokemon is set to 'random_starter' or 'random_any'."""
    display_name = "Starter Count"
    range_start = 1
    range_end = 3
    default = 1


class PreferLabStarters(Toggle):
    """When Starter Pokemon is 'random', prefer traditional starters
    (Bulbasaur, Charmander, Squirtle, Chikorita, etc.) over wild Pokemon.
    Gives a 5x weight to Professor's Lab Pokemon in the random selection."""
    display_name = "Prefer Lab Starters"
    default = 1


class RouteLocks(Toggle):
    """Require Route Key items to access Pokemon by game area.
    Routes are grouped into meaningful areas (e.g. Melemele Island, Wild Area
    North, Hoenn Early Routes). Each area adds one Route Key to the item pool.
    A Pokemon is accessible if you have ANY area key for a route it appears on.
    Forces Dexsanity ON if it isn't already (needed for enough locations to
    hold all Route Keys); a logging.warning fires when that mutation happens.
    Route Locks and Line Locks compose independently and no longer auto-disable
    each other -- the two gating axes are orthogonal (they gate by different
    things: where a Pokemon is found vs. its evolution family).

    YAML key: route_locks_enabled (NOT route_locks). The dataclass attribute
    in PokepelagoOptions uses the _enabled suffix; AP silently ignores unknown
    keys, so a YAML with `route_locks: true` will generate with this option
    set to its default (0) and the setting will appear to have no effect."""
    display_name = "Route Locks"
    default = 0


class LineLocks(Toggle):
    """Require a Line Unlock item for each evolution family.
    Every active evolution family adds one Line Unlock to the item pool.
    Required for ALL members of the family (base forms and evolutions).
    Evolution-only Pokemon inherit route access from their base form.
    Forces Dexsanity ON if it isn't already (needed for enough locations to
    hold all Line Unlocks); a logging.warning fires when that mutation happens.
    Composes independently with Route Locks (no longer auto-disabled when
    Route Locks is also on). When the active region pool is too small for
    the number of progression items Line Locks would create, generation only
    *warns* about the estimated progression-to-location ratio -- it never
    silently disables the option (see the -- GENERATION PERFORMANCE -- note
    below for the heuristic and its threshold).

    -- GENERATION PERFORMANCE -------------------------------------------------
    Line Locks is the single biggest cost on generation time, because it adds
    one progression item per evolution family across every active region
    (~50-100 per region, 300+ across many regions). Stacking Line Locks with:

      - 5+ active regions, AND
      - Type Locks + Region Locks + Badge Level Gating, AND
      - 3+ of {legendary, trade, baby, fossil, paradox, stone, ultra_beast} locks

    ...pushes the progression-item count into the 700-900 range. `fill_restrictive`
    complexity scales with progression-items x locations, so these configs can
    take 30-60s to generate on modest hardware (vs. <5s for typical configs).
    The heuristic at `__init__.py:90-108` only WARNS (via logging.warning) when the
    estimated progression-to-location ratio exceeds 55% -- it no longer disables
    Line Locks. This flags likely FillError risk but not slow-but-completes
    generation. If you want all-locks-on with many regions, be prepared to
    wait on generation."""
    display_name = "Line Locks"
    default = 0


class BadgeLevelGating(Toggle):
    """Gate Pokemon behind Gym Badges based on their encounter level.
    Higher-level Pokemon require more badges (Lv1-10: 0 badges, Lv11-20: 1, etc.).
    When combined with Legendary Locks, uses the higher requirement of the two.
    Requires Gym Badges in the item pool (enabled automatically)."""
    display_name = "Badge Level Gating"
    default = 0


class LegendaryLocks(Toggle):
    """Gate legendary Pokemon behind Gym Badge items.
    Collect 6 Badges for sub-legendaries (trios, regis, tapus, etc.),
    7 Badges for box legendaries (version mascots), and
    8 Badges for mythics (event-only Pokemon like Mew, Celebi, Arceus).
    When Badge Level Gating is also on, uses the higher badge requirement.
    8 Gym Badge items are added to the item pool when enabled."""
    display_name = "Legendary Locks"
    default = 1


class TradeLocks(Toggle):
    """Require a Link Cable item before guessing trade-evolved Pokemon
    (Alakazam, Machamp, Golem, Gengar, Scizor, Steelix, Conkeldurr, etc.)."""
    display_name = "Trade Evolution Lock"
    default = 1


class BabyLocks(Toggle):
    """Require Daycare item(s) before guessing baby Pokemon
    (Pichu, Cleffa, Igglybuff, Togepi, Tyrogue, Smoochum, Elekid, Magby, etc.)."""
    display_name = "Baby Pokemon Lock"
    default = 0


class DaycareCount(Range):
    """Number of Daycare items required to unlock baby Pokemon.
    Only used when Baby Pokemon Lock is enabled.
    Set higher for a more gradual unlock; all copies must be received."""
    display_name = "Daycare Items Required"
    range_start = 1
    range_end = 5
    default = 1


class FossilLocks(Toggle):
    """Require a Fossil Restorer item before guessing fossil-revived Pokemon
    (Omanyte, Omastar, Kabuto, Kabutops, Aerodactyl, Lileep, Cranidos, etc.)."""
    display_name = "Fossil Lock"
    default = 0


class UltraBeastLocks(Toggle):
    """Require an Ultra Wormhole item before guessing Ultra Beasts
    (Nihilego through Blacephalon, plus Necrozma which also originates from Ultra Space)."""
    display_name = "Ultra Beast Lock"
    default = 0


class ParadoxLocks(Toggle):
    """Require a Time Rift item before guessing Paradox Pokemon
    (Great Tusk, Roaring Moon, Iron Valiant, etc., plus Koraidon and Miraidon).
    Only relevant when Paldea is active."""
    display_name = "Paradox Lock"
    default = 0


class StoneLocks(Toggle):
    """Require the matching evolutionary stone item before guessing stone-only evolutions.
    Each stone type that gates at least one active Pokemon adds one stone item to the pool.
    Examples: Fire Stone -> Arcanine/Ninetales/Flareon, Water Stone -> Starmie/Vaporeon/Cloyster."""
    display_name = "Stone Evolution Lock"
    default = 1


class MasterBallBypassGates(Toggle):
    """If enabled, Master Balls can catch any Pokemon regardless of lock gates.
    If disabled, Master Balls can only be used on Pokemon you could normally guess."""
    display_name = "Master Ball Bypasses Gates"
    default = 1


# -- Legacy backward-compat toggles (hidden from UI, consumed by generate_early) -----
# Old YAMLs used include_kanto/include_johto/... instead of the unified "regions" OptionSet.
class _LegacyRegionToggle(Toggle):
    """Deprecated -- use the 'regions' option instead."""
    visibility = Visibility.none  # hidden from options UI
    default = 0

class IncludeKanto(_LegacyRegionToggle):
    """Deprecated -- use the 'regions' option instead."""
    display_name = "Include Kanto (deprecated)"

class IncludeJohto(_LegacyRegionToggle):
    """Deprecated -- use the 'regions' option instead."""
    display_name = "Include Johto (deprecated)"

class IncludeHoenn(_LegacyRegionToggle):
    """Deprecated -- use the 'regions' option instead."""
    display_name = "Include Hoenn (deprecated)"

class IncludeSinnoh(_LegacyRegionToggle):
    """Deprecated -- use the 'regions' option instead."""
    display_name = "Include Sinnoh (deprecated)"

class IncludeUnova(_LegacyRegionToggle):
    """Deprecated -- use the 'regions' option instead."""
    display_name = "Include Unova (deprecated)"

class IncludeKalos(_LegacyRegionToggle):
    """Deprecated -- use the 'regions' option instead."""
    display_name = "Include Kalos (deprecated)"

class IncludeAlola(_LegacyRegionToggle):
    """Deprecated -- use the 'regions' option instead."""
    display_name = "Include Alola (deprecated)"

class IncludeGalar(_LegacyRegionToggle):
    """Deprecated -- use the 'regions' option instead."""
    display_name = "Include Galar (deprecated)"

class IncludeHisui(_LegacyRegionToggle):
    """Deprecated -- use the 'regions' option instead."""
    display_name = "Include Hisui (deprecated)"

class IncludePaldea(_LegacyRegionToggle):
    """Deprecated -- use the 'regions' option instead."""
    display_name = "Include Paldea (deprecated)"

_LEGACY_REGION_MAP: dict[str, str] = {
    "include_kanto": "Kanto", "include_johto": "Johto", "include_hoenn": "Hoenn",
    "include_sinnoh": "Sinnoh", "include_unova": "Unova", "include_kalos": "Kalos",
    "include_alola": "Alola", "include_galar": "Galar", "include_hisui": "Hisui",
    "include_paldea": "Paldea",
}


class IncludeShinies(Toggle):
    """Add Shiny Charm filler items to the item pool.
    Receiving a Shiny Charm makes a random Pokemon in your caught list display
    its shiny sprite. Purely cosmetic -- no gameplay effect."""
    display_name = "Include Shiny Charms"
    default = 1


class PokegearPokedexFiller(Toggle):
    """Classify Pokedex and Pokegear as filler instead of useful items.
    They behave identically in-game (reveal a Pokemon's type/identity); this only
    lowers their fill priority so they stop crowding the useful-item tier when you
    end up with a large surplus. Master Ball is unaffected.
    Off by default (Pokedex and Pokegear remain 'useful')."""
    display_name = "Pokedex/Pokegear as Filler"
    default = 0


class StopAutosubmitOnGoal(Toggle):
    """Default for the client's 'stop auto-submit after goal' toggle.
    When on, once your goal is reached the client stops auto-submitting remaining
    guesses. This only sets the client's initial preference -- players can still
    override it locally. Off by default (auto-submit keeps running after goal).
    Has no effect on generation or logic."""
    display_name = "Stop Auto-submit After Goal"
    default = 0


@dataclass
class PokepelagoOptions(PerGameCommonOptions):
    dexsanity: Dexsanity
    type_locks: EnableTypeLocks
    region_locks: RegionLocks
    regions: Regions
    random_region_count: RandomRegionCount
    group_hisui_galar: GroupHisuiGalar
    starter_region: StarterRegion
    starter_pokemon: StarterPokemon
    starter_count: StarterCount
    prefer_lab_starters: PreferLabStarters
    starting_location_count: StartingLocationCount
    route_locks_enabled: RouteLocks
    line_locks: LineLocks
    badge_level_gating: BadgeLevelGating
    legendary_locks: LegendaryLocks
    trade_locks: TradeLocks
    baby_locks: BabyLocks
    daycare_count: DaycareCount
    fossil_locks: FossilLocks
    ultra_beast_locks: UltraBeastLocks
    paradox_locks: ParadoxLocks
    stone_locks: StoneLocks
    master_ball_bypass_gates: MasterBallBypassGates
    pokegear_pokedex_filler: PokegearPokedexFiller
    include_shinies: IncludeShinies
    goal_type: GoalType
    goal_percentage: GoalPercentage
    goal_count: GoalCount
    stop_autosubmit_on_goal: StopAutosubmitOnGoal
    trap_chance: TrapChance
    trap_weights: TrapWeights
    filler_weights: FillerWeights
    local_filler_percent: LocalFillerPercent
    # Legacy region toggles (hidden, backward compat only)
    include_kanto: IncludeKanto
    include_johto: IncludeJohto
    include_hoenn: IncludeHoenn
    include_sinnoh: IncludeSinnoh
    include_unova: IncludeUnova
    include_kalos: IncludeKalos
    include_alola: IncludeAlola
    include_galar: IncludeGalar
    include_hisui: IncludeHisui
    include_paldea: IncludePaldea


pokepelago_option_groups: list[OptionGroup] = [
    OptionGroup("Regions", [Regions, RandomRegionCount, GroupHisuiGalar, RegionLocks, StarterRegion, StarterPokemon, StarterCount, PreferLabStarters]),
    OptionGroup("Lock Gates", [EnableTypeLocks, RouteLocks, LineLocks, BadgeLevelGating,
                               LegendaryLocks, TradeLocks, BabyLocks, DaycareCount,
                               FossilLocks, UltraBeastLocks, ParadoxLocks, StoneLocks], start_collapsed=True),
    OptionGroup("Items", [IncludeShinies, MasterBallBypassGates, PokegearPokedexFiller, StopAutosubmitOnGoal, TrapChance, TrapWeights, FillerWeights, LocalFillerPercent], start_collapsed=True),
]
