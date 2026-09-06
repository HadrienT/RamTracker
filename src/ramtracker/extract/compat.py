"""Schéma de `configs/compat.yaml` — la matrice de qualification.

`extract` ne lit pas le fichier lui-même (D8) : `core.config.load_yaml` le fait
et passe un `CompatMatrix` à la cascade.
"""

from __future__ import annotations

from pydantic import BaseModel, Field


class _AcceptReject(BaseModel):
    accept: list[str] = Field(default_factory=list)
    reject: list[str] = Field(default_factory=list)


class _Speed(BaseModel):
    native: list[int] = Field(default_factory=list)
    accept_downclock: list[int] = Field(default_factory=list)


class _Ranks(BaseModel):
    accept: list[str] = Field(default_factory=list)
    reject: list[str] = Field(default_factory=list)


class _Capacity(BaseModel):
    accept: list[int] = Field(default_factory=list)
    reject: list[int] = Field(default_factory=list)


class _Brands(BaseModel):
    accept: list[str] = Field(default_factory=list)
    flag: list[str] = Field(default_factory=list)


class _VendorTable(BaseModel):
    family: dict[str, str] = Field(default_factory=dict)
    density: dict[str, int] = Field(default_factory=dict)
    speed: dict[str, int] = Field(default_factory=dict)


class CompatMatrix(BaseModel):
    generation: _AcceptReject = Field(default_factory=_AcceptReject)
    registration: _AcceptReject = Field(default_factory=_AcceptReject)
    form_factor: _AcceptReject = Field(default_factory=_AcceptReject)
    speed_mts: _Speed = Field(default_factory=_Speed)
    ranks: _Ranks = Field(default_factory=_Ranks)
    capacity_gb: _Capacity = Field(default_factory=_Capacity)
    brands: _Brands = Field(default_factory=_Brands)
    part_numbers: dict[str, _VendorTable] = Field(default_factory=dict)
    reject_keywords: list[str] = Field(default_factory=list)

    def accepts_speed(self, mts: int) -> bool:
        return mts in self.speed_mts.native or mts in self.speed_mts.accept_downclock

    def native_speed(self, mts: int) -> bool:
        return mts in self.speed_mts.native
