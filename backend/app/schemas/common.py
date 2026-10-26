from typing import Annotated, Generic, Iterable, List, TypeVar

from pydantic import BaseModel, StringConstraints

T = TypeVar("T")

Name100 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=100)]
Name255 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=255)]
Code50 = Annotated[str, StringConstraints(strip_whitespace=True, min_length=1, max_length=50)]


class Page(BaseModel, Generic[T]):
    items: List[T]
    total: int
    page: int
    page_size: int


def reject_explicit_nulls(model: BaseModel, fields: Iterable[str]) -> None:
    """For PATCH bodies: a field that is NOT NULL in the database may be omitted, but not sent as null."""
    for name in fields:
        if name in model.model_fields_set and getattr(model, name) is None:
            raise ValueError(f"{name} cannot be null")
