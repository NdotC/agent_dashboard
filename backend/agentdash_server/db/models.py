"""Datenmodell. Zeitstempel sind Unix-Sekunden (float), IDs aus OTel als Hex-Strings."""

from __future__ import annotations

from sqlalchemy import JSON, Float, ForeignKey, Index, Integer, String, Text, UniqueConstraint
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column


class Base(DeclarativeBase):
    pass


class Application(Base):
    """Eine Anwendung = ein Docker-Container (oder eine andere Quelle, z. B. ein Host)."""

    __tablename__ = "applications"

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    key: Mapped[str] = mapped_column(String(200), unique=True)
    name: Mapped[str] = mapped_column(String(200))
    source: Mapped[str] = mapped_column(String(20), default="docker")  # docker | otlp | proxy
    container_id: Mapped[str | None] = mapped_column(String(80))
    container_name: Mapped[str | None] = mapped_column(String(200))
    image: Mapped[str | None] = mapped_column(String(300))
    status: Mapped[str] = mapped_column(String(20), default="unknown")
    started_at: Mapped[float | None] = mapped_column(Float)
    exit_code: Mapped[int | None] = mapped_column(Integer)
    restart_count: Mapped[int] = mapped_column(Integer, default=0)
    labels: Mapped[dict | None] = mapped_column(JSON)
    first_seen: Mapped[float] = mapped_column(Float)
    last_seen: Mapped[float] = mapped_column(Float)
    last_log_ts: Mapped[float | None] = mapped_column(Float)


class Agent(Base):
    __tablename__ = "agents"
    __table_args__ = (UniqueConstraint("app_id", "name"),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    name: Mapped[str] = mapped_column(String(200))
    display_name: Mapped[str | None] = mapped_column(String(200))
    color: Mapped[str | None] = mapped_column(String(20))
    role: Mapped[str | None] = mapped_column(String(200))
    model: Mapped[str | None] = mapped_column(String(200))
    first_seen: Mapped[float] = mapped_column(Float)
    last_seen: Mapped[float] = mapped_column(Float)


class Run(Base):
    """Ein Durchlauf = ein OTel-Trace, oder eine automatisch erkannte LLM-Konversation."""

    __tablename__ = "runs"
    __table_args__ = (
        Index("ix_runs_app_started", "app_id", "started_at"),
        Index("ix_runs_started", "started_at"),
    )

    id: Mapped[str] = mapped_column(String(64), primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    title: Mapped[str | None] = mapped_column(Text)
    source: Mapped[str] = mapped_column(String(20), default="sdk")  # sdk | auto
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | ok | error
    started_at: Mapped[float] = mapped_column(Float)
    ended_at: Mapped[float | None] = mapped_column(Float)
    last_activity: Mapped[float] = mapped_column(Float)
    tokens_in: Mapped[int] = mapped_column(Integer, default=0)
    tokens_out: Mapped[int] = mapped_column(Integer, default=0)
    llm_calls: Mapped[int] = mapped_column(Integer, default=0)
    errors: Mapped[int] = mapped_column(Integer, default=0)


class Span(Base):
    __tablename__ = "spans"
    __table_args__ = (Index("ix_spans_run", "run_id", "started_at"), Index("ix_spans_agent", "agent_id"))

    id: Mapped[str] = mapped_column(String(32), primary_key=True)
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    parent_id: Mapped[str | None] = mapped_column(String(32))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20))  # run | agent | tool | step | llm
    name: Mapped[str] = mapped_column(Text)
    started_at: Mapped[float] = mapped_column(Float)
    ended_at: Mapped[float | None] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="running")  # running | ok | error
    status_message: Mapped[str | None] = mapped_column(Text)
    input: Mapped[str | None] = mapped_column(Text)
    output: Mapped[str | None] = mapped_column(Text)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    attributes: Mapped[dict | None] = mapped_column(JSON)


