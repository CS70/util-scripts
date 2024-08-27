import csv
import datetime
import json
import os
import random
from enum import StrEnum
from string import ascii_uppercase

import matplotlib
import matplotlib.colors
import numpy as np
from rich.console import Console
from rich.table import Table, box
from rich.theme import Theme

from matcher import (
    MatcherConfig,
    Preference,
    Slot,
    User,
    compute_slot_datetime,
    get_matches,
)

console = Console(theme=Theme({"repr.number": ""}))

SECTION_PREFERENCES_FILE = "preferences.xlsx"
OH_PREFERENCES_FILE = "preferences.xlsx"
SECTION_WORKSHEET_NAME = "Section Matching"
OH_WORKSHEET_NAME = "OH Matching"
SECTION_COUNT_WORKSHEET_NAME = "Section Counts"
OH_COUNT_WORKSHEET_NAME = "OH Counts"

COLOR_MAP_GRADIENT = matplotlib.colors.LinearSegmentedColormap.from_list(
    "rg", ["#FF0000", "#FFFF00", "#00FF00"], N=256
)
COLOR_MAP_DISCRETE = {
    0: "white on #FF0000",
    1: "black on #FF9900",
    3: "black on #FFFF00",
    5: "black on #00FF00",
}


class PreferencesHeader:
    """Header values for the preferences spreadsheet."""

    ID = "ID"
    LOCATION = "Location"
    DAY = "Day"
    START_TIME = "Start Time"
    END_TIME = "End Time"

    ALL = [ID, LOCATION, DAY, START_TIME, END_TIME]


class ConfigKeys:
    """Keys for the config file."""

    USERS = "users"
    SLOTS = "slots"

    # subkeys under SLOTS
    MIN_USERS = "min_users"
    MAX_USERS = "max_users"

    # subkeys under USERS
    MIN_SLOTS = "min_slots"
    MAX_SLOTS = "max_slots"


class PrintFormat(StrEnum):
    TABLE = "table"
    CSV = "csv"


class PrintColors(StrEnum):
    DISCRETE = "discrete"
    GRADIENT = "gradient"


def compute_color(
    pref, min_pref, max_pref, print_colors: PrintColors = PrintColors.DISCRETE
):
    """
    Compute the associated `rich` color style based on a preference and a preference range.
    """
    if print_colors == PrintColors.DISCRETE:
        if pref in COLOR_MAP_DISCRETE:
            return COLOR_MAP_DISCRETE[pref]
        else:
            return "normal"
    else:
        scaled_pref = (pref - min_pref) / (max_pref - min_pref)
        color = COLOR_MAP_GRADIENT(scaled_pref)
        hex_color = matplotlib.colors.rgb2hex(color)
        hsv_color = matplotlib.colors.rgb_to_hsv(color[:3])

        text_color = "white" if hsv_color[2] < 0.5 else "black"
        return f"{text_color} on {hex_color}"


def format_slot(slot: Slot):
    """
    Convert a discussion info dict into a human-readable string.
    """
    start_str = format_time(slot.start_time)
    end_str = format_time(slot.end_time)
    return f"{format_days(slot.days)} {start_str}-{end_str} @ {slot.location}"


def parse_preferences(csv_file: str, slot_id_prefix: str = ""):
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


def parse_config(config_file: str, slot_id_prefix: str = ""):
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


def parse_matcher_config(config_file: str):
    """
    Parse a config JSON file for the matcher.
    """
    if not config_file or not os.path.isfile(config_file):
        return None

    with open(config_file, "r", encoding="utf-8") as f:
        config = json.load(f)

    return MatcherConfig.from_dict(config)


def parse_time(time_str: str):
    """
    Parse a time string into a `datetime.time` object.
    """
    return datetime.time.fromisoformat(time_str)


def format_time(time: datetime.time):
    """
    Format a `datetime.time` object into a time string.
    """
    if time.minute == 0:
        return time.strftime("%-I%p")
    return time.strftime("%-I:%M%p")


def parse_days(day_str: str):
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


def format_days(day_list: list[int]):
    """
    Formats a list of day integers (where Monday = 0, Sunday = 6) into a string.
    """
    days = ["M", "Tu", "W", "Th", "F", "Sa", "Su"]
    return "".join(days[day] for day in day_list)


