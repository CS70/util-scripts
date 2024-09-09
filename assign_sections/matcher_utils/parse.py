import csv
import datetime
import json
import os
from string import ascii_uppercase
from typing import Optional

from .input_config import ConfigKeys, PreferencesHeader
from .matcher import MatcherConfig
from .types import SectionInfoMap, SlotConfigMap, UserConfigMap, UserPreferenceMap


def parse_config(
    config_file: str, slot_id_prefix: str = ""
) -> tuple[UserConfigMap, SlotConfigMap]:
    """
    Parse a config JSON file for user/slot counts.
    """
    if not config_file or not os.path.isfile(config_file):
        return {}, {}

    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)

    user_counts = config[ConfigKeys.USERS]
    slot_counts = config[ConfigKeys.SLOTS]

    if slot_id_prefix:
        slot_counts = {slot_id_prefix + key: val for key, val in slot_counts.items()}

    return user_counts, slot_counts


def parse_matcher_config(config_file: str) -> Optional[MatcherConfig]:
    """
    Parse a config JSON file for the matcher.
    """
    if not config_file or not os.path.isfile(config_file):
        return None

    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)

    return MatcherConfig.from_dict(config)


def parse_time(time_str: str) -> datetime.time:
    """
    Parse a time string into a `datetime.time` object.
    """
    return datetime.time.fromisoformat(time_str)


def parse_preferences(
    csv_file: str, slot_id_prefix: str = ""
) -> tuple[UserPreferenceMap, SectionInfoMap]:
    """
    Read preferences from a CSV file.
    """
    if not csv_file or not os.path.isfile(csv_file):
        return {}, {}

    # read the first row first
    with open(csv_file, "r", encoding="utf-8") as f:
        first_row = f.readline()

    user_names = [
        header.strip()
        for header in first_row.split(",")
        if header.strip() not in PreferencesHeader.ALL
    ]

    fieldnames = [
        *PreferencesHeader.ALL,
        *user_names,
    ]

    # initialize section preference map
    preference_map = {name: {} for name in user_names}
    info = {}

    with open(csv_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f, fieldnames=fieldnames)

        first_row = next(reader)
        for key, val in first_row.items():
            assert key == val, f"Expected {key}, got {val} in header"

        for row in reader:
            slot_id = slot_id_prefix + row[PreferencesHeader.ID]
            for name in user_names:
                preference_map[name][slot_id] = int(row[name])

            cur_info = {}
            for key in PreferencesHeader.ALL:
                cur_info[key] = row[key]
            info[slot_id] = cur_info

    return preference_map, info


def parse_days(day_str: str) -> list[int]:
    """
    Parse the days from a day string.
    Assumes that each day begins with an uppercase letter, followed by lowercase letters,
    where Tuesday and Thursday are differentiated by at least the second letter,
    and Saturday and Sunday are similarly differentiated by at least the second letter.

    Result is a list of day indices, where Monday = 0, and Sunday = 6

    Examples:
      - "TuTh"
      - "WF"
      - "Monday, Wednesday"
      - "TuF"
    """
    day_map = {
        "M": 0,
        "Tu": 1,
        "W": 2,
        "Th": 3,
        "F": 4,
        "Sa": 5,
        "Su": 6,
    }

    days = []
    for idx, c in enumerate(day_str):
        # only look at uppercase letters
        if c not in ascii_uppercase:
            continue

        if c in day_map:
            # one letter day
            days.append(day_map[c])
        else:
            assert (
                idx < len(day_str) - 1
            ), "More than one letter required to uniquely identify the day, but reached EOS"
            next_char = day_str[idx + 1]
            two_letters = f"{c}{next_char}"

            if two_letters in day_map:
                days.append(day_map[two_letters])
            else:
                raise ValueError(
                    f"Unable to identify day starting with '{two_letters}'"
                )

    return days
