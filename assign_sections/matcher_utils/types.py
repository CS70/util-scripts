import datetime
from dataclasses import dataclass
from typing import TypedDict


class UserConfig(TypedDict):
    """Config for users, parsed from JSON."""

    min_slots: int
    max_slots: int


UserConfigMap = dict[str, UserConfig]


class SlotConfig(TypedDict):
    """Config for slots, parsed from JSON."""

    min_users: int
    max_users: int


SlotConfigMap = dict[str, SlotConfig]

# map of {name: {slot_id: preference}}
UserPreferenceMap = dict[str, dict[str, int]]

# map of {slot_id: {info_key: value}}
SectionInfoMap = dict[str, dict[str, str]]


@dataclass
class PresetAssignmentInfo:
    """Information for section/OH preset assignments."""

    name: str
    days: list[int]
    start_time: datetime.time
    end_time: datetime.time
    location: str
