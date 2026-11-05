"""agentdash – meldet Agenten, Runs, Tools und Nachrichten an das Agent-Dashboard.

Beispiel::

    import agentdash
    from agentdash import run, agent, tool, send_message

    agentdash.init()  # Endpoint aus $AGENTDASH_ENDPOINT (Standard http://agentdash:4318)

    @tool
    def suche(query: str) -> str: ...

    with run("Tagesbericht"):
        with agent("researcher"):
            fakten = suche("KI News")
        with agent("writer", input=fakten) as w:
            w.set_output("Bericht …")
"""

from ._core import agent, current_agent, flush, init, run, send_message, shutdown, step, tool, trace_headers
from ._instrument import instrument_httpx

__all__ = [
    "agent",
    "current_agent",
    "flush",
    "init",
    "instrument_httpx",
    "run",
    "send_message",
    "shutdown",
    "step",
    "tool",
    "trace_headers",
]
__version__ = "0.1.0"
