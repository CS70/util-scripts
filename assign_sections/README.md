# Assign Discussion and OH Slots

Min-cost max-flow algorithm to assign TAs/course staff to discussion/OH slots.

## Usage

### Input Files

For section and OH matching, the columns should have the following headers:

```
    Location | Day | Time | Min Count | Max Count | <Name> | <Name> | <Name> | ...
```

The "\<Name>" columns should be filled in with the staff member's name.
Each person's column should be completely filled with colors; in particular, the default
red (#FF0000), orange (#FF9900), yellow (#FFFF00), and green (#00FF00)in Google sheets.

The "Min Count" and "Max Count" columns are optional; they denote the minimum and maximum
number of people that can be assigned to the given slot.
None, one, or both of the columns can be specified.

For section and OH counts, the columns should have the following headers:

```
    Name | Min Count | Max Count
```

All of the header values must be _exactly_ as they are here (case-sensitive, with no leading or trailing whitespace), otherwise the program will error and/or not provide valid matchings.

### CLI

Usage: `assign_sections.py (--section | --oh) [--seed SEED]`

-   `--section`: flag to match sections
    -   This flag is mutually exclusive with the `--oh` flag.
-   `--oh`: flag to match OH
    -   This flag is mutually exclusive with the `--section` flag.
-   `--seed`: seed for random number generation
    -   The only randomness used in this program is to shuffle the preferences prior to matching sections/OH. This random shuffle allows for ties to be displayed on successive runs of the program, since `networkx` breaks ties arbitrarily (but deterministically).

## Implementation

### Excel Files

Excel files are loaded and parsed through `openpyxl`. We use Excel files instead of CSV files, since preferences have historically been provided as highlighting instead of numerical values. The only downloadable file format that supports this kind of metadata is `*.xlsx` (technically `*.ods` also supports this, but Excel is more popular).

The format of these Excel files is strict, to make the data parsing and collection easier. Some leeway is made with the ordering of columns, but in general everything must match the specification in the first section.

### Matching

The bulk of this program is the matching algorithm. This algorithm was taken from [CSM Scheduler](https://github.com/csmberkeley/csm_web/), and modified to fit this use case. The terminology used here will be taken from that repository as well (in particular, "mentor" is used instead of "TA", and "slot" is used to denote a section time).

As input, we are given a list of mentors, a list of slots, and a list of preferences (i.e. a tuple of a mentor, a slot, and a preference value). Since preferences are provided as colors in the spreadsheet, each color is mapped to a value (red = 0, orange = 1, yellow = 3, and green = 5).

The goal is to match mentors to slots in a way that respects as many mentors' preferences as possible. In particular, we want to make as many mentors happy as possible.

To do this, we use a min-cost max-flow algorithm. This algorithm operates on a specially constructed graph, organized in layers:

-   **Layer 0: Source**
    -   Supplies flow equal to the number of sections that need to be assigned
-   **Layer 1: Mentors**
    -   Each mentor is associated with a node in this layer.
    -   Each mentor has an edge from the source:
        -   Each edge has 0 cost.
        -   Each edge has a capacity equal to the maximum number of sections this mentor can be assigned to. This enforces the maximum section constraint per mentor.
-   **Layer 2: Slots (time slots)**
    -   Each possible time slot is associated with a node in this layer. In particular, location information is not taken into account here. For example, if there are only two sections at the same time, but at different locations, then only one time slot is created on this layer.
    -   Each time slot has an edge from every mentor:
        -   Each edge has cost inversely proportional to the mentor's preference for the slot. (Higher preferences are better, but lower weight is better for the optimization algorithm.) This allows for the algorithm to take into account people's preferences for each slot.
            -   However, since multiple sections can be collapsed into the same time slot, we take the highest preference (lowest weight) among such sections. The specifics of the actual assignment are taken care of in the next phase.
        -   Each edge has a capacity equal to 1. This enforces that each mentor can only teach one section at any given point in time (they cannot be in two places at once).
-   **Layer 3: Slots (location slots)**
    -   Each possible location is associated with a node in this layer, grouped by time. Equivalently, every single individual section is associated with a node in this layer, distinguished by both time and location.
    -   Each of these slots consumes a demand equal to the minimum number of mentors that must be assigned to this slot.
    -   Each location slot has an edge from the associated time slot:
        -   Each edge has 0 cost.
        -   Each edge has a capacity equal to the maximum number of mentors that can be assigned to this slot.
-   **Layer 4: Sink**
    -   The sink has an edge from every location slot, with cost 0.
    -   Each of these edges has capacity equal to difference between the slot's minimum and maximum possible assigned mentors, enforcing the maximum number of mentors that can be assigned to the slot.
        -   The reason why we take the difference is because the slot node itself consumes some demand, which does not make it through to the sink.

A unit of flow from a mentor to a time slot means that the mentor is assigned to some section in this time slot. However, the distinction between time and location means that we may have some ambiguity if multiple mentors are assigned to the same time slot. In these situations, we do not know which section(s) each mentor is actually assigned to.

To remedy this ambiguity, we run another round of min-cost max-flow on each collision. Each of these collisions corresponds to a single time slot. Here, we operate on a new, smaller graph, organized similarly;

-   **Layer 0: Source**
    -   Supplies flow equal to the total input flow to the time slot. This is also equal to the number of mentors that have sections assigned.
-   **Layer 1: Mentors**
    -   Each mentor is associated with a node in this layer.
    -   Each mentor has an edge from the source:
        -   Each edge has 0 cost.
        -   Each edge has a capacity equal to the input flow from the given mentor to the time slot. This flow amount is taken from the first phase; at this point, we know exactly how many sections this mentor is assigned to in the collision.
-   **Layer 2: Slots**
    -   Each slot is assigned with a node in this layer. Unlike the first phase, these slots are distinguished by both time and location.
    -   Each of these slots consumes demand equal to the minimum number of mentors that must be assigned to this slot.
    -   Each slot has an edge from every mentor:
        -   Each edge has cost inversely proportional to the mentor's preference for this slot.
        -   Each edge has a capacity equal to 1. This enforces that each mentor can only teach one section at any given point in time; all possible slots in this graph occur at the same time.
-   **Layer 3: Sink**
    -   The sink has an edge from every slot, with cost 0.
    -   Each of these edges has capacity equal to difference between the slot's minimum and maximum possible assigned mentors, enforcing the maximum number of mentors that can be assigned to the slot.

Here, a unit of flow from a mentor to a slot means that the mentor is assigned to the given slot. This clears up the ambiguities from the first phase, giving definitive assignments for every mentor.

This second phase was also considered to be implemented as a [minimum weight vertex cover on a bipartite graph](https://networkx.org/documentation/stable/reference/algorithms/generated/networkx.algorithms.bipartite.matching.to_vertex_cover.html), but this does not take into account the min/max mentor counts for each slot, so another round of min-cost max-flow was used instead.
