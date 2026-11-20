# Hybrid master model (WORKLIST 50, branch `wip/master-model`)

Founder question (2026-11-20): why does the same prompt succeed in the Design Studio and fail in the Design Office?
The Studio has one agent, one script and one coordinate system, so every body is placed consistently by
construction. The Office chains plan, layout, interfaces, separately designed parts, matching and reassembly, and each
hand-off can lose information. The design graph and the connection-layout solver close that gap for structures the
graph knows (10 of 10 golden cases). This branch closes it for the rest, and only when needed: the founder approved a
"hybrid master model, used only when needed", with the golden suite deciding the default.

**In one paragraph.** At plan time a deterministic rule decides the layout path and records it on the program. The
fast path (design graph, connection solver or standard layout, spec builds) stays the default. When the rule says the
fast path can't lay the program out (a free-form product, a custom adapter, a structure the solver can't place, a
layout conflict, a part nothing reaches, a fast layout that fails a gate check), Archie spends one design-agent turn on
the Opus tier modelling a coarse multibody master of the whole product in one coordinate system. Code then measures
the master (frames, envelopes, contacts, hole patterns, pivot axes, fits, pockets) and writes the office's own
skeleton and ICD from it, so the ICD gate, direct builds, Gage, Fitz, revision and the supervisor run unchanged, and
Fitz places each detailed part where its master body sat. Measurement findings are never silent: they are errors or
warnings at the gate.

RESULTS_PLACEHOLDER
