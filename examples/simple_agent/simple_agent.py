"""Ein einzelner Agent OHNE agentdash-SDK.

Er zeigt, was das Dashboard ganz ohne Codeänderung sieht: Container-Logs und alle
LLM-Aufrufe (inkl. Tool-Aufrufen und -Ergebnissen) über den Ollama-Proxy.
Einzige Voraussetzung: OLLAMA_HOST zeigt auf das Dashboard.
"""

import logging
import os
import random
import time

import ollama

MODEL = os.environ.get("DEMO_MODEL", "llama3.2:3b")
INTERVAL = float(os.environ.get("DEMO_INTERVAL", "60"))
log = logging.getLogger("haus-agent")


def get_temperature(room: str) -> str:
    return f"{room}: {random.uniform(17, 23):.1f} °C"


TOOLS = [{
    "type": "function",
    "function": {
        "name": "get_temperature",
        "description": "Liest die Temperatur eines Raums",
        "parameters": {"type": "object", "properties": {"room": {"type": "string"}}, "required": ["room"]},
    },
}]


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s")
    client = ollama.Client()
    while True:
        room = random.choice(["Wohnzimmer", "Büro", "Keller"])
        messages = [{"role": "user", "content": f"Wie warm ist es im {room}?"}]
        try:
            resp = client.chat(model=MODEL, messages=messages, tools=TOOLS)
            messages.append(resp.message)
            for call in resp.message.tool_calls or []:
                messages.append({"role": "tool", "content": get_temperature(**call.function.arguments),
                                 "tool_name": call.function.name})
            answer = client.chat(model=MODEL, messages=messages).message.content
            log.info("Antwort: %s", answer)
        except Exception as exc:
            log.error("Fehler: %s", exc)
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
