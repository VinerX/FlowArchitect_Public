from __future__ import annotations

from typing import Any

from pydantic import BaseModel, ConfigDict, Field


class Position(BaseModel):
    """
    Minimal NiFi position model used for graph layout.
    """

    model_config = ConfigDict(extra="forbid")

    x: float
    y: float


class Processor(BaseModel):
    """
    Minimal NiFi processor representation required to generate a graph.
    `type` is typically a fully qualified NiFi class name, but we keep it as str.
    """

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    id: str | None = None
    name: str
    processor_type: str = Field(alias="type")
    position: Position
    properties: dict[str, Any] = Field(default_factory=dict)


class Connection(BaseModel):
    """
    Minimal NiFi connection representation between two components.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str | None = None
    source_id: str
    destination_id: str
    selected_relationships: list[str] = Field(default_factory=list)


class ProcessGroup(BaseModel):
    """
    Minimal NiFi process group representation containing processors and connections.
    """

    model_config = ConfigDict(extra="forbid")

    id: str | None = None
    name: str
    position: Position = Field(default_factory=lambda: Position(x=0.0, y=0.0))
    processors: list[Processor] = Field(default_factory=list)
    connections: list[Connection] = Field(default_factory=list)
