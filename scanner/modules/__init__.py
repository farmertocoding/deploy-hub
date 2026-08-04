"""Scanner modules (§S1/§V6 pinned home). Importing this package registers all
modules with scanner.core in precedence order: framework modules, then fallbacks."""
from . import django as django_module  # noqa: F401
from . import node_ts  # noqa: F401
from . import fallbacks  # noqa: F401
