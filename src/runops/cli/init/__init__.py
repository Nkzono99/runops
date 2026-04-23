"""Project initialization and doctor command facade."""

from __future__ import annotations

import shutil as shutil

from runops.cli.init.bootstrap import _bootstrap_environment as _bootstrap_environment
from runops.cli.init.command import (
    _BundledSiteProfile as _BundledSiteProfile,
)
from runops.cli.init.command import (
    _clone_doc_repos as _clone_doc_repos,
)
from runops.cli.init.command import (
    _prepare_knowledge_imports as _prepare_knowledge_imports,
)
from runops.cli.init.command import (
    _prompt_knowledge_sources as _prompt_knowledge_sources,
)
from runops.cli.init.command import (
    _prompt_launchers as _prompt_launchers,
)
from runops.cli.init.command import (
    _prompt_simulators as _prompt_simulators,
)
from runops.cli.init.command import (
    doctor as doctor,
)
from runops.cli.init.command import (
    init as init,
)

__all__ = [
    "_BundledSiteProfile",
    "_bootstrap_environment",
    "_clone_doc_repos",
    "_prepare_knowledge_imports",
    "_prompt_knowledge_sources",
    "_prompt_launchers",
    "_prompt_simulators",
    "doctor",
    "init",
    "shutil",
]
