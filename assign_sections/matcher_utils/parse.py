import csv
import datetime
import json
import os
import re
from string import ascii_uppercase
from typing import Optional

from .input_config import (
    ConfigKeys,
    OHPresetHeader,
    PreferencesHeader,
    SectionPresetHeader,
)
from .matcher import MatcherConfig
from .types import (
    PresetAssignmentInfo,
    SectionInfoMap,
    SlotConfigMap,
    UserConfigMap,
    UserPreferenceMap,
)


def parse_config(
    config_file: Optional[str], slot_id_prefix: str = ""
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


def parse_matcher_config(config_file: Optional[str]) -> Optional[MatcherConfig]:
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
    csv_file: Optional[str], slot_id_prefix: str = ""
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


def parse_section_preset_assignment(
    section_preset_assignment_file: Optional[str],
) -> list[PresetAssignmentInfo]:
    """
    Parse the given CSV file of section assignments.

    The input format is identical to the format expected when importing to the CS70 website,
    with the following columns:
    - ta
    - second_ta
    - shortday
    - time
    - type
    - location

    The "second_ta" columns is optional, and can be left blank.
    The "type" column is not read here, and can be left blank.

    The "time" column expects a time in the format "[XX[:XX]][am/pm]-[XX[:XX]][am/pm]",
    for example "10-11am" or "11am-12pm" or "10:30-11:30am".
    Whitespace is removed, and the strings are all converted to lowercase before parsing.
    This method will error if it is unable to parse a given time string.
    """

    if not section_preset_assignment_file:
        return []

    preset_assignment_info = []

    with open(section_preset_assignment_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        csv_rows = list(reader)

    for row in csv_rows:
        ta1 = row[SectionPresetHeader.TA]
        ta2 = row[SectionPresetHeader.TA2]

        days = parse_days(row[SectionPresetHeader.DAY])
        start_time, end_time = parse_human_time_range(row[SectionPresetHeader.TIME])
        location = row[SectionPresetHeader.LOCATION]

        for name in (ta1, ta2):
            if name:
                preset_assignment_info.append(
                    PresetAssignmentInfo(name, days, start_time, end_time, location)
                )

    return preset_assignment_info


def parse_human_time_range(time_str: str) -> tuple[datetime.time, datetime.time]:
    """
    Parse a string of the form "[XX[:XX]][am/pm]-[XX[:XX]][am/pm]",
    for example "10-11am" or "11am-12pm" or "10:30-11:30am".

    Whitespace is removed, and the strings are all converted to lowercase before parsing.
    This method will error if it is unable to parse a given time string.
    """

    # remove whitespace and convert to lowercase
    cleaned_str = re.sub(r"\s", "", time_str).lower()

    components = re.match(
        (
            # [XX[:XX]][am/pm]
            r"(?P<start_h>\d{1,2})(?::(?P<start_m>\d\d))?(?P<start_ampm>am|pm)?"
            # -[XX[:XX]][am/pm]
            r"-(?P<end_h>\d{1,2})(?::(?P<end_m>\d\d))?(?P<end_ampm>am|pm)"
        ),
        cleaned_str,
    )
    if components is None:
        raise ValueError(
            f"Unable to parse time string: {time_str};"
            " expected format [XX[:XX]][am/pm]-[XX[:XX]][am/pm]"
        )

    start_h, start_m, start_ampm = components.group("start_h", "start_m", "start_ampm")
    end_h, end_m, end_ampm = components.group("end_h", "end_m", "end_ampm")

    # convert to integers
    start_h = int(start_h)
    start_m = int(start_m) if start_m else 0
    end_h = int(end_h)
    end_m = int(end_m) if end_m else 0

    if not start_ampm:
        # default to end am/pm value if start am/pm is not given
        start_ampm = end_ampm

    # apply am/pm; special cases for 12am and 12pm, so we mod by 12
    start_h %= 12
    if start_ampm == "pm":
        start_h += 12
    end_h %= 12
    if end_ampm == "pm":
        end_h += 12

    return (
        datetime.time(hour=start_h, minute=start_m),
        datetime.time(hour=end_h, minute=end_m),
    )


def parse_oh_preset_assignment(
    oh_preset_assignment_file: Optional[str],
) -> list[PresetAssignmentInfo]:
    """
    Parse the given CSV file of OH assignments.

    The input format is identical to the format expected when importing to the CS70 website,
    with the following columns:
    - name XX
    - day
    - start_time
    - end_time

    There can be any number of "name XX" columns, ex. "name 1", "name 2", etc.
    In particular, any columns that begin with the string "name" will be considered a name column.

    The "start_time" and "end_time" columns are expected to have times in the format HH:MM am/pm,
    ex. "5:00 PM" or "10:15 AM". This method will error if the time cannot be parsed.
    """
    if not oh_preset_assignment_file:
        return []

    with open(oh_preset_assignment_file, "r", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames is not None, "CSV file must contain a header"

        # get all name columns
        name_columns = [
            field
            for field in reader.fieldnames
            if field.strip().lower().startswith(OHPresetHeader.NAME_PREFIX)
        ]

        csv_rows = list(reader)

    preset_assignment_info = []

    for row in csv_rows:
        for name_col in name_columns:
            name = row[name_col]

            days = row[OHPresetHeader.DAY]
            start_time = datetime.datetime.strptime(
                row[OHPresetHeader.START_TIME], "%I:%M %p"
            )
            end_time = datetime.datetime.strptime(
                row[OHPresetHeader.END_TIME], "%I:%M %p"
            )
            location = row[OHPresetHeader.LOCATION]

            days = parse_days(days)
            start_time = start_time.time()
            end_time = end_time.time()

            preset_assignment_info.append(
                PresetAssignmentInfo(name, days, start_time, end_time, location)
            )

    return preset_assignment_info
