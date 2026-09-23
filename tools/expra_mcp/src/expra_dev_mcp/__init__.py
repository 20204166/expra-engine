"""expra-mcp: local development/debugging MCP server for expra-engine.

Development tooling only. Never imported by src/expra_engine or by exported
Expra games -- see tools/expra_mcp/README.md.
"""

from . import _version

__version__ = _version.__version__
