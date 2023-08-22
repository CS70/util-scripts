"""
Fetch associated sections from a course catalog page.
"""

import json
from datetime import datetime, timedelta

import requests
from bs4 import BeautifulSoup
from rich.console import Console, Theme
from rich.table import Table, box
from selenium import webdriver
from selenium.webdriver import ChromeOptions

ASSOC_SECTION_URL = (
    "https://classes.berkeley.edu/enrollment/json-all-associated-sections/%d/%d/%d"
)

console = Console(theme=Theme({"repr.number": ""}))


def main(url: str, format: str):
    # fetch page
    options = ChromeOptions()
    options.add_argument("--headless=new")
    driver = webdriver.Chrome(options=options)
    driver.get(url)

    soup = BeautifulSoup(driver.page_source, "html.parser")
    associated_sections_div = soup.find(id="associatedSections")
    div_attrs = associated_sections_div.attrs
    section_id = int(div_attrs["data-sectionid"])
    term_id = int(div_attrs["data-termid"])

    assoc_url = ASSOC_SECTION_URL % (section_id, section_id, term_id)
    response = requests.get(assoc_url, timeout=60)
    parsed = json.loads(response.content)

    lines_by_time = {}
    lines_by_id = {}
    for node in parsed["nodes"]:
        section = json.loads(node["node"]["json"])
        section_number = section["number"]
        section_meetings = section["meetings"]
        if len(section_meetings) > 1:
            console.print(f"[red]more than one meeting: {section_number}[/red]")
            continue
        if len(section_meetings) == 0:
            console.print(f"[red]no meetings: {section_number}[/red]")
            continue
        section_meeting = section_meetings[0]

        meeting_building = section_meeting.get("location", {})
        meeting_location = (meeting_building or {}).get("description", "")

        meeting_start = datetime.strptime(section_meeting["startTime"], "%H:%M:%S")
        meeting_end = datetime.strptime(
            section_meeting["endTime"], "%H:%M:%S"
        ) + timedelta(minutes=1)
        meeting_days = section_meeting.get("meetsDays", "")

        formatted_start = meeting_start.strftime("%-I%p")
        formatted_end = meeting_end.strftime("%-I%p")

        if meeting_days not in lines_by_time:
            lines_by_time[meeting_days] = {}
        if meeting_start not in lines_by_time[meeting_days]:
            lines_by_time[meeting_days][meeting_start] = []

        if format == "csv":
            line = (
                f"{section_number},{meeting_location},{meeting_days},"
                f"{formatted_start}-{formatted_end}"
            )
        elif format == "table":
            line = [
                section_number,
                meeting_location,
                meeting_days,
                formatted_start,
                formatted_end,
            ]

        lines_by_time[meeting_days][meeting_start].append(line)
        # should be unique by ID
        lines_by_id[section_number] = line

    if format == "csv":
        console.print("\nSorted by time:\n")
        for days in sorted(lines_by_time.keys()):
            for time in sorted(lines_by_time[days].keys()):
                line_lst = lines_by_time[days][time]
                for line in line_lst:
                    console.print(line)

        console.print("\nSorted by ID:\n")
        for section_number in sorted(lines_by_id):
            console.print(lines_by_id[section_number])
    elif format == "table":
        table_by_time = Table(
            "ID",
            "Location",
            "Days",
            "Start Time",
            "End Time",
            box=box.SIMPLE,
            title="Sorted by time",
        )
        for days in sorted(lines_by_time.keys()):
            for time in sorted(lines_by_time[days].keys()):
                for line in lines_by_time[days][time]:
                    table_by_time.add_row(*line)
        console.print(table_by_time)

        table_by_id = Table(
            "ID",
            "Location",
            "Days",
            "Start Time",
            "End Time",
            box=box.SIMPLE,
            title="Sorted by ID",
        )
        for section_number in sorted(lines_by_id):
            table_by_id.add_row(*lines_by_id[section_number])
        console.print(table_by_id)


if __name__ == "__main__":
    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("url", help="URL for the course page on classes.berkeley.edu")
    parser.add_argument(
        "--format", choices=["csv", "table"], default="table", help="Output format"
    )
    args = parser.parse_args()

    main(args.url, args.format)
