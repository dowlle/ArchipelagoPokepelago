# Pokepelago fuzz hooks

Developer-only fuzz hooks for the [Eijebong Archipelago fuzzer](https://github.com/Eijebong/Archipelago-fuzzer).
Excluded from the built `.apworld` by `.apignore` (`tools/`). Never imported at
runtime.

## `client_item_decode.py` — DEVEX-16 Phase 2

A pure-Python cross-check that replays every generated Pokepelago multiworld
through a faithful port of the **client's** item decoders
(`PokepelagoClient/src/data/itemDecoding.ts` + `routeData.ts` + `useOffsets.ts`)
and asserts that each placed Route Key / Line Unlock / Region Pass / Type Key /
gate item decodes back to the item's real `name`.

It is the seed-driven counterpart to DEVEX-16 Phase 1 (the client Vitest suite):
Phase 1 fires synthetic IDs at the decoders; this fires **real generated seeds**
across the whole random option space, so an APWorld-side ID-layout change fails a
fuzz check instead of a player's game. It targets the exact BUG-12 failure mode
(the client re-deriving the route-key ordering independently and drifting from
the APWorld's `sorted(ROUTE_GROUPS) + sorted(ungrouped ROUTE_DATA)` layout).

No Node, no headless client — it runs inside `fuzz.py` at the same per-seed cost
as the other hooks.

### Run locally

Copy the hook into the fuzzer's `hooks/` package (next to `fuzz.py`), then add a
`run_check` row to `run-fuzz.sh` alongside the other checks:

```sh
cp worlds/pokepelago/tools/fuzz/client_item_decode.py "$AP_DIR/hooks/client_item_decode.py"
# in run-fuzz.sh, next to the other run_check rows:
run_check "check-client-item-decode" 500 --hook hooks.client_item_decode:Hook
```

Or invoke it directly:

```sh
python fuzz.py -j 8 -g pokepelago -r 500 -n 1 -t 60 --hook hooks.client_item_decode:Hook
```

Set `POKEPELAGO_DECODE_STATS=/path/to/stats.txt` to append per-seed decode
coverage counts (`checked route line region type gate`) for evidence gathering;
unset in normal runs.

### CI

`.github/workflows/pokepelago-fuzz.yml` copies this file into `archipelago/hooks/`
and passes `--hook hooks.client_item_decode:Hook`, so every push/PR touching
`worlds/pokepelago/**` runs the decode cross-check over 500 seeds.

### Validation (2026-07-10)

- 2,400 seeds against `main` (`aa3bb80a`): **0 failures, 0 timeouts**; 265,570
  decodable items checked in one 1,200-seed batch (26,941 route keys over 589
  seeds, 191,755 line unlocks, 11,472 type keys, 32,563 gate items, 2,839 region
  passes).
- Negative control: swapping the two-phase route ordering for a flat sort
  (the BUG-12 defect) failed 9/15 seeds and reproduced the exact BUG-12
  signature (`id=8581046 real='Sinnoh Mid Routes Key' client_decoded='Roaming
  Kalos Area Key'`, IDs 8581044–8581059 = indexes 44–59). The hook has teeth.
