from typing import Annotated, Literal, Self

from pydantic import BaseModel, ConfigDict, Field, StringConstraints, model_validator

Text = Annotated[str, StringConstraints(min_length=1, max_length=20000, pattern=r"\S")]
Identifier = Annotated[str, StringConstraints(pattern=r"^[a-zA-Z0-9_.-]+$", max_length=100)]
Number = Annotated[float, Field(strict=True, ge=0, allow_inf_nan=False)]


class Model(BaseModel):
    model_config = ConfigDict(extra="forbid")


class TurnInput(Model):
    timestamp: Text
    speaker: Literal["client", "operator", "bot", "system"]
    text: Text


class Message(TurnInput):
    message_id: Identifier


class ConversationInput(Model):
    conversation_id: Text
    channel: Literal["agent chat", "voice call"]
    language: Literal["RU", "KZ", "EN"]
    transcript: list[TurnInput] = Field(min_length=1, max_length=10000)
    audio_url: str | None = None


class Conversation(Model):
    conversation_id: Text
    channel: Literal["agent chat", "voice call"]
    language: Literal["RU", "KZ", "EN"]
    transcript: list[Message] = Field(min_length=1)
    audio_url: str | None = None

    @model_validator(mode="after")
    def unique_messages(self) -> Self:
        ids = [m.message_id for m in self.transcript]
        if len(ids) != len(set(ids)):
            raise ValueError("Message IDs must be unique")
        return self


class Dataset(Model):
    dataset_group_id: Text
    total_records: int = Field(ge=0, strict=True)
    records: list[ConversationInput] = Field(max_length=500)

    @model_validator(mode="after")
    def consistent_count(self) -> Self:
        if self.total_records != len(self.records):
            raise ValueError("total_records does not match records")
        ids = [r.conversation_id for r in self.records]
        if len(ids) != len(set(ids)):
            raise ValueError("Duplicate conversation_id in dataset")
        return self


class DatasetEnvelope(Model):
    error: str
    isSuccess: bool
    data: Dataset

    @model_validator(mode="after")
    def successful(self) -> Self:
        if not self.isSuccess or self.error:
            raise ValueError("Dataset API reported an error")
        return self


class ScaleLevel(Model):
    value: Number
    description: Text


class Criterion(Model):
    id: Identifier
    title: Text
    section: Text
    kind: Literal["binary", "scale", "flag"]
    weight: Number
    instructions: Text
    allow_na: bool = False
    na_condition: Text | None = None
    scale: list[ScaleLevel] = Field(default_factory=list)
    evidence_policy: Literal["any", "operator", "first_operator"] = "any"

    @model_validator(mode="after")
    def consistent_rules(self) -> Self:
        if self.allow_na != (self.na_condition is not None):
            raise ValueError("N/A requires exactly one applicability condition")
        if self.kind == "scale":
            values = [s.value for s in self.scale]
            if len(values) < 2 or len(values) != len(set(values)) or min(values) != 0:
                raise ValueError(
                    "Scale must have unique levels, including 0 and a positive maximum"
                )
        elif self.scale:
            raise ValueError("Only scale criteria may define scale levels")
        if self.kind == "flag" and (self.weight != 0 or self.allow_na):
            raise ValueError("Flags have no weight and cannot be N/A")
        if self.kind != "flag" and self.weight <= 0:
            raise ValueError("Scored criteria require a positive weight")
        return self


class Checklist(Model):
    id: Identifier
    version: int = Field(ge=1, strict=True)
    title: Text
    instructions: Text
    criteria: list[Criterion] = Field(min_length=1, max_length=100)

    @model_validator(mode="after")
    def unique_criteria(self) -> Self:
        ids = [c.id for c in self.criteria]
        if len(ids) != len(set(ids)):
            raise ValueError("Criterion IDs must be unique")
        return self


class CheckedRange(Model):
    start_message_id: Identifier
    end_message_id: Identifier


class Judgment(Model):
    # All fields required (nullable where appropriate) for strict Structured Outputs.
    criterion_id: Identifier
    decision: Literal["yes", "no", "score", "na"]
    score: Number | None
    explanation: Text
    evidence_message_ids: list[Identifier]
    checked_range: CheckedRange | None
    na_reason: Text | None


class ModelResponse(Model):
    judgments: list[Judgment]


class CriterionResult(Model):
    criterion_id: str
    title: str
    section: str
    kind: str
    judgment: Judgment
    evidence: list[Message]
    weight: float
    effective_weight: float
    earned_weight: float | None
    contribution: float | None
    flagged: bool


class SectionResult(Model):
    section: str
    applicable_weight: float
    earned_weight: float
    score: float | None


class ScoreResult(Model):
    total_score: float | None
    applicable_weight: float
    earned_weight: float
    flagged_criteria: list[str]
    criteria: list[CriterionResult]
    sections: list[SectionResult]
