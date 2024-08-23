# Assign Sections and OH Slots

ILP algorithm to assign TAs/course staff to discussion and OH slots.

## Usage

### Generating input files

#### Via colored spreadsheet

The easiest way to generate input files is through a spreadsheet, where preferences are color-coded.

For both section and OH matching, the columns should have the following headers:

```
    Location | Day | Start Time | End Time | Min Count | Max Count | <NAME> | <NAME> | ...
```

The `<NAME>` columns should be filled in with the staff member's name.
Each person's column should be completely filled with colors; in particular, the default
red (#FF0000), orange (#FF9900), yellow (#FFFF00), and green (#00FF00) in Google sheets.

The "Min Count" and "Max Count" columns are optional; they denote the minimum and maximum
number of people that can be assigned to the given slot.
None, one, or both of the columns can be specified.

For section and OH counts, the columns should have the following headers:

```
    Name | Min Count | Max Count
```

All of the header values must be _exactly_ as they are here (case-sensitive, with no leading or trailing whitespace), otherwise the program will error and/or not provide valid matchings.

Generating the input files can be done through the following script:

```sh
python3 convert_colored_spreadsheet.py <XLSX_file>
```

The script has a variety of options to customize the sheet names and output file names, which can all be listed by passing the `-h` flag.

By default, the outputs will include:

- `section_preferences.csv`: A CSV file containing preferences for discussion sections, along with discussion section info.
- `section_config.json`: A JSON file with all of the configuration for section slots, i.e. the min/max number of users allowed for each slot, along with the min/max number of slots allowed to be assigned to each user.
- `oh_preferences.csv`: A CSV file containing preferences for OH slots, along with the OH slot info.
- `oh_config.json`: A JSON file with all of the configuration for OH slots.

#### Manually

If the colored spreadsheet is not preferred, an alternate way of providing the input is to create the required files manually, or through some other automated means. At the minimum, the matching script requires a preferences CSV file along with a configuration JSON file. It is possible to run the matcher with only discussion section information provided, or with only OH information provided; it is not required to match both at the same time (though it is highly advised).

The preferences CSV file must contain the following headers:

```
ID,Location,Day,Start Time,End Time,<NAME>,<NAME>,...
```

Note that these headers must appear with the exact same case, with no extra whitespace (namely none surrounding the commas). The `<NAME>` headers should be filled in with the staff member's name.

The `ID` field is used to uniquely identify the slot; this `ID` is used to match to the slot in the configuration JSON file.

The configuration JSON file must be of the following form:

```json
{
  "users": {
    "<NAME>": {
      "min_slots": int,
      "max_slots": int
    },
    ...
  },
  "slots": {
    "<SLOT_ID>": {
      "min_users": int,
      "max_users": int
    },
    ...
  }
}
```

This configuration file provides two bits of information:

- The `users` key contains information about how many slots should be matched to each user. This can be useful if (for example) a given user must be assigned to multiple OH slots or discussion sections.
- The `slots` key contains information about how many users should be matched to each slot. This can be useful if (for example) a given OH slot is required to be staffed by multiple people.

An additional (optional) matcher configuration JSON file can be given as well, with the following keys:

- `section_bias` (`float`, between 0 and 1): Bias factor weighing the importance of a better section matching vs. a better OH matching. A number closer to 0 will try to make better OH matchings, while a number closer to 1 will try to make better section matchings.

  The default value is `0.75`.

- `maximize_filled_slots` (`bool`): Whether to maximize the number of filled slots. This adds a factor to the optimization problem which emphasizes assigning as many slots as possible to each user.

  The default value is `False`.

### Running the matcher

With the input files, the matching algorithm can be run using the following command:

```sh
python3 assign_sections.py \
    --section-preferences section_preferences.csv \
    --section-config section_config.json \
    --oh-preferences oh_preferences.csv \
    --oh-config oh_config.json \
    --matcher-config matcher_config.json
```

(Here the default input filenames are used, but they can be swapped out with any others.) The section/OH preferences/config files should be self explanatory, but `--matcher-config` can optionally be provided if you'd like to modify the matcher algorithm itself.

In addition, a couple other options for the script are available, and can be listed by passing the `-h` flag to the script.

## Implementation

### Excel Files

The `convert_colored_spreadsheet.py` script requires an Excel file input. This is primarily due to the fact that section/OH preferences have historically been provided as highlighting in Google Sheets rather than through numerical values. The only downloadable file format from Google Sheets that supports this kind of metadata is `*.xlsx` (technically `*.ods` also supports this, but Excel is more popular).

Excel files are loaded and parsed through `openpyxl`. The format of these Excel files is strict, to make the data parsing and collection easier. Some leeway is made with the ordering of columns, but in general everything must match the specification in the first section.

### Matching

A large portion of this utility is the matching algorithm. A first iteration of the matching algorithm used min-cost max-flow, but there were many limitations and complexities that made it hard to improve and add any other requirements. Instead, the more general ILP optimization approach was used, solving the general optimization problem utilizing `cvxpy`.

If a colored spreadsheet is used, the colors are first converted into integer preferences: red = 0, orange = 1, yellow = 3, and green = 5. A larger preference number indicates that a user prefers the slot more, and a preference of 0 indicates that the user is completely unable to be matched to the given slot.

As a brief note, we use "users" here to denote the staff members/TAs, as a generic term for the people involved in the matching. Similarly, "slot" is used to denote the section or OH time slot that users are matched to.

The optimization problem is given a set of constraints and an objective, with the goal of maximizing the "happiness" of all users involved.

The objective is

$$\max_x \alpha f_{\text{section}} + (1 - \alpha) f_{\text{OH}}$$

where $\alpha$ is a term balancing between matching section slots and matching OH slots. By default, $\alpha = 0.75$, to encourage better matching for section slots compared to OH slots, if a compromise must be made.

Here, $f_{\text{section}}$ and $f_{\text{OH}}$ are defined similar to each other, as $f = \sum_{u,s} p_{u,s} x_{u,s}$. In the summation, $p_{u,s}$ is the preference of user $u$ to slot $s$, and $x_{u,s}$ is whether user $u$ is actually assigned to slot $s$.

If `maximize_filled_slots` is set to `True`, then an additional term is added to the objective: $\lambda \sum_{u,s} x_{u,s}$, where $\lambda$ is a parameter (set to 1000 by default) tuning the influence of the term.

The constraints for the optimization problem fall under a few categories:

- Ensure all variables are binary:

  $$x_{u,s} \in \{0, 1\},\quad \forall u,s$$

  Since we want a matching, a user and a slot must either be matched or unmatched.

- Ensure that preferences of 0 result in the user never being matched to the given slot:

  $$p_{u,s} = 0 \implies x_{u,s} = 0,\quad \forall u,s$$

  Without this constraint, the optimization is free to set $x_{u,s} = 1$ even if $p_{u,s} = 1$, since it has no effect on the objective.

  This constraint is implemented by simply not declaring an optimization variable for the $x_{u,s}$ in question, rather than adding an equality constraint. A constant of 0 is used instead whenever $x_{u,s}$ is referenced.

  Optionally, preferences may be given a large negative value if instead you'd like to severely punish the algorithm for choosing a slot, rather than fully disallowing it. (There is no nonnegativity check on the preferences, though it is an input constraint that is recommended.)

- Enforce the number of assignments for each uesr:

  $$u_\text{min} \le \sum_s x_{u,s} \le u_\text{max},\quad \forall u$$

  Here $u_\text{min}$ and $u_\text{max}$ are the min/max number of assignments that user $u$ can have.

- Enforce the number of assignments for each slot:

  $$s_\text{min} \le \sum_u x_{u,s} \le s_\text{max},\quad \forall s$$

  Here $\text{min}_s$ and $\text{max}_s$ are the min/max number of assignments that slot $s$ can have.

- Enforce time conflicts for discussion slots and OH slots, separately:

  $$\sum_{s \in C} x_{u,s} \le 1,\quad \forall u, C$$

  Here $s \in C$ denotes all slots in a conflict group $C$; slots are conflicting if they overlap in time. This ensures that an individual is never assigned to two slots that overlap in time, as a given person cannot be in two places at the same time.

  Note that this objective does not account for any interactions between discussion slots and OH slots; with only this constraint, users can still be assigned to a discussion slot that happens at the same time as an OH slot they are also assigned to.

  In implementation, this constraint is provided with pairwise conflicts (i.e. $|C| = 2$ in all cases, and multiple conflicting events are separated into pairs), but is equivalent to the above summation even when $|C| > 2$.

- Enforce time conflicts for discussion slots and OH slots, together. The objective is written out similar to above.

  Here, we want to ensure that a discussion assignment for a given user rules out an OH assignment for the same time, since a given person cannot be in two places at the same time.

All of the above constraints are duplicated for both section slots and OH slots, if both are provided. (Except for the last, as it involves interactions across section slots and OH slots.)
