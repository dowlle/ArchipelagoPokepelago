"""
DEVEX-16 Phase 2 — client item-decode fuzzer hook.

A pure-Python cross-check that replays every generated Pokepelago multiworld
through a faithful port of the CLIENT'S item decoders and asserts that each
placed Route Key / Line Unlock / Region Pass / Type Key / gate item decodes
back to the item's real ``name``. No Node, no headless client spin-up — it runs
inside the existing Eijebong fuzz.py harness at the same per-seed cost as the
other hooks.

Why this exists (BUG-12): the APWorld (``worlds/pokepelago/Items.py``) and the
client (``src/data/itemDecoding.ts`` + ``src/data/routeData.ts`` +
``src/hooks/useOffsets.ts``) each independently turn an Archipelago item ID into
a display name. When those two derivations drift, seeds generate cleanly but the
client silently decodes items as the wrong thing (BUG-12: 16 of 80 route keys
landed on the wrong name, making multi-slot seeds look hard-locked). Phase 1
(client Vitest) locks this down against synthetic IDs; Phase 2 (this hook) locks
it down against REAL generated seeds across the whole random option space, so a
future APWorld-side change to the ID layout fails a fuzz check instead of a
player's game.

What is genuinely independent here (i.e. what this actually catches):
  * Route Keys   — the client re-derives the ID ordering with its OWN two-phase
                   heuristic (non-``roaming-``/``virtual-`` slugs sorted first,
                   then the ``roaming-``/``virtual-`` ones), ported verbatim
                   below. If that ordering ever disagrees with the APWorld's real
                   ``sorted(ROUTE_GROUPS) + sorted(ungrouped ROUTE_DATA)`` layout,
                   the decoded name won't equal the placed item's name. This is
                   the exact BUG-12 failure mode.
  * Type Keys /  — the client hard-codes the ordered name lists (TYPE_NAMES_ORDERED,
    Region Pass    REGION_NAMES_ORDERED) and the gate ID map. Ported verbatim, so
    / Gate items   any reorder / rename / offset change on the APWorld side is caught.
  * Every category also validates the client's hard-coded offsets
    (``useOffsets.ts`` NEW_OFFSETS) against the APWorld's real IDs, so an offset
    change on either side is caught too.

The client's slug->name and base_id->name maps are read from route_data.json,
which is EXPORTED from the APWorld, so those maps are sourced here from the
world under test (they can't drift by construction); the drift-prone logic
(ordering, offsets, hard-coded lists) is the client port below.

Note on DEVEX-15: once DEVEX-15 lands, the client resolves route keys / line
unlocks via explicit exported ID maps (a fast path that cannot drift because it
is exported). The offset/ordering decoder ported here remains the permanent
backward-compat fallback for pre-DEVEX-15 seed bundles, and is the BUG-12 path,
so fuzzing it stays meaningful regardless of DEVEX-15 merge state.

Usage (mirrors the other run_fuzz.sh rows):
    fuzz.py -g pokepelago -r 500 -n 1 -t 60 --hook hooks.client_item_decode:Hook

Deploy: copy this file to the fuzzer's ``hooks/`` package (next to fuzz.py) as
``client_item_decode.py`` before invoking. In CI it is copied into
``archipelago/hooks/`` by the pokepelago-fuzz workflow.
"""

import importlib
import os

from fuzz import BaseHook, GenOutcome

# Optional coverage instrumentation: when POKEPELAGO_DECODE_STATS points at a
# file, every generation appends one line ``checked route line region type gate``
# so a run's real per-category decode coverage can be tallied afterwards. Purely
# for evidence gathering; unset in normal/CI runs so behaviour is unchanged.
_STATS_PATH = os.environ.get("POKEPELAGO_DECODE_STATS")

# ── Client constants, ported verbatim from the client repo ──────────────────
# src/hooks/useOffsets.ts  (NEW_OFFSETS — the scheme every v0.6+ APWorld uses)
CLIENT_ITEM_OFFSET = 8574000
TYPE_ITEM_OFFSET = 2000
REGION_PASS_OFFSET = 5000
GATE_ITEM_OFFSET = 6000
ROUTE_KEY_OFFSET = 7000
LINE_UNLOCK_OFFSET = 9000

# src/data/itemDecoding.ts — TYPE_NAMES_ORDERED / REGION_NAMES_ORDERED
CLIENT_TYPE_NAMES_ORDERED = [
    "Normal", "Fire", "Water", "Grass", "Electric", "Ice", "Fighting",
    "Poison", "Ground", "Flying", "Psychic", "Bug", "Rock", "Ghost",
    "Dragon", "Fairy", "Steel", "Dark",
]
CLIENT_REGION_NAMES_ORDERED = [
    "Kanto", "Johto", "Hoenn", "Sinnoh", "Unova",
    "Kalos", "Alola", "Galar", "Hisui", "Paldea",
]

