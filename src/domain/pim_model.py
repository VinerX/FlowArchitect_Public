from __future__ import annotations

from typing import Any, Literal

from pydantic import AliasChoices, BaseModel, ConfigDict, Field


class DataFlow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str
    description: str | None = None


class ConnectionConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    properties: dict[str, Any] = Field(default_factory=dict)


class Trigger(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    type: Literal["schedule", "event", "manual"]
    condition: str


class ProcessedData(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    format: str


class DataComponent(BaseModel):
    model_config = ConfigDict(extra="forbid")

    id: str
    name: str


class DataSource(DataComponent):
    model_config = ConfigDict(extra="forbid")

    type: str
    location: str
    connection: ConnectionConfig | None = None


class DataProcessingElement(DataComponent):
    model_config = ConfigDict(extra="forbid")

    operation: str
    config: dict[str, Any] = Field(default_factory=dict)


class DataSink(DataComponent):
    model_config = ConfigDict(extra="forbid")

    type: str
    location: str
    connection: ConnectionConfig | None = None


class Link(BaseModel):
    model_config = ConfigDict(extra="forbid")

    from_id: str = Field(validation_alias=AliasChoices("from_id", "from"))
    to_id: str = Field(validation_alias=AliasChoices("to_id", "to"))
    data_ref: str | None = None

    @property
    def from_step(self) -> str:
        return self.from_id

    @property
    def to_step(self) -> str:
        return self.to_id


Step = DataSource | DataProcessingElement | DataSink


class PIMFlow(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flow: DataFlow
    triggers: list[Trigger] = Field(default_factory=list)
    sources: list[DataSource] = Field(default_factory=list)
    processing_elements: list[DataProcessingElement] = Field(default_factory=list)
    sinks: list[DataSink] = Field(default_factory=list)
    processed_data: list[ProcessedData] = Field(default_factory=list)
    links: list[Link] = Field(default_factory=list)


Flow = PIMFlow