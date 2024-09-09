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


class PrintFormat:
    """Possible options for the print output format"""

    TABLE = "table"
    CSV = "csv"


class PrintColors:
    """Possible options for the print color format"""

    DISCRETE = "discrete"
    GRADIENT = "gradient"
