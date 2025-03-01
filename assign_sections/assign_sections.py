import random
from pprint import pprint
from typing import Optional

import cvxpy as cp
import matplotlib
import matplotlib.colors
import numpy as np
from rich.console import Console
from rich.table import Table, box
from rich.theme import Theme

from matcher_utils.format import format_days, format_slot, format_time
from matcher_utils.input_config import (
    ConfigKeys,
    PreferencesHeader,
    PrintColors,
    PrintFormat,
)
from matcher_utils.matcher import (
    Assignment,
    Preference,
    Slot,
    User,
    compute_slot_datetime,
    get_matches,
)
from matcher_utils.parse import (
    parse_config,
    parse_days,
    parse_matcher_config,
    parse_oh_preset_assignment,
    parse_preferences,
    parse_section_preset_assignment,
    parse_time,
)
from matcher_utils.types import (
    PresetAssignmentInfo,
    SlotConfigMap,
    UserConfigMap,
    UserPreferenceMap,
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


def compute_color(
    pref, min_pref, max_pref, print_colors: str = PrintColors.DISCRETE
) -> str:
    """
    Compute the associated `rich` color style based on a preference and a preference range.
    """
    if print_colors == PrintColors.DISCRETE:
        if pref in COLOR_MAP_DISCRETE:
            return COLOR_MAP_DISCRETE[pref]
        return "normal"

    # for gradients, we need to compute the color from the color map
    scaled_pref = (pref - min_pref) / (max_pref - min_pref)
    color = COLOR_MAP_GRADIENT(scaled_pref)
    hex_color = matplotlib.colors.rgb2hex(color)
    hsv_color = matplotlib.colors.rgb_to_hsv(color[:3])

    text_color = "white" if hsv_color[2] < 0.5 else "black"
    return f"{text_color} on {hex_color}"


def print_assignment_by_user(
    assignment: dict[str, list[Slot]],
    users: list[User],
    preference_map: dict[str, dict[str, int]],
    title: str = "",
    print_format: str = PrintFormat.TABLE,
    print_colors: str = PrintColors.DISCRETE,
    print_empty: bool = False,
) -> None:
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
    print_format: str = PrintFormat.TABLE,
    print_colors: str = PrintColors.DISCRETE,
    print_empty: bool = False,
) -> None:
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


def generate_preset_assignment(
    preset_assignment_info: list[PresetAssignmentInfo],
    users: list[User],
    slots: list[Slot],
    force_unmatched: bool = False,
) -> Assignment:
    """
    Generate a dictionary mapping user/slot IDs to booleans,
    representing the given preset assignment.

    If the `force_unmatched` option is True,
    all user/slot pairs not given in the preset assignment are forcefully unmatched.
    If the `force_unmatched` option is False,
    only the given assignments are added as constraints,
    leaving the possibility for additional assignments as well.
    """
    if not preset_assignment_info:
        # if no assignment info is given, return an empty assignment
        return {}

    users_by_name = {user.name: user for user in users}
    slots_by_time_location = {
        (
            format_days(slot.days),
            slot.start_time.isoformat(),
            slot.end_time.isoformat(),
            slot.location,
        ): slot
        for slot in slots
    }

    assignment = {}
    for info in preset_assignment_info:
        cur_user = users_by_name.get(info.name, None)
        if cur_user is None:
            raise ValueError(
                f"User with name '{info.name}' not found in preset assignment"
            )

        formatted_days = format_days(info.days)
        cur_slot = slots_by_time_location.get(
            (
                format_days(info.days),
                info.start_time.isoformat(),
                info.end_time.isoformat(),
                info.location,
            ),
            None,
        )
        if cur_slot is None:
            raise ValueError(
                f"Slot '{formatted_days} {info.start_time}—{info.end_time} @ {info.location}'"
                " not found in preset assignment"
            )

        assignment[(cur_user.id, cur_slot.id)] = True

    if force_unmatched:
        # set all other pairs to False
        for user in users:
            for slot in slots:
                if (user.id, slot.id) not in assignment:
                    assignment[(user.id, slot.id)] = False

    return assignment


