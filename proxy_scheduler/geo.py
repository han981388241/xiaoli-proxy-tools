"""
Geo-code index used for generator parameter validation.

The source of truth is the workbook ``州城市数据.xlsx`` at the repository
root. A compact JSON snapshot is also bundled under ``proxy_scheduler/data``
for fast runtime loading. If the workbook is newer than the snapshot, the
workbook is parsed directly and overrides the bundled snapshot.
"""

from __future__ import annotations

import json
import zipfile
import xml.etree.ElementTree as ET
from collections import defaultdict
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path


_WORKBOOK_FILENAME = "geo_codes.xlsx"
_SNAPSHOT_FILENAME = "geo_codes.min.json"
_REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
_XML_NS = {
    "a": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
    "p": "http://schemas.openxmlformats.org/package/2006/relationships",
}


@dataclass(frozen=True)
class GeoCodeIndex:
    countries: frozenset[str]
    states_by_country: dict[str, frozenset[str]]
    cities_by_country: dict[str, frozenset[str]]
    city_to_state_by_country: dict[str, dict[str, str]]


def repo_workbook_path() -> Path:
    return Path(__file__).resolve().parents[1] / _WORKBOOK_FILENAME


def packaged_snapshot_path() -> Path:
    return Path(__file__).resolve().parent / "data" / _SNAPSHOT_FILENAME


@lru_cache(maxsize=1)
def load_geo_index() -> GeoCodeIndex:
    workbook = repo_workbook_path()
    snapshot = packaged_snapshot_path()

    if workbook.exists() and snapshot.exists():
        if workbook.stat().st_mtime > snapshot.stat().st_mtime:
            return build_geo_index_from_workbook(workbook)
        return build_geo_index_from_snapshot(json.loads(snapshot.read_text(encoding="utf-8")))

    if snapshot.exists():
        return build_geo_index_from_snapshot(json.loads(snapshot.read_text(encoding="utf-8")))

    if workbook.exists():
        return build_geo_index_from_workbook(workbook)

    raise FileNotFoundError(
        f"Neither {_WORKBOOK_FILENAME!r} nor {_SNAPSHOT_FILENAME!r} could be found."
    )


def build_geo_index_from_workbook(path: Path) -> GeoCodeIndex:
    return build_geo_index_from_snapshot(build_geo_snapshot(path))


def build_geo_snapshot(path: Path) -> dict[str, object]:
    state_cities: dict[str, dict[str, list[str]]] = defaultdict(lambda: defaultdict(list))

    with zipfile.ZipFile(path) as archive:
        shared_strings = _load_shared_strings(archive)
        sheets = _load_sheet_targets(archive)

        for _, target in sheets:
            sheet_root = ET.fromstring(archive.read(target))
            rows = sheet_root.findall(".//a:sheetData/a:row", _XML_NS)
            for row in rows[1:]:
                values = _read_row(row, shared_strings)
                country = values.get("E", "").strip().upper()
                state = values.get("G", "").strip()
                city = values.get("I", "").strip()
                if country and state and city:
                    state_cities[country][state].append(city)

    return {
        "countries": sorted(state_cities),
        "state_cities": {
            country: {
                state: sorted(cities)
                for state, cities in sorted(states.items())
            }
            for country, states in sorted(state_cities.items())
        },
    }


def build_geo_index_from_snapshot(snapshot: dict[str, object]) -> GeoCodeIndex:
    state_cities = snapshot["state_cities"]
    assert isinstance(state_cities, dict)

    states_by_country: dict[str, frozenset[str]] = {}
    cities_by_country: dict[str, frozenset[str]] = {}
    city_to_state_by_country: dict[str, dict[str, str]] = {}

    for country, states in state_cities.items():
        assert isinstance(country, str)
        assert isinstance(states, dict)
        country_city_to_state: dict[str, str] = {}

        for state, cities in states.items():
            assert isinstance(state, str)
            assert isinstance(cities, list)
            for city in cities:
                assert isinstance(city, str)
                country_city_to_state[city] = state

        states_by_country[country] = frozenset(states.keys())
        cities_by_country[country] = frozenset(country_city_to_state.keys())
        city_to_state_by_country[country] = country_city_to_state

    countries = snapshot.get("countries", list(states_by_country))
    assert isinstance(countries, list)
    return GeoCodeIndex(
        countries=frozenset(str(country) for country in countries),
        states_by_country=states_by_country,
        cities_by_country=cities_by_country,
        city_to_state_by_country=city_to_state_by_country,
    )


def _load_shared_strings(archive: zipfile.ZipFile) -> list[str]:
    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for si in root.findall("a:si", _XML_NS):
        values.append("".join(node.text or "" for node in si.iterfind(".//a:t", _XML_NS)))
    return values


def _load_sheet_targets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    workbook = ET.fromstring(archive.read("xl/workbook.xml"))
    rels = ET.fromstring(archive.read("xl/_rels/workbook.xml.rels"))
    rel_map = {
        rel.attrib["Id"]: rel.attrib["Target"]
        for rel in rels.findall("p:Relationship", _XML_NS)
    }

    sheets: list[tuple[str, str]] = []
    for sheet in workbook.find("a:sheets", _XML_NS) or []:
        rid = sheet.attrib[_REL_NS]
        target = rel_map[rid]
        if not target.startswith("xl/"):
            target = f"xl/{target}"
        sheets.append((sheet.attrib["name"], target))
    return sheets


def _read_row(row: ET.Element, shared_strings: list[str]) -> dict[str, str]:
    values: dict[str, str] = {}

    for cell in row.findall("a:c", _XML_NS):
        ref = cell.attrib.get("r", "")
        column = "".join(ch for ch in ref if ch.isalpha())
        cell_type = cell.attrib.get("t")

        if cell_type == "inlineStr":
            inline = cell.find("a:is", _XML_NS)
            value = (
                "".join(node.text or "" for node in inline.iterfind(".//a:t", _XML_NS))
                if inline is not None
                else ""
            )
        else:
            raw = cell.find("a:v", _XML_NS)
            value = "" if raw is None or raw.text is None else raw.text
            if cell_type == "s" and value:
                value = shared_strings[int(value)]

        values[column] = value.strip() if isinstance(value, str) else ""

    return values
