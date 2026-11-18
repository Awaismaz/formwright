# EVAL-008: same-prompt repeatability harness

`aicad repeat` (`src/aicad/eval/repeat.py`) runs one prompt N times (default 5), each in an empty workspace with a
fresh agent conversation, and reports how much the resulting geometry varies. Judged only on the deterministic build
outputs (status.json, topology), never on the agent's words.

## Modes

| Mode | Model calls | Use |
|---|---|---|
| `--fake` (default) | none | synthetic replays of the benchmark case's reference solution: proves the harness (every run must be identical) |
| `--replay PATH` | none | a folder of cassettes (run i uses file i, cycling) or one cassette for every run; re-score recorded live runs offline |
| `--live [--record DIR] [--yes]` | **yes** | the real agent; prints a token estimate and refuses without confirmation (PD-41: not run in this batch) |

```
uv run aicad repeat --case P01                                       # fake, 5 runs
uv run aicad repeat --case B02 --live --runs 5 --record rep-cas --yes  # spends tokens
uv run aicad repeat --case B02 --replay rep-cas --out rep-out         # offline re-score
uv run aicad repeat --prompt "..." --replay one-cassette.json
```

## Report (`report.json`, `report.md`)

Summary: verdict (`repeatable` / `varies: N distinct results; differs in …` / `nothing built`), built rate, gate pass
rate, per-check pass rate (CHK-02…08), share of runs identical to the most common result, number of distinct
geometries, and the case-expectation pass rate when a benchmark case is used.

Per metric (volume, bbox x/y/z, faces, edges, solids, features, builds, time, tokens): n, mean, sample standard
deviation, min, max, spread, coefficient of variation, distinct values. "Identical geometry" means equal volume and
bbox within 1e-6 relative, equal topology counts and equal cylinder census.

Per run: built, gates, volume, size, faces, features, builds, time; plus checks, census, tokens and errors in JSON.

## Tests (`tests/test_repeat.py`, fakes and replays only)

- fake ×5 of P01: verdict repeatable, stdev 0, every check 100 %, expectation 100 %;
- replayed ×5 with thicknesses 6, 6, 8, 6 and one broken script: built 80 %, 2 distinct geometries, 60 % modal, volume
  stdev exactly 4000 mm³ (hand computed), bbox z varies and bbox x does not;
- `--live` refuses without confirmation; argument errors; CLI dispatch.

Limitation: a measured variance of the real agent needs live runs (token spend, PD-41) — the harness is ready.
