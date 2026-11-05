"""Demo: Eine "Redaktion" aus vier Agenten in einem Container.

planner  -> zerlegt das Thema und beauftragt die anderen
researcher -> nutzt ein Tool (Websuche, simuliert) über Ollama-Tool-Calling
writer   -> schreibt den Text
critic   -> prüft und gibt Feedback; ggf. überarbeitet der writer einmal

Alle LLM-Aufrufe laufen über den Ollama-Proxy des Dashboards (OLLAMA_HOST),
die Struktur (Runs, Agenten, Übergaben) meldet das agentdash-SDK.
"""

from __future__ import annotations

import logging
import os
import random
import time

import ollama

import agentdash
from agentdash import agent, run, send_message, tool

MODEL = os.environ.get("DEMO_MODEL", "llama3.2:3b")
INTERVAL = float(os.environ.get("DEMO_INTERVAL", "45"))
TOPICS = [
    "Neue Entwicklungen bei lokalen Sprachmodellen",
    "Energiesparen im Homelab",
    "Wie funktionieren Multi-Agenten-Systeme?",
    "Smart-Home ohne Cloud",
    "Backups richtig planen",
]

log = logging.getLogger("newsroom")
client = ollama.Client()  # nutzt OLLAMA_HOST


def chat(system: str, prompt: str, **kw) -> ollama.ChatResponse:
    return client.chat(
        model=MODEL,
        messages=[{"role": "system", "content": system}, {"role": "user", "content": prompt}],
        **kw,
    )


@tool
def web_search(query: str) -> str:
    """Simulierte Websuche."""
    time.sleep(0.3)
    hits = [f"{query}: Quelle {i} berichtet über aktuelle Trends." for i in range(1, 4)]
    if random.random() < 0.1:
        raise TimeoutError("Suchdienst antwortet nicht")
    return "\n".join(hits)


SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "Sucht im Web nach aktuellen Informationen",
        "parameters": {"type": "object", "properties": {"query": {"type": "string"}}, "required": ["query"]},
    },
}


@agent("researcher", role="Recherche")
def research(question: str) -> str:
    messages = [
        {"role": "system", "content": "Researcher. Recherchiere mit dem Tool web_search."},
        {"role": "user", "content": question},
    ]
    resp = client.chat(model=MODEL, messages=messages, tools=[SEARCH_TOOL])
    messages.append(resp.message)
    for call in resp.message.tool_calls or []:
        try:
            result = web_search(**call.function.arguments)
        except TimeoutError as exc:
            log.warning("Tool fehlgeschlagen: %s", exc)
            result = f"Fehler: {exc}"
        messages.append({"role": "tool", "content": result, "tool_name": call.function.name})
    final = client.chat(model=MODEL, messages=messages)
    log.info("Recherche abgeschlossen (%d Zeichen)", len(final.message.content))
    return final.message.content


@agent("writer", role="Text")
def write(topic: str, facts: str, feedback: str | None = None) -> str:
    prompt = f"Thema: {topic}\nFakten:\n{facts}"
    if feedback:
        prompt += f"\nFeedback der Kritik: {feedback}"
    return chat("Writer. Schreibe einen kurzen, gut lesbaren Artikel.", prompt).message.content


@agent("critic", role="Qualität")
def review(article: str) -> dict:
    verdict = chat("Critic. Bewerte den Artikel kurz.", article, think=True).message.content
    ok = random.random() > 0.35
    return {"ok": ok, "feedback": verdict}


def produce(topic: str) -> None:
    with run(f"Artikel: {topic}") as r:
        with agent("planner", input=topic, role="Koordination") as planner:
            plan = chat("Planner. Zerlege das Thema in eine Rechercheaufgabe.", topic).message.content
            facts = research(plan)
            article = write(topic, facts)
            result = review(article)
            if not result["ok"]:
                send_message("writer", result["feedback"], kind="feedback", sender="critic")
                article = write(topic, facts, feedback=result["feedback"])
            planner.set_output(article[:500])
        r.set_output(f"{len(article)} Zeichen")
    log.info("Artikel fertig: %s", topic)


def main() -> None:
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    agentdash.init(app=os.environ.get("AGENTDASH_APP"))
    log.info("Redaktion startet (Modell %s, alle %.0f s)", MODEL, INTERVAL)
    while True:
        topic = random.choice(TOPICS)
        try:
            produce(topic)
        except Exception:
            log.exception("Durchlauf fehlgeschlagen")
        agentdash.flush()
        time.sleep(INTERVAL)


if __name__ == "__main__":
    main()
