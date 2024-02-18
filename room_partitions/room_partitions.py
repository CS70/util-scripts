"""
Partitions a list of students into rooms based on alphabetical order by last name,
without exceeding the room capacities.

The algorithm greedily expands the room capacities by 1 until a valid solution is found.
This isn't the most efficient algorithm, but since the number of rooms is small, it's good enough.
"""

from collections import Counter
from csv import DictReader
from itertools import permutations, product
from string import ascii_uppercase
from typing import Union

NAME_COLUMN = "Name"
ROOM_NAME_COLUMN = "Room"
ROOM_CAPACITY_COLUMN = "Capacity"
PREFIX_LENGTH = 1


def main(
    csv_file: str,
    capacity_file: str,
    scale: float = 1,
    sort: str = "avg",
    limit: int = -1,
    no_single_prefix: bool = False,
):
    """
    Partition a list of students into rooms based on alphabetical order by last name,
    without exceeding the room capacities.

    :param csv_file: The path to the CSV file containing the student data.
    :param room_capacities: A list of room capacities.
    :param scale: The scale for room capacities during preprocessing;
        all capacities will be multiplied by this value before the algorithm runs.
    """
    # read name csv file
    with open(csv_file, "r", encoding="utf-8") as student_csv:
        reader = DictReader(student_csv)
        assert (
            NAME_COLUMN in reader.fieldnames
        ), f"Student CSV must have column {NAME_COLUMN}"
        students = [row[NAME_COLUMN] for row in reader]

    # read room csv file
    with open(capacity_file, "r", encoding="utf-8") as room_csv:
        reader = DictReader(room_csv)
        assert (
            ROOM_NAME_COLUMN in reader.fieldnames
        ), f"Room CSV must have column {ROOM_NAME_COLUMN}"
        assert (
            ROOM_CAPACITY_COLUMN in reader.fieldnames
        ), f"Room CSV must have column {ROOM_CAPACITY_COLUMN}"
        capacities = {
            row[ROOM_NAME_COLUMN]: int(int(row[ROOM_CAPACITY_COLUMN]) * scale)
            for row in reader
        }

    # sort students by last name
    students.sort()

    # get counts of each initial last name letter
    counts = Counter([student[:PREFIX_LENGTH].upper() for student in students])

    solutions = []
    extra_capacity = 0
    all_rooms = list(capacities.keys())

    while not solutions:
        # brute force all possible orderings of rooms
        rooms_to_permute = [room for room, capacity in capacities.items() if capacity > 0]
        empty_rooms = [room for room, capacity in capacities.items() if capacity == 0]
        for room_order in permutations(rooms_to_permute):
            filled_rooms = {room: 0 for room in all_rooms}
            room_ranges: dict[str, dict[str, Union[str, None]]] = {
                # put empty rooms at the end, keep other room order
                room: {"start": None, "end": None} for room in [*room_order, *empty_rooms]
            }
            cur_room_idx = 0
            # set first room start
            room_ranges[room_order[0]]["start"] = "A" * PREFIX_LENGTH

            # iterate over letters
            for letters in product(ascii_uppercase, repeat=PREFIX_LENGTH):
                prefix = "".join(letters)
                # if there are no students with this letter, skip
                if counts[prefix] == 0:
                    continue

                cur_room = room_order[cur_room_idx]

                # if there is no space, move to next room
                while (
                    filled_rooms[cur_room] + counts[prefix]
                    > capacities[cur_room] + extra_capacity
                ):
                    cur_room_idx += 1
                    if cur_room_idx >= len(room_order):
                        break

                    cur_room = room_order[cur_room_idx]

                # if we've run out of rooms, break
                if cur_room_idx >= len(room_order):
                    break

                # set start if not already set
                if room_ranges[cur_room]["start"] is None:
                    room_ranges[cur_room]["start"] = prefix
                # always set end
                room_ranges[cur_room]["end"] = prefix

                # increment room count
                filled_rooms[cur_room] += counts[prefix]
            else:
                # if we didn't break, we found a valid ordering

                # check for no_single_prefix
                if no_single_prefix:
                    has_single_prefix_room = False
                    for room in room_order:
                        if room_ranges[room]["start"] == room_ranges[room]["end"]:
                            has_single_prefix_room = True
                            break

                    if has_single_prefix_room:
                        # don't use this solution
                        continue

                # get average fullness
                avg_fullness = sum(
                    filled_rooms[room] / capacities[room]
                    for room in room_order
                    if capacities[room] > 0
                ) / len(room_order)
                # get max fullness
                max_fullness = max(
                    filled_rooms[room] / capacities[room]
                    for room in room_order
                    if capacities[room] > 0
                )

                # add solution
                solutions.append(
                    (avg_fullness, max_fullness, filled_rooms, room_ranges)
                )

        if not solutions:
            # haven't found anything; add 1 to all capacities
            extra_capacity += 1

    if extra_capacity == 0:
        print(f"{len(solutions)} solutions:\n")
    else:
        # if extra capacity is needed, say so
        print(
            f"{len(solutions)} solutions requiring {extra_capacity} extra capacity:\n"
        )

    if sort == "avg":
        # sort solutions by avg fullness then by max fullness
        solutions.sort(key=lambda x: (x[0], x[1]))
    elif sort == "-avg":
        solutions.sort(key=lambda x: (x[0], x[1]), reverse=True)
    elif sort == "max":
        solutions.sort(key=lambda x: (x[1], x[0]))
    elif sort == "-max":
        solutions.sort(key=lambda x: (x[1], x[0]), reverse=True)

    # apply limit to the number of solutions to print
    if limit == -1:
        limit = len(solutions)

    for avg_fullness, max_fullness, filled_rooms, room_ranges in solutions[:limit]:
        print(f"avg: {avg_fullness:.4f}, max: {max_fullness:.4f}")
        for room, room_range in room_ranges.items():
            print(
                f"{room} ({filled_rooms[room]}/{capacities[room]}):"
                f" {room_range['start']}-{room_range['end']}"
            )
        print()


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument(
        "students",
        help="CSV file with student information; names should be of the form 'Last, First'",
    )
    parser.add_argument("rooms", help="CSV file with room capacities")
    parser.add_argument(
        "--scale",
        type=float,
        default=1.0,
        help=(
            "Scale for room capacity; all capacities are multiplied by this value"
            " (and rounded down) in preprocessing (default: 1.0)"
        ),
    )
    parser.add_argument(
        "--sort",
        choices=["avg", "max", "-avg", "-max"],
        default="avg",
        help=(
            "Sort order of output; 'avg' sorts by average fullness first,"
            " 'max' sorts by max fullness first. Prepending a '-' reverses the order."
            "(default: avg)"
        ),
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=-1,
        help="Number of solutions to print out; -1 to print all options. (default: -1)",
    )
    parser.add_argument(
        "--no-single-prefix",
        action="store_true",
        help="If given, start and end prefixes for a given room cannot be the same.",
    )
    args = parser.parse_args()
    main(
        args.students,
        args.rooms,
        scale=args.scale,
        sort=args.sort,
        limit=args.limit,
        no_single_prefix=args.no_single_prefix,
    )
