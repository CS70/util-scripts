from dataclasses import dataclass
from datetime import datetime, time, timedelta
from itertools import combinations
from typing import Literal, Optional, Type, TypeVar, Union, cast

import cvxpy as cp

EPS = 1e-6

MatcherConfigClass = TypeVar("MatcherConfigClass", bound="MatcherConfig")


@dataclass
class MatcherConfig:
    # default to more section bias, since generally it's more important
    section_bias: float = 0.75

    # whether to prefer filling all of the available slots
    maximize_filled_slots: bool = False
    # weight for the bonus for maximizing filled slots
    maximize_filled_slots_weight: float = 1000

    # whether to give a bonus for consecutive slots
    consecutive_bonus: bool = True
    # weight to give to the consecutive bonus
    consecutive_bonus_weight: float = 0.75

    # whether to give a bonus for globally consecutive slots (regardless of the user);
    # can be applied to sections, OH, both, or neither.
    global_consecutive_bonus: Union[
        None, Literal["section"], Literal["oh"], Literal["all"]
    ] = "oh"
    # weight to give to the global consecutive bonus
    global_consecutive_bonus_weight: float = 1

    # whether to give a bonus for the same time slot across different days
    same_time_bonus: bool = True
    # weight to give to the same time bonus
    same_time_bonus_weight: float = 0.1

    @classmethod
    def from_dict(cls: Type[MatcherConfigClass], config: dict) -> MatcherConfigClass:
        """Create a MatcherConfig instance from a dict."""
        matcher_config = cls()

        if "section_bias" in config:
            matcher_config.section_bias = float(config["section_bias"])
            assert 0 <= matcher_config.section_bias <= 1

        if "maximize_filled_slots" in config:
            matcher_config.maximize_filled_slots = bool(config["maximize_filled_slots"])
        if "maximize_filled_slots_weight" in config:
            matcher_config.maximize_filled_slots_weight = float(
                config["maximize_filled_slots_weight"]
            )

        if "consecutive_bonus" in config:
            matcher_config.consecutive_bonus = bool(config["consecutive_bonus"])
        if "consecutive_bonus_weight" in config:
            matcher_config.consecutive_bonus_weight = float(
                config["consecutive_bonus_weight"]
            )

        if "global_consecutive_bonus" in config:
            matcher_config.global_consecutive_bonus = config["global_consecutive_bonus"]
            assert matcher_config.global_consecutive_bonus in (
                None,
                "section",
                "oh",
                "all",
            )
        if "global_consecutive_bonus_weight" in config:
            matcher_config.global_consecutive_bonus_weight = float(
                config["global_consecutive_bonus_weight"]
            )

        if "same_time_bonus" in config:
            matcher_config.same_time_bonus = bool(config["same_time_bonus"])
        if "same_time_bonus_weight" in config:
            matcher_config.same_time_bonus_weight = float(
                config["same_time_bonus_weight"]
            )

        return matcher_config


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


VariableMap = dict[tuple[str, str], cp.Variable | cp.Constant]


_TIMESTAMP_START = "START"
_TIMESTAMP_END = "END"

# arbitrary day in the middle of a month in the middle of a eyar
REFERENCE_DATETIME = datetime(
    year=2000, month=6, day=15, hour=0, minute=0, second=0, microsecond=0
)

# set to Monday of the week
REFERENCE_DATETIME = REFERENCE_DATETIME - timedelta(days=REFERENCE_DATETIME.weekday())


def linear_and(
    var1: Union[cp.Variable, cp.Constant], var2: Union[cp.Variable, cp.Constant]
) -> tuple[cp.Expression, list[cp.Constraint]]:
    """
    Compute the AND of two binary variables, linearized with an extra variable.

    Returns (result, constraints):
        - `result` is the value of the AND expression (as a new variable)
        - `constraints` are the additional constraints necessary for the optimization problem
    """
    if not isinstance(var1, cp.Variable) or not isinstance(var2, cp.Variable):
        return var1 * var2, []

    and_var = cp.Variable(name=f"{var1}&{var2}", boolean=True)

    return and_var, [and_var <= var1, and_var <= var2, and_var >= var1 + var2 - 1]