def validate_inputs(
    section_preference_map: UserPreferenceMap,
    section_counts: UserConfigMap,
    section_slot_counts: SlotConfigMap,
    oh_preference_map: UserPreferenceMap,
    oh_counts: UserConfigMap,
    oh_slot_counts: SlotConfigMap,
):
    """
    Validate all inputs, after parsing.

    Raises an error if any validation errors occur,
    otherwise does nothing.
    """

    # ensure that the names in all files match up, if provided
    if section_preference_map:
        assert set(section_counts.keys()) == set(
            section_preference_map.keys()
        ), "Section config and preference files should share the same user names"
    if oh_preference_map:
        assert set(oh_counts.keys()) == set(
            oh_preference_map.keys()
        ), "OH config and preference files should share the same user names"

    # ensure that min/max counts are feasible
    for user_counts, slot_counts, label in (
        (section_counts, section_slot_counts, "section"),
        (oh_counts, oh_slot_counts, "oh"),
    ):
        total_min_user_counts = sum(
            count["min_slots"] for count in user_counts.values()
        )
        total_max_user_counts = sum(
            count["max_slots"] for count in user_counts.values()
        )

        total_min_slot_counts = sum(
            count["min_users"] for count in slot_counts.values()
        )
        total_max_slot_counts = sum(
            count["max_users"] for count in slot_counts.values()
        )

        assert total_min_user_counts <= total_max_slot_counts, (
            f"[{label}]"
            f" Minimum total count for users ({total_min_user_counts})"
            f" must be at most the maximum total count for slots ({total_max_slot_counts});"
            " either increase the maximums for each slot, or decrease the minimums for each user"
        )
        assert total_min_slot_counts <= total_max_user_counts, (
            f"[{label}]"
            f" Minimum total count for slots ({total_min_slot_counts})"
            f" must be at most the maximum total count for users ({total_max_user_counts});"
            " either increase the maximums for each user, or decrease the minimums for each slot"
        )


def run_matcher(
    section_preferences_file: Optional[str],
    section_config_file: Optional[str],
    oh_preferences_file: Optional[str],
    oh_config_file: Optional[str],
    matcher_config_file: Optional[str],
    # preset assignments
    section_preset_assignment_file: Optional[str],
    oh_preset_assignment_file: Optional[str],
    # options
    verbose: bool = False,
    solver: str = cp.SCIPY,
    print_format: str = PrintFormat.TABLE,
    print_colors: str = PrintColors.DISCRETE,
    print_empty: bool = False,
    preset_force_unmatched: bool = False,
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

    section_preset_assignment_info = parse_section_preset_assignment(
        section_preset_assignment_file
    )
    oh_preset_assignment_info = parse_oh_preset_assignment(oh_preset_assignment_file)

    validate_inputs(
        section_preference_map,
        section_counts,
        section_slot_counts,
        oh_preference_map,
        oh_counts,
        oh_slot_counts,
    )

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

    section_preset_assignment = generate_preset_assignment(
        section_preset_assignment_info,
        section_users,
        section_slots,
        force_unmatched=preset_force_unmatched,
    )
    oh_preset_assignment = generate_preset_assignment(
        oh_preset_assignment_info,
        oh_users,
        oh_slots,
        force_unmatched=preset_force_unmatched,
    )

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
        section_preset_assignment=section_preset_assignment,
        oh_preset_assignment=oh_preset_assignment,
        config=matcher_config,
        verbose=verbose,
        solver=solver,
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
    file_group.add_argument(
        "--section-preset-assignment",
        help=(
            "CSV file for a preset section assignment;"
            " taken into account when computing OH assignments"
        ),
        default="",
    )
    file_group.add_argument(
        "--oh-preset-assignment",
        help=(
            "CSV file for a preset OH assignment;"
            " taken into account when computing section assignments"
        ),
        default="",
    )

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
        choices=[PrintColors.DISCRETE, PrintColors.GRADIENT],
        default=PrintColors.DISCRETE,
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
    options_group.add_argument(
        "--preset-assignment-force-unmatched",
        action="store_true",
        help="When a preset assignment is passed in, ensure all other pairs of users/slots are forcefully unmatched.",
    )

    options_group.add_argument(
        "--solver",
        default=cp.SCIPY,
        choices=cp.installed_solvers(),
        help="Solver to use for the ILP optimization problem",
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
        args.section_preset_assignment,
        args.oh_preset_assignment,
        verbose=args.verbose,
        solver=args.solver,
        print_format=args.format,
        print_colors=args.colors,
        print_empty=args.show_empty,
        preset_force_unmatched=args.preset_assignment_force_unmatched,
    )
