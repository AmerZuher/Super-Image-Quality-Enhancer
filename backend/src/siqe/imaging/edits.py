"""The edit document: a non-destructive description of everything done to one image.

Stored as JSON on the asset. Geometry is applied first (rotate, flip, crop), then
adjustments in the canonical order of ``OPS``. Ops whose parameters are all at their
defaults are dropped, so an untouched image has an empty ``ops`` list.
"""

from dataclasses import dataclass
from typing import Annotated, Any, Literal

from pydantic import BaseModel, Field, field_validator, model_validator

from siqe.core.errors import AppError, validation_message


@dataclass(frozen=True)
class Param:
    name: str
    label: str
    min: float
    max: float
    step: float
    default: float
    unit: str = ""


@dataclass(frozen=True)
class OpSpec:
    id: str
    label: str
    group: Literal["light", "color", "detail", "effects"]
    description: str
    params: tuple[Param, ...]


def _amount(label: str = "Amount") -> tuple[Param, ...]:
    return (Param("amount", label, -100, 100, 1, 0),)


# Canonical order: this is the order adjustments are applied in, on the server and in WebGL.
OPS: tuple[OpSpec, ...] = (
    OpSpec("temperature", "Temperature", "color", "Warmer or cooler white balance.", _amount()),
    OpSpec("tint", "Tint", "color", "Green to magenta white balance.", _amount()),
    OpSpec(
        "exposure", "Exposure", "light", "Brightness in stops.", (Param("ev", "Stops", -4, 4, 0.01, 0, "EV"),)
    ),
    OpSpec("whites", "Whites", "light", "Moves the white point.", _amount()),
    OpSpec("blacks", "Blacks", "light", "Moves the black point.", _amount()),
    OpSpec("highlights", "Highlights", "light", "Recovers or brightens bright areas.", _amount()),
    OpSpec("shadows", "Shadows", "light", "Lifts or deepens dark areas.", _amount()),
    OpSpec("contrast", "Contrast", "light", "Spread between darks and lights.", _amount()),
    OpSpec("vibrance", "Vibrance", "color", "Boosts muted colours more than vivid ones.", _amount()),
    OpSpec("saturation", "Saturation", "color", "Intensity of every colour.", _amount()),
    OpSpec("black_white", "Black & white", "color", "Converts to monochrome luminance.", ()),
    OpSpec(
        "sharpen",
        "Sharpen",
        "detail",
        "Adds back fine detail from the original.",
        (Param("amount", "Amount", 0, 300, 1, 0), Param("radius", "Radius", 0.5, 5, 0.1, 1, "px")),
    ),
    OpSpec(
        "vignette",
        "Vignette",
        "effects",
        "Negative darkens the edges, positive lightens them.",
        (Param("amount", "Amount", -100, 100, 1, 0), Param("midpoint", "Midpoint", 0, 0.95, 0.01, 0.5)),
    ),
)

OPS_BY_ID = {op.id: op for op in OPS}
ORDER = {op.id: index for index, op in enumerate(OPS)}


class Crop(BaseModel):
    """Normalised rectangle in the rotated and flipped image (0..1 on both axes)."""

    x: Annotated[float, Field(ge=0, le=1)]
    y: Annotated[float, Field(ge=0, le=1)]
    w: Annotated[float, Field(gt=0, le=1)]
    h: Annotated[float, Field(gt=0, le=1)]

    @model_validator(mode="after")
    def _inside(self) -> "Crop":
        if self.x + self.w > 1.0001 or self.y + self.h > 1.0001:
            raise ValueError("crop rectangle extends outside the image")
        return self


class Geometry(BaseModel):
    rotate: Literal[0, 90, 180, 270] = 0
    flip_h: bool = False
    flip_v: bool = False
    crop: Crop | None = None


class OpEntry(BaseModel):
    id: str
    enabled: bool = True
    params: dict[str, float] = Field(default_factory=dict)


class EditDocument(BaseModel):
    version: Literal[1] = 1
    geometry: Geometry = Field(default_factory=Geometry)
    ops: list[OpEntry] = Field(default_factory=list)

    @field_validator("ops")
    @classmethod
    def _canonical(cls, ops: list[OpEntry]) -> list[OpEntry]:
        seen: set[str] = set()
        cleaned: list[OpEntry] = []
        for entry in ops:
            spec = OPS_BY_ID.get(entry.id)
            if spec is None:
                raise ValueError(f"unknown operation '{entry.id}'")
            if entry.id in seen:
                raise ValueError(f"operation '{entry.id}' appears twice")
            seen.add(entry.id)
            params: dict[str, float] = {}
            for p in spec.params:
                value = float(entry.params.get(p.name, p.default))
                if not p.min <= value <= p.max:
                    raise ValueError(
                        f"{spec.label} {p.label.lower()} must be between {p.min:g} and {p.max:g}"
                    )
                params[p.name] = value
            unknown = set(entry.params) - {p.name for p in spec.params}
            if unknown:
                raise ValueError(f"unknown parameter(s) for {entry.id}: {', '.join(sorted(unknown))}")
            # Drop ops that change nothing (all parameters at default), except toggles like B&W.
            if spec.params and all(params[p.name] == p.default for p in spec.params):
                continue
            if spec.id == "sharpen" and params["amount"] == 0:
                continue
            if spec.id == "vignette" and params["amount"] == 0:
                continue
            cleaned.append(OpEntry(id=entry.id, enabled=entry.enabled, params=params))
        return sorted(cleaned, key=lambda e: ORDER[e.id])

    def active(self) -> dict[str, dict[str, float]]:
        return {e.id: e.params for e in self.ops if e.enabled}


def parse_document(raw: dict[str, Any] | None) -> EditDocument:
    try:
        return EditDocument.model_validate(raw or {})
    except ValueError as exc:
        raise AppError(
            "edit.invalid",
            f"The edit settings aren't valid: {validation_message(exc)}.",
            status=422,
            title="Invalid edits",
            fix="Reset the edits for this image, then try again.",
        ) from exc


def catalog() -> list[dict[str, Any]]:
    """Operation metadata for the UI: labels, groups and parameter ranges."""
    return [
        {
            "id": op.id,
            "label": op.label,
            "group": op.group,
            "description": op.description,
            "params": [p.__dict__ for p in op.params],
        }
        for op in OPS
    ]
