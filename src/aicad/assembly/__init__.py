"""Assembly Studio: multi-part assemblies of verified project parts and Toolbox components.

Pure-Python pieces (safe to import in the web process): ``xform`` (rigid transforms), ``solver`` (mate solver and
DOF analysis), ``fasteners`` (ISO fastener stack selection), ``store`` (assembly documents), ``service``
(orchestration), ``bom``, ``explode``. Kernel work (part preparation, interference, clearance, grip probing, STEP
export) runs only in the assembly worker process (``geometry`` + ``worker``).
"""


class AssemblyInputError(ValueError):
    """A problem the user can fix (shown as-is)."""
