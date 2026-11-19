"""Projects that hold related parts, project context for the design agent, and personal design memory.

Naming (kept apart from the code's historic per-part "project"):

- a **part** is what the code and the API call a ``Project`` (one model, one workspace, one design conversation);
- a **design project** (``DesignProject``, user-facing "Project") groups related parts, carries their purpose, notes
  and shared decisions, and gives the agent a compact brief of the sibling parts;
- **design memory** (``MemoryFact``) is one person's learned preferences inside one workspace.

Every table here is new (additive), so an existing database upgrades in place and a part without a row here behaves
exactly as before. ``context.turn_context`` is the single entry point that turns all of this into the text block a
design-agent turn carries.
"""