class Message(Base):
    """Nachricht zwischen Agenten. ``from_agent_id``/``to_agent_id`` NULL = Start/Benutzer."""

    __tablename__ = "messages"
    __table_args__ = (Index("ix_messages_run", "run_id", "ts"), Index("ix_messages_app", "app_id", "ts"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    run_id: Mapped[str] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    span_id: Mapped[str | None] = mapped_column(String(32))
    from_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    to_agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    kind: Mapped[str] = mapped_column(String(20))  # call | return | handoff | request | response | broadcast
    content: Mapped[str | None] = mapped_column(Text)
    ts: Mapped[float] = mapped_column(Float)


class LlmCall(Base):
    __tablename__ = "llm_calls"
    __table_args__ = (
        Index("ix_llm_app", "app_id", "started_at"),
        Index("ix_llm_agent", "agent_id", "started_at"),
        Index("ix_llm_run", "run_id", "started_at"),
        Index("ix_llm_started", "started_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    span_id: Mapped[str | None] = mapped_column(String(32))
    parent_span_id: Mapped[str | None] = mapped_column(String(32))
    parent_call_id: Mapped[int | None] = mapped_column(Integer)
    endpoint: Mapped[str] = mapped_column(String(60))
    model: Mapped[str | None] = mapped_column(String(200))
    request: Mapped[dict | None] = mapped_column(JSON)
    response: Mapped[str | None] = mapped_column(Text)
    thinking: Mapped[str | None] = mapped_column(Text)
    tool_calls: Mapped[list | None] = mapped_column(JSON)
    tokens_in: Mapped[int | None] = mapped_column(Integer)
    tokens_out: Mapped[int | None] = mapped_column(Integer)
    duration_ms: Mapped[float | None] = mapped_column(Float)
    started_at: Mapped[float] = mapped_column(Float)
    status: Mapped[str] = mapped_column(String(20), default="ok")
    error: Mapped[str | None] = mapped_column(Text)
    client_ip: Mapped[str | None] = mapped_column(String(64))


class ToolInvocation(Base):
    """Tool-Aufruf: Entscheidung des Modells (aus dem Proxy) oder Ausführung (aus dem SDK)."""

    __tablename__ = "tool_invocations"
    __table_args__ = (Index("ix_tools_run", "run_id", "ts"), Index("ix_tools_app", "app_id", "ts"))

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    app_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    run_id: Mapped[str | None] = mapped_column(ForeignKey("runs.id", ondelete="CASCADE"))
    llm_call_id: Mapped[int | None] = mapped_column(Integer)
    result_llm_call_id: Mapped[int | None] = mapped_column(Integer)
    call_ref: Mapped[str | None] = mapped_column(String(100))
    name: Mapped[str] = mapped_column(String(200))
    arguments: Mapped[dict | list | str | None] = mapped_column(JSON)
    result: Mapped[str | None] = mapped_column(Text)
    ts: Mapped[float] = mapped_column(Float)
    result_ts: Mapped[float | None] = mapped_column(Float)


class LogEntry(Base):
    __tablename__ = "logs"
    __table_args__ = (
        Index("ix_logs_app_ts", "app_id", "ts"),
        Index("ix_logs_agent_ts", "agent_id", "ts"),
        Index("ix_logs_run_ts", "run_id", "ts"),
        Index("ix_logs_ts", "ts"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    ts: Mapped[float] = mapped_column(Float)
    app_id: Mapped[int] = mapped_column(ForeignKey("applications.id", ondelete="CASCADE"))
    agent_id: Mapped[int | None] = mapped_column(ForeignKey("agents.id", ondelete="SET NULL"))
    run_id: Mapped[str | None] = mapped_column(String(64))
    span_id: Mapped[str | None] = mapped_column(String(32))
    level: Mapped[str] = mapped_column(String(10), default="info")  # debug | info | warn | error
    source: Mapped[str] = mapped_column(String(10))  # docker | sdk | proxy
    stream: Mapped[str | None] = mapped_column(String(10))
    message: Mapped[str] = mapped_column(Text)
    attributes: Mapped[dict | None] = mapped_column(JSON)


class Setting(Base):
    __tablename__ = "settings"

    key: Mapped[str] = mapped_column(String(100), primary_key=True)
    value: Mapped[dict | list | str | int | float | bool | None] = mapped_column(JSON)