def print_assignment_by_user(
    assignment: dict[str, list[Slot]],
    users: list[User],
    preference_map: dict[str, dict[str, int]],
    title: str = "",
    print_format: PrintFormat = PrintFormat.TABLE,
    print_colors: PrintColors = PrintColors.DISCRETE,
    print_empty: bool = False,
):
    """
    Given a map from user_id (name) to the list of assigned slots,
    prints the slots assigned to each user.
    """
    # sort users by user_id (name)
    sorted_users = sorted(users, key=lambda u: u.name)

    # min and max preferences
    min_pref = min(
        pref for user_pref in preference_map.values() for pref in user_pref.values()
    )
    max_pref = max(
        pref for user_pref in preference_map.values() for pref in user_pref.values()
    )

    table_rows = []
    for user in sorted_users:
        assigned_slots = assignment.get(user.name, [])
        if not print_empty and not assigned_slots:
            # skip if we don't want to print empty assignments
            continue

        formatted_discussions = []

        # sort slots by first start time
        sorted_slots = sorted(
            assigned_slots,
            key=lambda slot: compute_slot_datetime(min(slot.days), slot.start_time),
        )

        for slot in sorted_slots:
            disc_str = format_slot(slot)
            pref = preference_map[user.name][slot.id]
            pref_color = compute_color(
                pref, min_pref, max_pref, print_colors=print_colors
            )
            formatted_discussions.append(f"[{pref_color}]{disc_str}[/{pref_color}]")

        table_rows.append([user.name, *formatted_discussions])

    # name column, followed by assigned slots
    num_columns = max(len(row) for row in table_rows)
    table_by_ta = Table("Name", "Assigned", box=box.SIMPLE, title=title)

    if print_format == PrintFormat.TABLE:
        for _ in range(num_columns - 2):
            table_by_ta.add_column()

        for table_row in table_rows:
            if len(table_row) != num_columns:
                table_row = [*table_row, *([""] * (num_columns - len(table_row)))]
            table_by_ta.add_row(*table_row)
        console.print(table_by_ta)
    elif print_format == PrintFormat.CSV:
        print(f"===== {title} =====\n")
        for table_row in table_rows:
            console.print(",".join(table_row + [""] * (num_columns - len(table_row))))


def print_assignment_by_slot(
    assignment: dict[str, list[Slot]],
    slots: list[Slot],
    preference_map: dict[str, dict[str, int]],
    title: str = "",
    print_format: PrintFormat = PrintFormat.TABLE,
    print_colors: PrintColors = PrintColors.DISCRETE,
    print_empty: bool = False,
):
    """
    Given a map from user_id (name) to the list of assigned slots,
    prints the users assigned to each slot.
    """
    # min and max preferences
    min_pref = min(
        pref for user_pref in preference_map.values() for pref in user_pref.values()
    )
    max_pref = max(
        pref for user_pref in preference_map.values() for pref in user_pref.values()
    )

    users_per_slot: dict[str, set[str]] = {}
    for name, assigned_slots in assignment.items():
        for slot in assigned_slots:
            if slot.id not in users_per_slot:
                users_per_slot[slot.id] = set()
            users_per_slot[slot.id].add(name)

    # precompute map from ID to slot
    slots_by_id: dict[str, Slot] = {slot.id: slot for slot in slots}
    sorted_slots = sorted(
        slots_by_id.items(),
        key=lambda t: (
            compute_slot_datetime(min(t[1].days), t[1].start_time),
            t[1].location,
        ),
    )

    table_rows = []
    for slot_id, slot in sorted_slots:
        sorted_names = sorted(users_per_slot.get(slot_id, []))
        if not print_empty and not sorted_names:
            # skip if we don't want to print empty assignments
            continue

        slot = slots_by_id[slot_id]

        colored_names = []
        for name in sorted_names:
            pref = preference_map[name][slot_id]
            pref_color = compute_color(
                pref, min_pref, max_pref, print_colors=print_colors
            )
            colored_names.append(f"[{pref_color}]{name}[/{pref_color}]")
        table_rows.append(
            [
                slot.location,
                format_days(slot.days),
                format_time(slot.start_time),
                format_time(slot.end_time),
                *colored_names,
            ]
        )

    # location, day, time columns followed by assigned TAs
    num_columns = max(len(row) for row in table_rows)
    if print_format == PrintFormat.TABLE:
        table_by_slot = Table(
            "Location",
            "Day",
            "Start Time",
            "End Time",
            "Assigned",
            box=box.SIMPLE,
            title=title,
        )
        for _ in range(num_columns - 4):
            table_by_slot.add_column()

        for table_row in table_rows:
            if len(table_row) != num_columns:
                table_row = [*table_row, *([""] * (num_columns - len(table_row)))]
            table_by_slot.add_row(*table_row)
        console.print(table_by_slot)
    elif print_format == PrintFormat.CSV:
        print(f"===== {title} =====\n")
        for table_row in table_rows:
            console.print(",".join(table_row + [""] * (num_columns - len(table_row))))