def linear_or(
    variables: list[Union[cp.Variable, cp.Constant]]
) -> tuple[cp.Variable, list[cp.Constraint]]:
    """
    Compute the OR of a list of binary variables, linearized with an extra variable.

    Returns (result, constraints):
        - `result` is the value of the OR expression
        - `constraints` are the additional constraints necessary for the optimization problem
    """

    variable_names = [str(v) for v in variables]
    or_var = cp.Variable(name=f"{'|'.join(variable_names)}", boolean=True)
    return or_var, [or_var >= var for var in variables]


def compute_slot_datetime(slot_day: int, slot_time: time):
    """
    Given an element in the `days` field and one of the `start_time`/`end_time` fields
    in a `Slot` object, compute the associated datetime.
    """
    reference_day = REFERENCE_DATETIME + timedelta(days=slot_day)
    return datetime.combine(reference_day.date(), slot_time)


def is_consecutive(slot1: Slot, slot2: Slot, tol=timedelta(minutes=1)):
    """
    Determine whether `slot1` comes immediately before `slot2` (or vice versa),
    up to some tolerance `tol`.
    """
    slot1_days = set(slot1.days)
    slot2_days = set(slot2.days)
    days_intersect = slot1_days.intersection(slot2_days)

    # in order to be consecutive, both slots must overlap in the days
    if not days_intersect:
        return False

    # on one of the intersection days, compare the datetimes
    day = list(days_intersect)[0]
    slot1_start = compute_slot_datetime(day, slot1.start_time)
    slot1_end = compute_slot_datetime(day, slot1.end_time)
    slot2_start = compute_slot_datetime(day, slot2.start_time)
    slot2_end = compute_slot_datetime(day, slot2.end_time)

    # difference must be within tolerance
    return abs(slot1_end - slot2_start) <= tol or abs(slot2_end - slot1_start) <= tol


def is_same_time(slot1: Slot, slot2: Slot, tol=timedelta(minutes=1)):
    """
    Determine whether `slot1` and `slot2` occur on different days but the same times,
    up to some tolerance `tol`.
    """
    slot1_days = set(slot1.days)
    slot2_days = set(slot2.days)
    days_intersect = slot1_days.intersection(slot2_days)

    # slots cannot share any days, otherwise they'd overlap if they occurred at the same time
    if days_intersect:
        return False

    day = slot1.days[0]
    slot1_start = compute_slot_datetime(day, slot1.start_time)
    slot1_end = compute_slot_datetime(day, slot1.end_time)
    slot2_start = compute_slot_datetime(day, slot2.start_time)
    slot2_end = compute_slot_datetime(day, slot2.end_time)

    # difference must be within tolerance
    return abs(slot1_start - slot2_start) <= tol and abs(slot1_end - slot2_end) <= tol


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
            yield from ((slots_by_id[id], slot) for id in sorted(ongoing_slot_ids))
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
                yield from ((slot, slots_by_id[1][id]) for id in sorted(ongoing_slot_ids[1]))
            elif idx == 1:
                yield from ((slots_by_id[0][id], slot) for id in sorted(ongoing_slot_ids[0]))

            ongoing_slot_ids[idx].add(slot.id)


