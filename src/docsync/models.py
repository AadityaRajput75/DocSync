from typing import Literal

from pydantic import BaseModel, ConfigDict, Field


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Decision(StrictModel):
    action: Literal["tool", "draft", "no_update", "insufficient_evidence"]
    summary: str = Field(max_length=500)
    tool: Literal["list_tree", "read_file", "search_text", "find_symbol", "get_related_symbols"] | None = None
    arguments: dict = Field(default_factory=dict)


class Citation(StrictModel):
    path: str
    start: int = Field(ge=1)
    end: int = Field(ge=1)


class Draft(StrictModel):
    content: str = Field(min_length=1, max_length=60_000)
    summary: str = Field(max_length=800)
    citations: list[Citation] = Field(min_length=1, max_length=20)
    symbols: list[str] = Field(
        default_factory=list, max_length=30,
        description="Exact source-defined or explicitly imported names referenced in the draft. "
                    "For aliased imports use the local alias or full import path. "
                    "Do not infer members of imported modules or wildcard imports.",
    )


class ProjectCreate(StrictModel):
    root: str
    watching: bool = True
    ignore: list[str] = Field(default_factory=list)


class ProjectPatch(StrictModel):
    watching: bool | None = None
    provider: Literal["local", "gemini"] | None = None
    cloud_consent: bool | None = None
    ignore: list[str] | None = None


class Review(StrictModel):
    decision: Literal["accept", "reject", "edit"]
    content: str | None = Field(default=None, max_length=60_000)
