from mcp.server.fastmcp import FastMCP

from .guide import register as register_guide
from .search import register as register_search
from .read import register as register_read
from .write import register as register_write
from .delete import register as register_delete


def register(mcp: FastMCP) -> None:
    register_guide(mcp)
    register_search(mcp)
    register_read(mcp)
    register_write(mcp)
    register_delete(mcp)