def get_optimization(
    users: list[User],
    slots: list[Slot],
    preferences: list[Preference],
    config: MatcherConfig,
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
                assignment[user.id, slot.id] = cp.Constant(0)
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

    # add a bonus for maximizing filled slots
    if config.maximize_filled_slots:
        num_filled_slots = sum(v for v in assignment.values())
        objective += config.maximize_filled_slots_weight * num_filled_slots

    # add a bonus for assigning consecutive slots
    if config.consecutive_bonus:
        consecutive_bonus = 0
        consecutive_constraints = []
        for slot1, slot2 in combinations(slots, 2):
            if is_consecutive(slot1, slot2):
                for user in users:
                    slot1_var = assignment[user.id, slot1.id]
                    slot2_var = assignment[user.id, slot2.id]

                    and_result, and_constraints = linear_and(slot1_var, slot2_var)
                    consecutive_bonus += and_result
                    consecutive_constraints.extend(and_constraints)

        objective += config.consecutive_bonus_weight * consecutive_bonus
        constraints.extend(consecutive_constraints)

    # add a bonus for assigning slots at the same time but on different days
    if config.same_time_bonus:
        same_time_bonus = 0
        same_time_constraints = []
        for slot1, slot2 in combinations(slots, 2):
            if is_same_time(slot1, slot2):
                for user in users:
                    slot1_var = assignment[user.id, slot1.id]
                    slot2_var = assignment[user.id, slot2.id]

                    and_result, and_constraints = linear_and(slot1_var, slot2_var)
                    same_time_bonus += and_result
                    same_time_constraints.extend(and_constraints)

        objective += config.same_time_bonus_weight * same_time_bonus
        constraints.extend(same_time_constraints)

    return objective, constraints, assignment


def get_cross_constraints(
    section_users: list[User],
    section_slots: list[Slot],
    section_assignment: VariableMap,
    oh_users: list[User],
    oh_slots: list[Slot],
    oh_assignment: VariableMap,
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
    applicable_users = sorted(section_user_ids.intersection(oh_user_ids))

    for section_slot, oh_slot in compute_cross_conflicts(section_slots, oh_slots):
        for user_id in applicable_users:
            constraints.append(
                section_assignment[user_id, section_slot.id]
                + oh_assignment[user_id, oh_slot.id]
                <= 1
            )

    return constraints


def get_global_consecutive_bonus(
    users: list[User], slots: list[Slot], assignment: VariableMap, config: MatcherConfig
) -> tuple[cp.Expression, list[cp.Constraint]]:
    """
    Compute the objective function bonus along with any extra constraints
    corresponding to a global consecutive bonus.

    In particular, this function rewards assignments that are consecutive within a given day,
    across all users.
    """

    bonus = cp.Constant(0)
    constraints: list[cp.Constraint] = []
    for slot1, slot2 in combinations(slots, 2):
        if is_consecutive(slot1, slot2):
            # take the OR across each slot
            slot1_or, slot1_or_constraints = linear_or(
                [assignment[user.id, slot1.id] for user in users]
            )
            slot2_or, slot2_or_constraints = linear_or(
                [assignment[user.id, slot2.id] for user in users]
            )
            constraints.extend(slot1_or_constraints)
            constraints.extend(slot2_or_constraints)

            # then take the AND between these two slots
            and_var, and_constraints = linear_and(slot1_or, slot2_or)

            bonus += and_var
            constraints.extend(and_constraints)

    return config.global_consecutive_bonus_weight * bonus, constraints


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
    solver: str = cp.SCIPY,
) -> MatchResult:
    if config is None:
        # use default config if not provided
        config = MatcherConfig()

    section_objective, section_constraints, section_assignment = get_optimization(
        section_users, section_slots, section_preferences, config=config
    )
    oh_objective, oh_constraints, oh_assignment = get_optimization(
        oh_users, oh_slots, oh_preferences, config=config
    )

    cross_constraints = get_cross_constraints(
        section_users,
        section_slots,
        section_assignment,
        oh_users,
        oh_slots,
        oh_assignment,
    )

    # weighting between section and OH objectives
    objective = (
        config.section_bias * section_objective
        + (1 - config.section_bias) * oh_objective
    )
    constraints = [*section_constraints, *oh_constraints, *cross_constraints]

    # additions to the objective/constraints

    if config.global_consecutive_bonus in ("section", "all"):
        bonus_objective, bonus_constraints = get_global_consecutive_bonus(
            section_users, section_slots, section_assignment, config=config
        )
        objective += bonus_objective
        constraints.extend(bonus_constraints)

    if config.global_consecutive_bonus in ("oh", "all"):
        bonus_objective, bonus_constraints = get_global_consecutive_bonus(
            oh_users, oh_slots, oh_assignment, config=config
        )
        objective += bonus_objective
        constraints.extend(bonus_constraints)

    # set up and solve optimization problem
    problem = cp.Problem(cp.Maximize(objective), constraints)
    problem.solve(verbose=verbose, solver=solver)

    if problem.status != "optimal":
        # could not solve problem; raise error
        raise RuntimeError(
            f"Optimization problem could not be solved: status {problem.status}"
        )

    # fetch and store the final assignment
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
