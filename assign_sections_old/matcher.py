from dataclasses import dataclass
from typing import List

import networkx as nx


class MatcherValidationError(BaseException):
    pass


@dataclass
class Mentor:
    id: int
    name: str
    min_slots: int = 1
    max_slots: int = 1


@dataclass
class Slot:
    id: int
    time: str
    location: str = None
    min_mentors: int = 0
    max_mentors: int = 1


@dataclass
class Preference:
    mentor_id: int
    slot_id: int
    value: int


SOURCE = "SOURCE"
SINK = "SINK"
DUMMY_SLOT = "DUMMY_SLOT"

UNMATCHABLE_EDGE_WEIGHT = 1e6


def weight_func(preference: int) -> int:
    """
    Weight function to map from preference to weight.

    Larger preference values are more wanted, but the algorithm optimizes for smaller weight,
    so this function maps large preference values to small (nonnegative) weight values.
    """
    if preference == 0:
        return UNMATCHABLE_EDGE_WEIGHT
    return round(1 / preference * 100, 0)


def get_matches(
    mentors: List[Mentor], slots: List[Slot], preferences: List[Preference]
):
    """
    Match each mentor with `mentor.num_slots` slots.
    Each slot must be associated with at least `min_mentors` and at most `max_mentors` mentors.

    Creates a graph to run min-cost max-flow:
    - Layer 0: Source
        - supply equal to the number of sections that need to be assigned
    - Layer 1: Mentors
        - 0 cost from the source
        - capacity from the source equal to the number of sections for this mentor
    - Layer 2: Slots (time slots)
        - cost from the mentor inversely proportional to the preference
        - capacity 1 from the mentor
    - Layer 3: Slots (locations)
        - 0 cost from the time slot
        - capacity max_mentors from the time slot
    - Layer 4: Sink
        - 0 cost from the location slot

    Because of the way time slots/locations are laid out, this does mean that when
    multiple mentors get assigned to the same time slot (but different locations),
    it is ambiguous who is assigned exactly to which location.

    This means that we need to run another min-cost max-flow on each set of collisions,
    taking only the locations that have actually received any flow.
    This new graph contains the following layers:
    - Layer 0: Source
        - supply equal to the amount of flow into the time slot node previously
    - Layer 1: Mentors in collision
        - cost 0 from the source
    - Layer 2: Slots (locations) in collision
        - cost from the mentor inversely proportional to the preference
        - capacity 1 from the mentor
        - demand equal to the minimum number of mentors that must be assigned to this slot
    - Layer 3: Sink
        - capacity from slot equal to the out flow from the location node previously

    This will give a final assignment from mentors to slots for the collision.

    Returns a dictionary containing:
    - cost: Cost of the flow
    - assignments: An assignment from mentor IDs to sets of slot IDs
    - unmatched: A list of unmatched mentors
    """

    # total number of slots that can be matched
    total_min_slots = sum(slot.min_mentors for slot in slots)
    total_max_slots = sum(slot.max_mentors for slot in slots)

    # total number of mentors that can be matched
    total_max_mentors = sum(mentor.max_slots for mentor in mentors)

    # validate capacities
    if total_min_slots > total_max_slots:
        raise MatcherValidationError(
            "Total minimum slot capacities are greater than total maximum slot capacities."
        )
    # validate number of slots
    if total_min_slots > total_max_mentors:
        raise MatcherValidationError("Not enough mentors to fulfill slot requirements.")
    # okay to have more mentors than slots; taken care of later

    graph = nx.DiGraph()
    graph.add_node(SOURCE, demand=-total_max_mentors, subset="source")
    graph.add_node(SINK, demand=total_max_mentors - total_min_slots, subset="sink")
    # add mentor nodes and edges from source
    for mentor in mentors:
        graph.add_node(mentor.id, demand=0, subset="mentor")
        graph.add_edge(
            SOURCE,
            mentor.id,
            # no cost
            weight=0,
            # capacity equal to the number of sections assigned to the mentor
            capacity=mentor.max_slots,
        )
    # add slot nodes and edges to sink
    id_to_slot = {}
    for slot in slots:
        if slot.min_mentors > slot.max_mentors:
            raise MatcherValidationError(
                "Minimum slot capacity is greater than maximum slot capacity."
            )
        id_to_slot[slot.id] = slot

        # divide into two parts; one for time and one for location

        if slot.time not in graph:
            # time component; add if not present already
            graph.add_node(slot.time, demand=0, subset="slot_time")

        # MUST have at least `min_mentors` flow through this node
        # this means that this node consumes some flow
        graph.add_node(slot.id, demand=slot.min_mentors, subset="slot_location")
        graph.add_edge(
            slot.time,
            slot.id,
            # no cost
            weight=0,
            # no defined capacity here; restrictions are applied on the way out of the location node
            capacity=slot.max_mentors,
        )
        graph.add_edge(
            slot.id,
            SINK,
            # no cost
            weight=0,
            # `min_mentors` consumed, so `max_mentors - min_mentors` left
            capacity=slot.max_mentors - slot.min_mentors,
        )

    # create edges from mentor nodes to slot nodes
    preference_map = {}
    for pref in preferences:
        slot_time = id_to_slot[pref.slot_id].time
        pref_weight = weight_func(pref.value)
        if (pref.mentor_id, slot_time) in graph.edges:
            existing_weight = graph[pref.mentor_id][slot_time]["weight"]
            # if the edge is present already, only update it if we have a higher preference
            # (i.e. a lower weight)
            if existing_weight > pref_weight:
                graph.add_edge(
                    pref.mentor_id, slot_time, weight=pref_weight, capacity=1
                )
        else:
            graph.add_edge(
                pref.mentor_id,
                slot_time,
                # cost inversely proportional to the preference number
                weight=pref_weight,
                # each pair of (mentor, slot) can only be populated by one flow
                # this prevents the same mentor from being assigned to the same slot
                # multiple times
                capacity=1,
            )

        # build a map of preferences for ease of access later
        if pref.mentor_id not in preference_map:
            preference_map[pref.mentor_id] = {}
        preference_map[pref.mentor_id][pref.slot_id] = pref.value

    # if more mentors than slots, add a dummy slot with infinite capacity,
    # with edges from all mentors to this slot with UNMATCHABLE_EDGE_WEIGHT cost.
    # this allows for mentors to be forcefully unmatched while still having a valid flow.
    if total_max_slots < total_max_mentors:
        max_sections = max(mentor.max_slots for mentor in mentors)
        for num_removed in range(1, max_sections):
            # dummy slot when unmatching for the nth time
            graph.add_node(f"{DUMMY_SLOT}-{num_removed}", subset="slot_dummy")
            graph.add_edge(f"{DUMMY_SLOT}-{num_removed}", SINK, weight=0)

        for mentor in mentors:
            if mentor.max_slots > 1:
                # only allow unmatched if more than 1
                for num_removed in range(1, mentor.max_slots - mentor.min_slots + 1):
                    # only allow to unmatch until there is 1 left
                    graph.add_edge(
                        mentor.id,
                        f"{DUMMY_SLOT}-{num_removed}",
                        # matching this slot is equivalent to being unmatched
                        # this value scales as more are unmatched
                        weight=UNMATCHABLE_EDGE_WEIGHT * num_removed,
                        capacity=1,
                    )

    # flow_dict[u][v] is the amount of flow from u to v
    flow_cost, flow_dict = nx.network_simplex(graph)
    unmatched_mentors = set(mentor.id for mentor in mentors)
    assignments = {}

    # scan for collisions
    collisions = {}
    for mentor in mentors:
        out_flows = flow_dict[mentor.id]
        for time, flow_amt in out_flows.items():
            if (
                # no flow
                flow_amt == 0
                # unmatched
                or graph[mentor.id][time]["weight"] >= UNMATCHABLE_EDGE_WEIGHT
            ):
                continue

            if (
                # only one possibility
                len(flow_dict[time]) == 1
                # multiple possibilities, but only one output flow from this node
                or sum(location_flow for location_flow in flow_dict[time].values()) == 1
            ):
                # get the only location possibility
                location_id = None
                for cur_location in flow_dict[time]:
                    if flow_dict[time][cur_location] > 0:
                        location_id = cur_location
                        break
                assert location_id is not None

                # set the assignment
                if mentor.id not in assignments:
                    assignments[mentor.id] = set()
                assignments[mentor.id].add(location_id)
                if mentor.id in unmatched_mentors:
                    unmatched_mentors.remove(mentor.id)
                continue

            # multiple possibilities, and multiple output flows from this node;
            # keep track of it as a collision
            if time not in collisions:
                collisions[time] = {
                    "mentors": [],
                    # compute all slots involved with some flow
                    "slots": [
                        id_to_slot[slot_id]
                        for (slot_id, amt) in flow_dict[time].items()
                        if amt > 0
                    ],
                    "in_flow": {},
                }
            collisions[time]["mentors"].append(mentor)
            collisions[time]["in_flow"][mentor.id] = flow_amt

    # for each collision, run another round of min-cost max-flow
    for collision in collisions.values():
        collision_in_flow = sum(collision["in_flow"].values())
        collision_min_mentors = sum(slot.min_mentors for slot in collision["slots"])

        collision_graph = nx.DiGraph()
        collision_graph.add_node(
            SOURCE,
            # supplies the sum of all max_slots for each mentor;
            # gives the opportunity to match all mentors the maximum number of times
            demand=-collision_in_flow,
            subset="source",
        )
        collision_graph.add_node(
            SINK,
            # slot nodes consume in total collision_min_mentors,
            # so the remainder is consumed by the sink
            demand=collision_in_flow - collision_min_mentors,
            subset="sink",
        )

        for mentor in collision["mentors"]:
            collision_graph.add_node(mentor.id, subset="mentor")
            collision_graph.add_edge(
                SOURCE,
                mentor.id,
                # no weight
                weight=0,
                # capacity equal to the max number of slots that can be assigned to this mentor
                capacity=collision["in_flow"][mentor.id],
            )
        for slot in collision["slots"]:
            collision_graph.add_node(slot.id, demand=slot.min_mentors, subset="slot")
            collision_graph.add_edge(
                slot.id,
                SINK,
                # no weight
                weight=0,
                # node consumes min_mentors demand, so max_mentors - min_mentors left
                capacity=slot.max_mentors - slot.min_mentors,
            )
        for mentor in collision["mentors"]:
            for slot in collision["slots"]:
                pref = preference_map[mentor.id][slot.id]
                # negate preference since it's a minimum weight full matching
                collision_graph.add_edge(
                    mentor.id,
                    slot.id,
                    # weight inversely proportional to the preference
                    weight=weight_func(pref),
                    # capacity 1, since each mentor cannot have multiple assignments in the same time slot
                    capacity=1,
                )

        _, collision_flow_dict = nx.network_simplex(collision_graph)
        # store assignment
        for mentor in collision["mentors"]:
            if mentor.id not in assignments:
                assignments[mentor.id] = set()
            for time, flow_val in collision_flow_dict[mentor.id].items():
                if flow_val > 0:
                    # save assignment
                    assignments[mentor.id].add(time)

            # mark mentor as matched
            if mentor.id in unmatched_mentors:
                unmatched_mentors.remove(mentor.id)

    unmatched_mentors = sorted(unmatched_mentors)
    return {
        "cost": flow_cost,
        "assignments": assignments,
        "unmatched": unmatched_mentors,
    }
