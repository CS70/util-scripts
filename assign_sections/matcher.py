import secrets
from dataclasses import dataclass
from datetime import datetime, time, timedelta
from itertools import groupby
from typing import Optional, cast

import cvxpy as cp

EPS = 1e-6

MAXIMIZE_FILLED_SLOTS_COEFF = 1000


@dataclass
class MatcherConfig:
    # default to more section bias, since generally it's more important
    section_bias: float = 0.75
    # whether to prefer filling all of the available slots
    maximize_filled_slots: bool = False


@dataclass
class User:
    id: str
    name: str
    min_slots: int = 1
    max_slots: int = 1


@dataclass
class Slot:
    id: str
    # list of days, where 0 = Monday, 6 = Sunday
    days: list[int]
    start_time: time
    end_time: time
    location: str
    min_users: int = 0
    max_users: int = 1


@dataclass
class Preference:
    user_id: str
    slot_id: str

    # nonnegative value; 0 = do not match, higher = more preferred
    value: int


@dataclass
class MatchResult:
    # map from user_id to a list of assigned slots
    section_assignment: dict[str, list[Slot]]
    oh_assignment: dict[str, list[Slot]]
    cost: float


_TIMESTAMP_START = "START"
_TIMESTAMP_END = "END"

NOW = datetime.now()

# Monday of the week
REFERENCE_DATETIME = NOW - timedelta(days=NOW.weekday())


def compute_slot_datetime(slot_day: int, slot_time: time):
    """
    Given an element in the `days` field and one of the `start_time`/`end_time` fields
    in a `Slot` object, compute the associated datetime.
    """
    reference_day = REFERENCE_DATETIME + timedelta(days=slot_day)
    return datetime.combine(reference_day.date(), slot_time)


def timestamps_from_slots(slots: list[Slot]) -> list[tuple[datetime, str, Slot]]:
    """
    Compute sorted timestamps (of start/end datetimes) from a list of slots.
    """
    timestamps = []
    for slot in slots:
        for day in slot.days:
            start_datetime = compute_slot_datetime(day, slot.start_time)
            end_datetime = compute_slot_datetime(day, slot.end_time)
            timestamps.append((start_datetime, _TIMESTAMP_START, slot))
            timestamps.append((end_datetime, _TIMESTAMP_END, slot))

    timestamps.sort(key=lambda t: t[0])
    return timestamps


def compute_conflicts(slots: list[Slot]):
    """
    Generator for all time conflicts within the given list of slots.
    """
    timestamps = timestamps_from_slots(slots)

    slots_by_id = {slot.id: slot for slot in slots}

    # ids of currently ongoing slots
    ongoing_slot_ids = set()
    for _, kind, slot in timestamps:
        if kind == _TIMESTAMP_END:
            ongoing_slot_ids.remove(slot.id)
        elif kind == _TIMESTAMP_START:
            yield from ((slots_by_id[id], slot) for id in ongoing_slot_ids)
            ongoing_slot_ids.add(slot.id)


def compute_cross_conflicts(slots1: list[Slot], slots2: list[Slot]):
    """
    Generator for all time conflicts across the two groups of slots.
    Yields tuples of the form (slot1, slot2), where the first slot comes from the first list,
    and the second slot comes from the second list.
    """
    # use helper, but add an identifier for which list of slots it came from
    timestamps1 = [
        (*timestamp[:2], 0, *timestamp[2:])
        for timestamp in timestamps_from_slots(slots1)
    ]
    timestamps2 = [
        (*timestamp[:2], 1, *timestamp[2:])
        for timestamp in timestamps_from_slots(slots2)
    ]
    timestamps = sorted([*timestamps1, *timestamps2], key=lambda t: t[0])

    slots_by_id = [
        {slot.id: slot for slot in slots1},
        {slot.id: slot for slot in slots2},
    ]

    ongoing_slot_ids = [set(), set()]
    for _, kind, idx, slot in timestamps:
        if kind == _TIMESTAMP_END:
            ongoing_slot_ids[idx].remove(slot.id)
        elif kind == _TIMESTAMP_START:
            # yield from the other set of ongoing slot ids
            if idx == 0:
                yield from ((slot, slots_by_id[1][id]) for id in ongoing_slot_ids[1])
            elif idx == 1:
                yield from ((slots_by_id[0][id], slot) for id in ongoing_slot_ids[0])

            ongoing_slot_ids[idx].add(slot.id)


