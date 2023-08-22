# Fetch Sections

Fetches associated sections from a course catalog page.

Usage: `python3 fetch_sections.py [--format={csv,table}] <url>`

-   `--format={csv,table}`: output format

    -   `csv` displays the sections in CSV format, making it easier to copy into a spreadsheet, etc.

    -   `table` displays the sections in a more human-readable table format.

-   `url`: the course URL to fetch sections from.

    This URL should be the course URL on the catalog page, on `classes.berkeley.edu`.

## Implementation

The URL is loaded via Selenium, since data is fetched dynamically via Javascript.
We don't wait until the full page is loaded, since this would load additional data and sections that are not needed.

Instead, we search for the IDs needed to send a separate request directly to the API for fetching associated sections. This request tends to take a while, but it results in raw JSON data for each section.

This data is then parsed and displayed in the console.
