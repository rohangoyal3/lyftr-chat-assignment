from typing import Annotated, Literal

from pydantic import BaseModel, Field, StrictStr, StringConstraints, field_validator


class ChatRequest(BaseModel):
    session_id: Annotated[StrictStr, Field(min_length=1, max_length=128)]
    message: Annotated[str, StringConstraints(strict=True, strip_whitespace=True, min_length=1, max_length=4000)]
    system_prompt: StrictStr | None = None

    @field_validator("session_id")
    @classmethod
    def nonblank_session_id(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("session_id cannot be blank")
        return value


class Metadata(BaseModel):
    resolution_source: Literal["LIVE_INFERENCE", "LLM_CACHE"]
    model: str
    latency_ms: int = Field(ge=0)
    input_tokens: int = Field(ge=0)
    output_tokens: int = Field(ge=0)
    key_id: str | None
    fallback_attempts: int = Field(ge=0)


class ChatResponse(BaseModel):
    session_id: str
    reply: str = Field(min_length=1)
    metadata: Metadata
