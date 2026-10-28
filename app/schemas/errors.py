from pydantic import BaseModel, Field


class ErrorDetail(BaseModel):
    field: str = Field(
        description="Dotted path of the offending request field.", examples=["amount"]
    )
    message: str = Field(examples=["Input should be greater than 0"])


class ErrorBody(BaseModel):
    code: str = Field(
        description="Stable machine-readable error code. Branch on this, not on the message.",
        examples=["insufficient_funds"],
    )
    message: str = Field(
        description="Human-readable explanation. May change between releases.",
        examples=["Insufficient funds"],
    )
    details: list[ErrorDetail] = Field(
        default_factory=list,
        description="Per-field problems. Non-empty for validation errors only.",
    )


class ErrorResponse(BaseModel):
    error: ErrorBody
