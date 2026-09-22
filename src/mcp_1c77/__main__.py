"""Entry point for running the server as ``python -m mcp_1c77``."""

import os
import uvicorn


def main() -> None:
    """Run the local web and MCP server."""
    host = os.environ.get("MCP_HOST", "127.0.0.1")
    port = int(os.environ.get("MCP_PORT", "8099"))
    uvicorn.run("mcp_1c77.web:app", host=host, port=port)


if __name__ == "__main__":
    main()
