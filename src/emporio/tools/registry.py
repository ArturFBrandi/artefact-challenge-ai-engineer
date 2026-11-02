"""All tools available to the agent."""

from emporio.tools import catalog, orders, store
from emporio.tools.base import Tool

TOOLS: dict[str, Tool] = {tool.name: tool for tool in (*catalog.TOOLS, *store.TOOLS, *orders.TOOLS)}
