# Room Partitioning

Partitions a list of students into rooms based on alphabetical order by last name,
without exceeding the room capacities.

The algorithm greedily expands the room capacities by 1 until a valid solution is found.
This isn't the most efficient algorithm, but since the number of rooms is small, it's good enough.

Usage: `room_partitions.py [--scale SCALE] [--sort {avg,max}] student_csv room_csv`

-   `student_csv`: a CSV file of student information, with a `Name` column for student names.

    The names should be of the form "Last, First"; it's easiest to get the CSV
    exported directly from CalCentral and referenced here.

-   `room_csv`: a CVS file with the columns `Room` and `Capacity`, to specify the different rooms and their respective capacities.

    By default, this script will fill capacities as given,
    but the `--scale` parameter can be used to scale down the capacities
    (ex. if you desire to only fill to half capacity)

-   `--scale <float>`: used to modify the capacities; for example, use `--scale 0.5` to only fill rooms to half capacity.

-   `--sort avg|max`: used to order the list of matchings.

    Use `--sort avg` to sort by average fullness across all rooms (from lowest to highest)
    Use `--sort max` to sort by maximum fullness across all rooms (from lowest to highest)
