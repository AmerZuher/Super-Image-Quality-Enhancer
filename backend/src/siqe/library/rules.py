"""Smart album rules and Library filters, compiled to SQL.

A rule set is ``{"match": "all" | "any", "rules": [{"field", "op", "value"}, ...]}``. The same
rules drive smart albums and the filter chips, so anything a user can filter by can become an
album. Every field and operator is checked here; nothing user-supplied reaches SQL as text.
"""

from datetime import UTC, date, datetime, timedelta
from typing import Any, Literal

from pydantic import BaseModel, Field, model_validator
from sqlalchemy import ColumnElement, and_, any_, false, func, literal, or_, true

from siqe.db.models import Asset

Field_ = Literal[
    "orientation",
    "width",
    "height",
    "megapixels",
    "aspect",
    "format",
    "color",
    "tag",
    "sharpness",
    "has_gps",
    "ai_result",
    "duplicate",
    "taken",
    "added_days",
    "name",
    "folder",
]
Op = Literal["is", "is_not", "gte", "lte", "approx", "has", "after", "before", "contains", "starts_with"]

OPS: dict[str, tuple[str, ...]] = {
    "orientation": ("is", "is_not"),
    "width": ("gte", "lte"),
    "height": ("gte", "lte"),
    "megapixels": ("gte", "lte"),
    "aspect": ("gte", "lte", "approx"),
    "format": ("is", "is_not"),
    "color": ("is", "is_not"),
    "tag": ("has", "is_not"),
    "sharpness": ("gte", "lte"),
    "has_gps": ("is",),
    "ai_result": ("is",),
    "duplicate": ("is",),
    "taken": ("after", "before"),
    "added_days": ("lte", "gte"),
    "name": ("contains",),
    "folder": ("starts_with",),
}
NUMERIC = frozenset({"width", "height", "megapixels", "aspect", "sharpness", "added_days"})
BOOLEAN = frozenset({"has_gps", "ai_result", "duplicate"})
ORIENTATIONS = ("landscape", "portrait", "square")
SQUARE_TOLERANCE = 0.02
ASPECT_TOLERANCE = 0.03


class Rule(BaseModel):
    field: Field_
    op: Op
    value: str | float | bool

    @model_validator(mode="after")
    def _check(self) -> "Rule":
        if self.op not in OPS[self.field]:
            raise ValueError(f"'{self.op}' can't be used with {self.field}")
        numeric = isinstance(self.value, int | float) and not isinstance(self.value, bool)
        if self.field in NUMERIC and not numeric:
            raise ValueError(f"{self.field} needs a number")
        if self.field in BOOLEAN and not isinstance(self.value, bool):
            raise ValueError(f"{self.field} needs true or false")
        if self.field not in NUMERIC | BOOLEAN:
            if not isinstance(self.value, str) or not self.value.strip():
                raise ValueError(f"{self.field} needs some text")
            self.value = self.value.strip()[:120]
        if self.field == "orientation" and self.value not in ORIENTATIONS:
            raise ValueError("orientation is landscape, portrait or square")
        if self.field == "taken":
            date.fromisoformat(str(self.value))
        return self


class RuleSet(BaseModel):
    match: Literal["all", "any"] = "all"
    rules: list[Rule] = Field(default_factory=list, max_length=20)


def _orientation(value: str) -> ColumnElement[bool]:
    w, h = Asset.width, Asset.height
    square = func.abs(w - h) <= func.greatest(w, h) * SQUARE_TOLERANCE
    if value == "square":
        return square
    return and_(~square, w > h) if value == "landscape" else and_(~square, h > w)


def _aspect() -> ColumnElement[Any]:
    return Asset.width * 1.0 / func.greatest(Asset.height, 1)


def compile_rule(rule: Rule, *, now: datetime | None = None) -> ColumnElement[bool]:
    f, op, v = rule.field, rule.op, rule.value
    negate = op == "is_not"
    clause: ColumnElement[bool]
    if f == "orientation":
        clause = _orientation(str(v))
    elif f in ("width", "height", "megapixels", "sharpness", "aspect"):
        column: Any = {
            "width": Asset.width,
            "height": Asset.height,
            "megapixels": Asset.width * Asset.height / 1e6,
            "sharpness": Asset.sharpness,
            "aspect": _aspect(),
        }[f]
        number = float(v)
        if op == "approx":
            clause = func.abs(column - number) <= number * ASPECT_TOLERANCE
        else:
            clause = column >= number if op == "gte" else column <= number
    elif f == "format":
        clause = Asset.format == str(v).lower()
    elif f == "color":
        clause = Asset.color == str(v).lower()
    elif f == "tag":
        tag = str(v).lower()
        clause = or_(literal(tag) == any_(Asset.tags), literal(tag) == any_(Asset.auto_tags))
    elif f == "has_gps":
        clause = Asset.has_gps.is_(True) if v else Asset.has_gps.is_(False)
    elif f == "ai_result":
        clause = Asset.parent_id.is_not(None) if v else Asset.parent_id.is_(None)
    elif f == "duplicate":
        clause = Asset.duplicate_group.is_not(None) if v else Asset.duplicate_group.is_(None)
    elif f == "taken":
        day = datetime.combine(date.fromisoformat(str(v)), datetime.min.time(), tzinfo=UTC)
        clause = Asset.taken_at >= day if op == "after" else Asset.taken_at < day + timedelta(days=1)
    elif f == "added_days":
        cutoff = (now or datetime.now(UTC)) - timedelta(days=float(v))
        clause = Asset.created_at >= cutoff if op == "lte" else Asset.created_at < cutoff
    elif f == "name":
        clause = Asset.original_name.ilike(f"%{_escape(str(v))}%", escape="\\")
    else:  # folder
        clause = Asset.source["path"].astext.like(f"{_escape(str(v))}%", escape="\\")
    return ~clause if negate else clause


def _escape(text: str) -> str:
    return text.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")


def compile_rules(rules: RuleSet, *, now: datetime | None = None) -> ColumnElement[bool]:
    if not rules.rules:
        return true()
    parts = [compile_rule(r, now=now) for r in rules.rules]
    return and_(*parts) if rules.match == "all" else or_(false(), *parts)


def parse(data: dict[str, Any] | None) -> RuleSet:
    return RuleSet.model_validate(data or {})


# Albums every new library starts with. Users can edit or delete them.
DEFAULT_ALBUMS: list[tuple[str, dict[str, Any]]] = [
    (
        "Desktop wallpapers",
        {
            "match": "all",
            "rules": [
                {"field": "orientation", "op": "is", "value": "landscape"},
                {"field": "width", "op": "gte", "value": 1920},
            ],
        },
    ),
    (
        "Phone wallpapers",
        {
            "match": "all",
            "rules": [
                {"field": "orientation", "op": "is", "value": "portrait"},
                {"field": "aspect", "op": "lte", "value": 0.6},
                {"field": "height", "op": "gte", "value": 1600},
            ],
        },
    ),
    (
        "Needs enhancing",
        {
            "match": "any",
            "rules": [
                {"field": "width", "op": "lte", "value": 1000},
                {"field": "sharpness", "op": "lte", "value": 0.3},
            ],
        },
    ),
    ("Has location", {"match": "all", "rules": [{"field": "has_gps", "op": "is", "value": True}]}),
]
