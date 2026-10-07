"""Strict saved-fitting proposal value objects."""

from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, order=True)
class FittingItem:
    type_id: int
    flag: str
    quantity: int

    def __post_init__(self) -> None:
        if type(self.type_id) is not int or self.type_id < 1:
            raise ValueError("type_id must be a positive integer")
        if type(self.quantity) is not int or self.quantity < 1:
            raise ValueError("quantity must be a positive integer")
        if not isinstance(self.flag, str) or not self.flag:
            raise ValueError("flag must be a nonempty catalog flag")
        if not _known_flag(self.flag):
            raise ValueError("flag must be a known fitting slot or bay flag")

    def to_dict(self) -> dict[str, int | str]:
        return {"type_id": self.type_id, "flag": self.flag, "quantity": self.quantity}


@dataclass(frozen=True)
class Fitting:
    name: str
    description: str
    ship_type_id: int
    items: tuple[FittingItem, ...]

    def __post_init__(self) -> None:
        if not isinstance(self.name, str) or not self.name.strip():
            raise ValueError("name must not be empty")
        if not isinstance(self.description, str):
            raise ValueError("description must be a string")
        if type(self.ship_type_id) is not int or self.ship_type_id < 1:
            raise ValueError("ship_type_id must be a positive integer")

    def to_dict(self) -> dict[str, object]:
        return {
            "name": self.name,
            "description": self.description,
            "ship_type_id": self.ship_type_id,
            "items": [item.to_dict() for item in self.items],
        }


def _known_flag(flag: str) -> bool:
    for prefix in ("HiSlot", "MedSlot", "LoSlot", "RigSlot", "ServiceSlot"):
        if flag.startswith(prefix):
            suffix = flag.removeprefix(prefix)
            return suffix.isdigit() and str(int(suffix)) == suffix and 0 <= int(suffix) <= 7
    return flag in {"DroneBay", "FighterBay", "Cargo"}