def run_matcher(
    section_preferences_file: str,
    section_config_file: str,
    oh_preferences_file: str,
    oh_config_file: str,
    matcher_config_file: str,
    # options
    verbose: bool = False,
    print_format: PrintFormat = PrintFormat.TABLE,
    print_colors: PrintColors = PrintColors.DISCRETE,
    print_empty: bool = False,
):
    """
    Run the matcher for discussions and OH on a given set of preference and config files.

    `section_preferences_file`:
        CSV file of discussion preferences.
    `section_config_file`:
        JSON file indicating how many sections each user can have,
        and how many users each section can have.
    `oh_preferences_file`:
        CSV file of OH preferences.
    `oh_config_file`:
        JSON file indicating how many OH each user can have,
        and how many users each OH slot can have.
    `matcher_config_file`:
        JSON file containing configuration options for the matcher.
    `verbose`:
        Whether to print verbose output for the optimizer.
    `print_format`:
        Print format for the assignments.
    `print_colors`:
        Print color map; either "discrete" if using preferences from (0, 1, 3, 5)
        or "gradient" otherwise
    """
    section_preference_map, section_info = parse_preferences(
        section_preferences_file, slot_id_prefix="A"
    )
    oh_preference_map, oh_info = parse_preferences(
        oh_preferences_file, slot_id_prefix="B"
    )

    section_counts, section_slot_counts = parse_config(
        section_config_file, slot_id_prefix="A"
    )
    oh_counts, oh_slot_counts = parse_config(oh_config_file, slot_id_prefix="B")

    matcher_config = parse_matcher_config(matcher_config_file)

    # ensure that the names in all files match up, if provided

    if section_preference_map:
        assert set(section_counts.keys()) == set(
            section_preference_map.keys()
        ), "Section config and preference files should share the same user names"
    if oh_preference_map:
        assert set(oh_counts.keys()) == set(
            oh_preference_map.keys()
        ), "OH config and preference files should share the same user names"

    # format input values
    section_users = [
        User(
            id=name,
            name=name,
            min_slots=section_counts[name][ConfigKeys.MIN_SLOTS],
            max_slots=section_counts[name][ConfigKeys.MAX_SLOTS],
        )
        for name in section_counts.keys()
    ]
    oh_users = [
        User(
            id=name,
            name=name,
            min_slots=oh_counts[name][ConfigKeys.MIN_SLOTS],
            max_slots=oh_counts[name][ConfigKeys.MAX_SLOTS],
        )
        for name in oh_counts.keys()
    ]

    section_slots = [
        Slot(
            id=slot_id,
            days=parse_days(slot_info[PreferencesHeader.DAY]),
            start_time=parse_time(slot_info[PreferencesHeader.START_TIME]),
            end_time=parse_time(slot_info[PreferencesHeader.END_TIME]),
            location=slot_info[PreferencesHeader.LOCATION],
            min_users=section_slot_counts[slot_id][ConfigKeys.MIN_USERS],
            max_users=section_slot_counts[slot_id][ConfigKeys.MAX_USERS],
        )
        for slot_id, slot_info in section_info.items()
    ]
    oh_slots = [
        Slot(
            id=slot_id,
            days=parse_days(slot_info[PreferencesHeader.DAY]),
            start_time=parse_time(slot_info[PreferencesHeader.START_TIME]),
            end_time=parse_time(slot_info[PreferencesHeader.END_TIME]),
            location=slot_info[PreferencesHeader.LOCATION],
            min_users=oh_slot_counts[slot_id][ConfigKeys.MIN_USERS],
            max_users=oh_slot_counts[slot_id][ConfigKeys.MAX_USERS],
        )
        for slot_id, slot_info in oh_info.items()
    ]

    section_preferences = [
        Preference(user_id=user_id, slot_id=slot_id, value=value)
        for user_id, preferences in section_preference_map.items()
        for slot_id, value in preferences.items()
    ]
    oh_preferences = [
        Preference(user_id=user_id, slot_id=slot_id, value=value)
        for user_id, preferences in oh_preference_map.items()
        for slot_id, value in preferences.items()
    ]

    # sort then shuffle, to avoid any discrepancies
    section_users.sort(key=lambda u: u.id)
    section_slots.sort(key=lambda s: s.id)
    section_preferences.sort(key=lambda p: (p.user_id, p.slot_id))
    oh_users.sort(key=lambda u: u.id)
    oh_slots.sort(key=lambda s: s.id)
    oh_preferences.sort(key=lambda p: (p.user_id, p.slot_id))

    random.shuffle(section_users)
    random.shuffle(section_slots)
    random.shuffle(section_preferences)
    random.shuffle(oh_users)
    random.shuffle(oh_slots)
    random.shuffle(oh_preferences)

    result = get_matches(
        section_users,
        section_slots,
        section_preferences,
        oh_users,
        oh_slots,
        oh_preferences,
        config=matcher_config,
        verbose=verbose,
    )

    print("cost", result.cost)

    # print by user
    if result.section_assignment:
        print_assignment_by_user(
            result.section_assignment,
            section_users,
            section_preference_map,
            title="Discussions",
            print_format=print_format,
            print_colors=print_colors,
            print_empty=print_empty,
        )
    if result.section_assignment and result.oh_assignment:
        print("\n")
    if result.oh_assignment:
        print_assignment_by_user(
            result.oh_assignment,
            oh_users,
            oh_preference_map,
            title="OH",
            print_format=print_format,
            print_colors=print_colors,
            print_empty=print_empty,
        )

    # spacing between ways of printing
    print("\n==========\n")

    if result.section_assignment:
        print_assignment_by_slot(
            result.section_assignment,
            section_slots,
            section_preference_map,
            title="Discussions",
            print_format=print_format,
            print_colors=print_colors,
            print_empty=print_empty,
        )
    if result.section_assignment and result.oh_assignment:
        print("\n")
    if result.oh_assignment:
        print_assignment_by_slot(
            result.oh_assignment,
            oh_slots,
            oh_preference_map,
            title="OH",
            print_format=print_format,
            print_colors=print_colors,
            print_empty=print_empty,
        )


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()

    file_group = parser.add_argument_group("Files")
    file_group.add_argument(
        "--section-preferences", help="Preferences CSV file for sections", default=""
    )
    file_group.add_argument(
        "--section-config", help="Configuration JSON file for sections", default=""
    )
    file_group.add_argument(
        "--oh-preferences", help="Preferences CSV file for OH", default=""
    )
    file_group.add_argument("--oh-config", help="Configuration for OH", default="")

    options_group = parser.add_argument_group("Options")
    options_group.add_argument("--seed", "-s", help="Random seed")
    options_group.add_argument(
        "--verbose", "-v", action="store_true", help="Verbose output"
    )
    options_group.add_argument(
        "--format",
        choices=[PrintFormat.TABLE, PrintFormat.CSV],
        default=PrintFormat.TABLE,
        help="Output format",
    )
    options_group.add_argument(
        "--colors",
        choices=["discrete", "gradient"],
        default="discrete",
        help="Print color format; use 'discrete' if choosing from (0, 1, 3, 5), and 'gradient' otherwise.",
    )
    options_group.add_argument(
        "--show-empty",
        action="store_true",
        help="Show slots in the resulting output even if they are not assigned to anything.",
    )
    options_group.add_argument(
        "--matcher-config", help="Config file for running the matcher", default=""
    )

    args = parser.parse_args()

    if args.seed:
        random.seed(int(args.seed))
        np.random.seed(int(args.seed))
        print("seed", args.seed)
    else:
        seed = random.randint(0, 2**16)
        random.seed(seed)
        np.random.seed(args.seed)
        print("seed", seed)

    run_matcher(
        args.section_preferences,
        args.section_config,
        args.oh_preferences,
        args.oh_config,
        args.matcher_config,
        verbose=args.verbose,
        print_format=args.format,
        print_colors=args.colors,
        print_empty=args.show_empty,
    )