def get_optimization(
    users: list[User],
    slots: list[Slot],
    preferences: list[Preference],
    maximize_filled_slots=True,
):
    """
    Compute the optimization objective and constraints for the given set of users and slots.
    """
    if len(slots) == 0 or len(preferences) == 0:
        return 0, [], {}

    # map from (user_id, slot_id) => preference
    preference_map = {}
    for preference in preferences:
        preference_map[(preference.user_id, preference.slot_id)] = preference.value

    # variables for assignments
    assignment = {}

    for user in users:
        for slot in slots:
            pref = preference_map.get((user.id, slot.id), 0)
            if pref <= 0:
                assignment[user.id, slot.id] = 0
            else:
                assignment[user.id, slot.id] = cp.Variable(
                    name=f"{user.id}/{slot.id}", boolean=True
                )

    constraints = []

    # enforce number of assignments for each user
    for user in users:
        user_sum = sum(assignment[user.id, slot.id] for slot in slots)
        constraints.extend(
            [
                user.min_slots <= user_sum,
                user_sum <= user.max_slots,
            ]
        )

    # enforce number of assignments for each slot
    for slot in slots:
        slot_sum = sum(assignment[user.id, slot.id] for user in users)
        constraints.extend(
            [
                slot.min_users <= slot_sum,
                slot_sum <= slot.max_users,
            ]
        )

    # enforce time conflicts
    for slot1, slot2 in compute_conflicts(slots):
        for user in users:
            constraints.append(
                assignment[user.id, slot1.id] + assignment[user.id, slot2.id] <= 1
            )

    # maximize the total preferences for each user
    objective = sum(
        preference_map[user_id, slot_id] * variable
        for (user_id, slot_id), variable in assignment.items()
    )

    if maximize_filled_slots:
        num_filled_slots = sum(v for v in assignment.values())
        objective += MAXIMIZE_FILLED_SLOTS_COEFF * num_filled_slots

    return objective, constraints, assignment


def get_cross_constraints(
    section_users: list[User],
    section_slots: list[Slot],
    section_assignment: dict[tuple[str, str], cp.Variable | float],
    oh_users: list[User],
    oh_slots: list[Slot],
    oh_assignment: dict[tuple[str, str], cp.Variable | float],
):
    """
    Compute the constraints across sections and OH slots.
    Enforces the fact that a single person cannot have section and OH at the same time.
    """

    if len(section_slots) == 0 or len(oh_slots) == 0:
        return []

    constraints = []

    section_user_ids = set(user.id for user in section_users)
    oh_user_ids = set(user.id for user in oh_users)

    # only look at intersection of two user groups
    applicable_users = section_user_ids.intersection(oh_user_ids)

    for section_slot, oh_slot in compute_cross_conflicts(section_slots, oh_slots):
        for user_id in applicable_users:
            constraints.append(
                section_assignment[user_id, section_slot.id]
                + oh_assignment[user_id, oh_slot.id]
                <= 1
            )

    return constraints


def get_matches(
    # section parameters
    section_users: list[User] = [],
    section_slots: list[Slot] = [],
    section_preferences: list[Preference] = [],
    # oh parameters
    oh_users: list[User] = [],
    oh_slots: list[Slot] = [],
    oh_preferences: list[Preference] = [],
    # config
    config: Optional[MatcherConfig] = None,
    verbose: bool = False,
) -> MatchResult:
    if config is None:
        # use default config if not provided
        config = MatcherConfig()

    section_objective, section_constraints, section_assignment = get_optimization(
        section_users,
        section_slots,
        section_preferences,
        maximize_filled_slots=config.maximize_filled_slots,
    )
    oh_objective, oh_constraints, oh_assignment = get_optimization(
        oh_users,
        oh_slots,
        oh_preferences,
        maximize_filled_slots=config.maximize_filled_slots,
    )

    cross_constraints = get_cross_constraints(
        section_users,
        section_slots,
        section_assignment,
        oh_users,
        oh_slots,
        oh_assignment,
    )

    problem = cp.Problem(
        cp.Maximize(
            # weighting between section and OH objectives
            config.section_bias * section_objective
            + (1 - config.section_bias) * oh_objective
        ),
        [*section_constraints, *oh_constraints, *cross_constraints],
    )

    problem.solve(verbose=verbose)

    final_section_assignment = {}
    final_oh_assignment = {}

    section_slots_by_id = {slot.id: slot for slot in section_slots}
    oh_slots_by_id = {slot.id: slot for slot in oh_slots}

    if section_slots and section_assignment:
        for user in section_users:
            matched_section_slot_ids = set()

            for slot in section_slots:
                assignment_obj = section_assignment[user.id, slot.id]
                if (
                    isinstance(assignment_obj, cp.Variable)
                    and assignment_obj.value > EPS
                ):
                    matched_section_slot_ids.add(slot.id)
            final_section_assignment[user.id] = [
                section_slots_by_id[slot_id] for slot_id in matched_section_slot_ids
            ]

    if oh_slots and oh_assignment:
        for user in oh_users:
            matched_oh_slot_ids = set()
            for slot in oh_slots:
                assignment_obj = oh_assignment[user.id, slot.id]
                if (
                    isinstance(assignment_obj, cp.Variable)
                    and assignment_obj.value > EPS
                ):
                    matched_oh_slot_ids.add(slot.id)
            final_oh_assignment[user.id] = [
                oh_slots_by_id[slot_id] for slot_id in matched_oh_slot_ids
            ]

    # cast into float
    cost = float(cast(float, problem.value))

    return MatchResult(
        section_assignment=final_section_assignment,
        oh_assignment=final_oh_assignment,
        cost=cost,
    )
