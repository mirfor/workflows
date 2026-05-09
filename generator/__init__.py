"""Generator CNCF SW IR → Python (Temporal Workflow `.py`).

Decyzje #14, #15, #17, #28. Implementacja w `generator/codegen.py` (Python `ast` module).
"""

from generator.codegen import (
    GeneratedWorkflow,
    GeneratorError,
    compute_source_hash,
    generate,
)
from generator.manifest import update_manifest

__all__ = [
    "GeneratedWorkflow",
    "GeneratorError",
    "compute_source_hash",
    "generate",
    "update_manifest",
]
