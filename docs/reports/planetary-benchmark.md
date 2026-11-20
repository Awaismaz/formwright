# Benchmark: "Build a single stage planetary Gearbox"

Founder's standing benchmark (2026-11-20): run the brief through the Design Office on his account until the result is
right, fixing the software between attempts. Every attempt is a program in his Design Office named
"Planetary benchmark A<n>", so the history is visible there.

**What "right" means** (checked on the assembly, by eye and by the numbers): a sun gear on the input shaft; N planet
gears on bearings on pins pressed into a carrier; an internal ring gear fixed in the housing; the carrier on the output
shaft; z_ring = z_sun + 2 z_planet; (z_sun + z_ring) / N whole; planets equally spaced at a = m (z_sun + z_planet) / 2;
all gears in one plane; a planet rim of at least about 2.5 m over its bearing; ratio 1 + z_ring / z_sun; every shaft on
two bearings in the housing; 0 clashes; nothing floating or left in the parts bin.

## Attempts

| # | When | Result | What went wrong | Fixed by |
|---|---|---|---|---|
| (sim) | 2026-11-21 | Golden case `k_planetary` added. After the orchestration fixes: 0 clashes (was 10), 1 ticket stop (was 73), conformance 84 of 85, rim rule passes (6004 bearing, 6.5 mm = 3.25 m rim) | Only the ring gear left (internal-gear generator pending) | wip/planetary-orchestration |
| A1 | 2026-11-21 | Plan and layout right (sun z30, 3 planets z30, ring z90 internal, m2, a 60, ratio 4:1); build blocked | (1) No internal-gear generator, so the ring went to the AI designer, and the recognizer could not see internal teeth, so Gage sent a correct ring back every round. (2) The ring's placeholder was a solid disc, so the correctly built input shaft and planet pins were blocked for "clashing" with empty space. (3) Planet gears went to the AI designer (no bearing-seat bore in the gear generator). (4) 6204 planet bearing leaves a 4 mm rim in a z30 m2 planet | wip/planetary-geometry (internal gears: generator, recognition, conformance; planet bearing seats) and wip/planetary-orchestration (faithful placeholders, placeholder clashes never block a built part, rim rule in the planetary sizing, golden case) |
