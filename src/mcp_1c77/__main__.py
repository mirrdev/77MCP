"""Entry point for running the server as ``python -m mcp_1c77``."""

import os
import sys
from pathlib import Path
import uvicorn


def main() -> None:
    """Run the local web and MCP server."""
    if "--stdio" in sys.argv[1:]:
        from . import tools
        from .server import mcp
        from .web import DATA_DIR, MD_FILENAME
        tools.set_data_dir(DATA_DIR)
        md_path = Path(os.environ.get("MCP_MD_PATH") or Path(DATA_DIR) / MD_FILENAME)
        if md_path.is_file():
            tools.init(str(md_path))
        mcp.run()
        return
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8099"))
    uvicorn.run("mcp_1c77.web:app", host=host, port=port)


if __name__ == "__main__":
    main()
