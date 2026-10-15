"""Strict input schemas and fixture-only reference access matrix (not API authorization)."""

from typing import Literal, Self

from pydantic import BaseModel, ConfigDict, Field, model_validator

type Role = Literal["ADMIN", "KNOWLEDGE_MANAGER", "EMPLOYEE", "AUDITOR"]


class Schema(BaseModel):
    model_config = ConfigDict(extra="forbid")


class Persona(Schema):
    id: str
    email: str
    roles: list[Role]
    departments: list[str]
    active: bool


class Personas(Schema):
    version: str
    personas: list[Persona]


class DemoDocument(Schema):
    id: str
    file: str
    title: str
    visibility: Literal["COMPANY", "DEPARTMENT", "RESTRICTED"]
    department: str
    owner: str
    read_users: list[str]
    read_roles: list[Role]
    sha256: str = Field(pattern=r"^[0-9a-f]{64}$")
    size_bytes: int = Field(gt=0)
    version: int = Field(ge=1)


class Manifest(Schema):
    version: str
    synthetic: Literal[True]
    documents: list[DemoDocument]


class ExpectedEvidence(Schema):
    document_id: str
    quote: str = Field(min_length=1)


class GoldenCase(Schema):
    id: str
    category: Literal["answerable", "no_evidence", "restricted"]
    persona: str
    question: str = Field(min_length=1)
    reference_answer: str | None
    expected_sources: list[str]
    forbidden_sources: list[str]
    evidence: list[ExpectedEvidence]

    @model_validator(mode="after")
    def validate_expectations(self) -> Self:
        if self.category == "answerable":
            if not self.reference_answer or not self.expected_sources or self.forbidden_sources:
                raise ValueError("answerable case needs an answer and allowed sources")
            if {item.document_id for item in self.evidence} != set(self.expected_sources):
                raise ValueError("each expected source needs reference evidence")
        elif self.reference_answer or self.expected_sources or self.evidence:
            raise ValueError("abstention cases must not contain response evidence")
        if (self.category == "restricted") != bool(self.forbidden_sources):
            raise ValueError(
                "restricted cases need forbidden sources; other cases must not have them"
            )
        return self


class GoldenDataset(Schema):
    version: str
    corpus_version: str
    cases: list[GoldenCase]


def reference_can_read(persona: Persona, document: DemoDocument) -> bool:
    """Validate fixture intent. The database policy implementation arrives in phase 1/2."""
    if not persona.active:
        return False
    if "ADMIN" in persona.roles:
        return True
    if (
        persona.id == document.owner
        or persona.id in document.read_users
        or bool(set(persona.roles) & set(document.read_roles))
    ):
        return True
    if set(persona.roles) == {"AUDITOR"}:
        return False
    return document.visibility == "COMPANY" or (
        document.visibility == "DEPARTMENT" and document.department in persona.departments
    )