# src/context/GameContext.tsx gate checks + src/data/pokemon_gates.ts
# STONE_NAMES_ORDERED. The client keys stones internally ('fire', ...) at
# GATE_ITEM_OFFSET + 6010 + i; the display/item name is "<Stone> Stone".
_CLIENT_STONE_DISPLAY_ORDERED = [
    "Fire Stone", "Water Stone", "Thunder Stone", "Leaf Stone", "Moon Stone",
    "Sun Stone", "Shiny Stone", "Dusk Stone", "Dawn Stone", "Ice Stone",
]
# gate offset (relative to CLIENT_ITEM_OFFSET) -> expected item name.
CLIENT_GATE_NAMES = {
    6000: "Gym Badge",
    6001: "Link Cable",
    6002: "Daycare",
    6003: "Ultra Wormhole",
    6004: "Time Rift",
    6005: "Fossil Restorer",
    6020: "Shiny Charm",
}
for _i, _stone in enumerate(_CLIENT_STONE_DISPLAY_ORDERED):
    CLIENT_GATE_NAMES[6010 + _i] = _stone

# src/data/routeData.ts — UNGROUPED_ROUTE_KEY_PREFIXES
UNGROUPED_ROUTE_KEY_PREFIXES = ("roaming-", "virtual-")


class ClientItemDecodeMismatch(Exception):
    """A placed item decodes to the wrong name under the client's algorithm.

    Single-string arg so it pickles cleanly across the fuzzer's worker->main
    result callback (same reason as item_location_count's exception)."""

    def __init__(self, message):
        super().__init__(message)


def _is_ungrouped_route_key(slug):
    return any(slug.startswith(p) for p in UNGROUPED_ROUTE_KEY_PREFIXES)


class _ClientDecoder:
    """Faithful port of the client's ID->name decoders for one Pokepelago world.

    Route-key slug->name and line base_id->name maps come from the world's own
    Items module (== the exported route_data.json the client bundles); the
    ordering / offsets / hard-coded lists are the independent client logic.
    """

    def __init__(self, items_module):
        route_key_names = items_module.ROUTE_KEY_NAMES      # slug -> "<display> Key"
        line_unlock_names = items_module.LINE_UNLOCK_NAMES  # base_id(int) -> "<mon> Line"

        # Client's two-phase route-key ordering (routeData.ts ROUTE_KEY_ORDER):
        # non-ungrouped slugs sorted, then ungrouped (roaming-/virtual-) slugs sorted.
        slugs = list(route_key_names.keys())
        grouped = sorted(s for s in slugs if not _is_ungrouped_route_key(s))
        ungrouped = sorted(s for s in slugs if _is_ungrouped_route_key(s))
        client_order = grouped + ungrouped

        # Client route-key ID (ITEM_OFFSET + ROUTE_KEY_OFFSET + index) -> name.
        self.route_id_to_name = {}
        for idx, slug in enumerate(client_order):
            cid = CLIENT_ITEM_OFFSET + ROUTE_KEY_OFFSET + idx
            self.route_id_to_name[cid] = route_key_names[slug]
        self._route_count = len(client_order)

        # Line unlocks: base Pokemon ID encoded directly as the offset.
        self.line_base_to_name = dict(line_unlock_names)

    def category(self, item_id):
        """Return the client decoder category for an item ID, or None if the ID
        is outside every decoder's range (e.g. Pokemon Unlock / useful / trap /
        filler — handled by other client paths, out of scope for this hook)."""
        off = item_id - CLIENT_ITEM_OFFSET
        if TYPE_ITEM_OFFSET <= off < TYPE_ITEM_OFFSET + len(CLIENT_TYPE_NAMES_ORDERED):
            return "type"
        if REGION_PASS_OFFSET <= off < REGION_PASS_OFFSET + len(CLIENT_REGION_NAMES_ORDERED):
            return "region"
        if GATE_ITEM_OFFSET <= off < GATE_ITEM_OFFSET + 100:
            return "gate"
        if ROUTE_KEY_OFFSET <= off < ROUTE_KEY_OFFSET + self._route_count:
            return "route"
        if LINE_UNLOCK_OFFSET < off <= LINE_UNLOCK_OFFSET + 1025:
            return "line"
        return None

    def decode(self, category, item_id):
        """Return the display name the client would render for item_id, or None
        if the client's decoder for that category cannot resolve it."""
        off = item_id - CLIENT_ITEM_OFFSET
        if category == "type":
            return CLIENT_TYPE_NAMES_ORDERED[off - TYPE_ITEM_OFFSET] + " Type Key"
        if category == "region":
            return CLIENT_REGION_NAMES_ORDERED[off - REGION_PASS_OFFSET] + " Pass"
        if category == "gate":
            return CLIENT_GATE_NAMES.get(off)  # None => client has no mapping for it
        if category == "route":
            return self.route_id_to_name.get(item_id)
        if category == "line":
            return self.line_base_to_name.get(off - LINE_UNLOCK_OFFSET)
        return None


