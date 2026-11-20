"""The hybrid master model (WORKLIST 50): lay a Design Office program out from one coarse multibody model.

Founder question (2026-11-20): why does the same prompt succeed in the Design Studio and fail in the Design Office? The
Studio has one agent, one script and one coordinate system: every body is placed consistently by construction. The
Office chains plan, layout, interfaces, separately designed parts, matching and reassembly, and each hand-off can lose
information. The design graph and the connection-layout solver close that gap for structures the graph knows; this
package closes it for the rest, and only when needed:

* ``decide``    the deterministic rule: the fast path (graph + solver + spec builds) or the master path, recorded on
                the program with the reason in plain words.
* ``prompt``    the master turn's dedicated instructions (one design-agent turn, Opus tier).
* ``kit``       the helpers a master script uses to name its bodies (one per planned part, copies separate).
* ``measure``   the deterministic measurement of the master B-rep: each body's frame and envelope, planar contacts,
                coaxial fits, holes across a contact, overlaps, bodies that touch nothing.
* ``skeleton``  the measurement turned into the office's own skeleton and ICD format (``office.icd.build``'s), plus a
                design graph of what was measured, so the ICD gate, direct builds, Gage, Fitz, revision and the
                supervisor run unchanged. Fitz places each detailed part where its master body sat.
* ``run``       the master step of the planning phase (agent turn or a recorded script, build, measure, attach).

Geometry acceptance stays deterministic; nothing here claims manufacturing validity.
"""
