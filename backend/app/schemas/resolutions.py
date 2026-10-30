from datetime import datetime
from typing import Annotated

from pydantic import BaseModel, Field, StringConstraints

Note = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=2000)]


class NoteRequest(BaseModel):
    version: int
    note: Note


class OptionalNoteRequest(BaseModel):
    version: int
    note: str | None = Field(default=None, max_length=2000)


class ResolutionOut(BaseModel):
    decision: str
    note: str | None
    actor_email: str | None
    exception_version: int
    created_at: datetime