class Hook(BaseHook):
    def setup_worker(self, args):
        super().setup_worker(args)
        # Per-worker instance reused across seeds; reset state every generation.
        self._decode_error = None
        self._decoder = None
        self._decoder_pkg = None

    def _get_decoder(self, mw):
        """Build (and cache per worker) the client decoder from the Pokepelago
        world's own Items module. Returns None if no Pokepelago world present."""
        for player, world in mw.worlds.items():
            if player == 0:
                continue
            if getattr(world, "game", None) != "Pokepelago":
                continue
            pkg = getattr(__import__(type(world).__module__, fromlist=["__package__"]),
                          "__package__", None) or type(world).__module__
            if self._decoder is not None and self._decoder_pkg == pkg:
                return self._decoder
            items_module = importlib.import_module(pkg + ".Items")
            self._decoder = _ClientDecoder(items_module)
            self._decoder_pkg = pkg
            return self._decoder
        return None

    @staticmethod
    def _pokepelago_players(mw):
        return {p for p, w in mw.worlds.items()
                if p != 0 and getattr(w, "game", None) == "Pokepelago"}

    def _iter_pokepelago_items(self, mw, players):
        """All distinct real (id-bearing) items belonging to Pokepelago players,
        wherever they ended up (itempool, placed at a location, precollected)."""
        seen = set()
        sources = [mw.itempool]
        sources.append([loc.item for loc in mw.get_filled_locations() if loc.item is not None])
        for pre in mw.precollected_items.values():
            sources.append(pre)
        for src in sources:
            for item in src:
                if item.player not in players:
                    continue
                if item.code is None:  # event item, no wire ID
                    continue
                key = id(item)
                if key in seen:
                    continue
                seen.add(key)
                yield item

    def after_generate(self, mw, output_path):
        # Reset per generation — the instance is shared across seeds in a worker.
        self._decode_error = None
        if mw is None:
            return
        try:
            players = self._pokepelago_players(mw)
            if not players:
                return
            decoder = self._get_decoder(mw)
            if decoder is None:
                return

            checked = 0
            per_cat = {}
            mismatches = []
            for item in self._iter_pokepelago_items(mw, players):
                cat = decoder.category(item.code)
                if cat is None:
                    continue
                checked += 1
                per_cat[cat] = per_cat.get(cat, 0) + 1
                decoded = decoder.decode(cat, item.code)
                if decoded != item.name:
                    mismatches.append(
                        f"[{cat}] id={item.code} real={item.name!r} "
                        f"client_decoded={decoded!r}"
                    )

            if _STATS_PATH:
                # Line-sized append; atomic enough across worker processes on Linux.
                cats = " ".join(str(per_cat.get(c, 0))
                                for c in ("route", "line", "region", "type", "gate"))
                with open(_STATS_PATH, "a", encoding="utf-8") as fd:
                    fd.write(f"{checked} {cats}\n")

            if mismatches:
                cat_summary = ", ".join(f"{k}:{v}" for k, v in sorted(per_cat.items()))
                head = mismatches[:20]
                more = "" if len(mismatches) <= 20 else f" (+{len(mismatches) - 20} more)"
                self._decode_error = ClientItemDecodeMismatch(
                    f"{len(mismatches)} client-decode mismatch(es) of {checked} "
                    f"decodable items [{cat_summary}]:\n  " + "\n  ".join(head) + more
                )
        except Exception as e:  # a bug in the hook itself must be visible, not silent
            self._decode_error = ClientItemDecodeMismatch(f"hook internal error: {e!r}")

    def reclassify_outcome(self, outcome, raised):
        # Only override a genuinely successful generation; never mask a real
        # generation Failure/Timeout/OptionError.
        if self._decode_error is not None and outcome == GenOutcome.Success:
            return GenOutcome.Failure, self._decode_error
        return outcome, raised
