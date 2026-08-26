"""Offline regression tests for inline unified-CLI command groups."""
from __future__ import annotations

import ast
import importlib
import inspect
from dataclasses import dataclass

from click.testing import CliRunner

import sustech_survival.booking as booking_pkg
import sustech_survival.faculty as faculty_pkg
import sustech_survival.lib.booking as lib_booking_pkg
import sustech_survival.pms as pms_pkg
import sustech_survival.transit as transit_pkg
from sustech_survival.cli import main


@dataclass
class _Record:
    name: str
    facility_id: str = ""
    title: str = "Professor"
    slug: str = "test"
    relevance_score: int = 1
    is_available: bool = True
    dw_job_id: int = 7
    file_name: str = "test.pdf"

    def to_dict(self):
        return {"name": self.name, "facility_id": self.facility_id}

    def to_markdown(self):
        return f"# {self.name}"


def _invoke(group, *args):
    result = CliRunner().invoke(group, list(args))
    assert result.exit_code == 0, result.output
    return result


def test_cli_main_has_no_child_package_relative_imports():
    tree = ast.parse(inspect.getsource(main))
    imports = [
        node for node in ast.walk(tree)
        if isinstance(node, ast.ImportFrom) and node.level == 1
    ]
    assert imports == []


def test_transit_commands_use_factory_and_public_contract(monkeypatch):
    class FakeTransit:
        route_args = None
        stop_args = None

        def list_facilities(self):
            return [_Record("Library", "building:library")]

        def find_facility(self, query):
            matches = {
                "library": _Record("Library", "building:library"),
                "hall": _Record("Hall", "building:hall"),
            }
            return [matches[query]] if query in matches else []

        def get_bus_stops(self, line_code, direction):
            self.stop_args = (line_code, direction)
            return [_Record("Stop", "bus_stop:1")]

        def get_live_positions(self):
            return [_Record("Bus")]

        def shortest_path(self, from_id, to_id):
            self.route_args = (from_id, to_id)
            return _Record("Route")

    fake = FakeTransit()
    monkeypatch.setattr(transit_pkg, "transit", lambda: fake)

    _invoke(main.transit_cmd, "facilities", "--json")
    _invoke(main.transit_cmd, "find", "library", "--json")
    _invoke(
        main.transit_cmd,
        "stops", "--line", "XYBS2", "--direction", "ccw", "--json",
    )
    _invoke(main.transit_cmd, "live", "--json")
    _invoke(main.transit_cmd, "route", "hall", "library")

    assert fake.stop_args == ("XYBS2", transit_pkg.DIR_CCW)
    assert fake.route_args == ("building:hall", "building:library")


def test_faculty_commands_import_parent_package(monkeypatch):
    class FakeFaculty:
        departments = ["CSE"]

        def list(self, dept, full=False, limit=None):
            return [_Record("Ada")]

        def get(self, slug):
            return _Record("Ada")

        def search(self, query, dept=None, limit=10):
            return [_Record("Ada")]

        def render(self, slug):
            return "# Ada"

    monkeypatch.setattr(faculty_pkg, "faculty", FakeFaculty())

    _invoke(main.faculty_cmd, "depts")
    _invoke(main.faculty_cmd, "list", "CSE")
    _invoke(main.faculty_cmd, "get", "ada", "--json")
    _invoke(main.faculty_cmd, "search", "systems")
    _invoke(main.faculty_cmd, "render", "ada")


def test_booking_commands_import_parent_package(monkeypatch):
    class FakeBooking:
        def whoami(self):
            return {"name": "Student"}

        def rooms(self, keyword=""):
            return [_Record("Room")]

        def my_meetings(self):
            return [_Record("Meeting")]

    monkeypatch.setattr(booking_pkg, "booking", lambda: FakeBooking())

    _invoke(main.booking_cmd, "whoami", "--json")
    _invoke(main.booking_cmd, "rooms", "Room", "--available", "--json")
    _invoke(main.booking_cmd, "my-meetings", "--json")


def test_pms_commands_use_public_factory(monkeypatch):
    class FakePMS:
        group_sn = None

        def list_stations(self, group_sn=None):
            self.group_sn = group_sn
            return [_Record("Printer")]

        def list_print_jobs(self):
            return [_Record("Print job")]

    fake = FakePMS()
    monkeypatch.setattr(pms_pkg, "pms", lambda: fake)

    _invoke(main.pms_cmd, "stations", "12", "--json")
    _invoke(main.pms_cmd, "jobs", "--json")

    assert fake.group_sn == 12


def test_library_booking_commands_and_policy(monkeypatch):
    class FakeLibraryBooking:
        def whoami(self):
            return _Record("Student")

        def home_summary(self):
            return [_Record("Discussion rooms")]

    monkeypatch.setattr(
        lib_booking_pkg, "lib_booking", lambda: FakeLibraryBooking()
    )

    _invoke(main.lib_booking_cmd, "whoami", "--json")
    _invoke(main.lib_booking_cmd, "home-summary", "--json")
    result = _invoke(main.lib_booking_cmd, "policy")
    assert "本地快照" in result.output


def test_papers_command_imports_parent_package(monkeypatch):
    search_module = importlib.import_module("sustech_survival.papers.search")
    monkeypatch.setattr(
        search_module,
        "crossref_search",
        lambda *args, **kwargs: [
            type(
                "Paper",
                (),
                {
                    "title": "Test Paper",
                    "authors": ["Ada"],
                    "year": 2026,
                    "doi": "10.1/test",
                },
            )()
        ],
    )

    result = _invoke(main.papers_cmd, "search", "test")
    assert "Test Paper" in result.output
