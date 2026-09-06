"""Contrat `Notifier` et schéma `spam:` de `thresholds.yaml`."""

from __future__ import annotations

from datetime import time
from typing import Protocol

from pydantic import BaseModel, Field, field_validator


class Action(BaseModel):
    action: str = "view"  # 'view' | 'http'
    label: str
    url: str
    method: str | None = None
    clear: bool = True


class Notification(BaseModel):
    title: str
    body: str
    priority: int  # 5 = achat immédiat, 2 = enchère (muette)
    tags: list[str] = Field(default_factory=list)
    click: str
    actions: list[Action] = Field(default_factory=list)


class Notifier(Protocol):
    def send(self, n: Notification) -> None: ...


# --- vue `spam:` de thresholds.yaml -------------------------------------------------


class QuietHours(BaseModel):
    from_: time = Field(alias="from")
    to: time
    downgrade_to: int = 3

    model_config = {"populate_by_name": True}

    @field_validator("from_", "to", mode="before")
    @classmethod
    def _parse(cls, v: object) -> object:
        if isinstance(v, str):
            hh, mm = v.split(":")
            return time(int(hh), int(mm))
        return v


class SpamPolicy(BaseModel):
    daily_cap_urgent: int = 6
    re_alert_min_drop_pct: float = 10
    quiet_hours: QuietHours


class NotifySettings(BaseModel):
    spam: SpamPolicy


def load_spam_policy() -> SpamPolicy:
    from ramtracker.core.config import load_yaml

    return load_yaml("thresholds", NotifySettings).spam
