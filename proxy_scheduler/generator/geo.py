"""
地区代码索引模块。

运行时固定优先使用内置 JSON 快照；Excel 仅作为开发阶段生成快照的数据源。
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
    """
    国家、州、城市代码索引。
    """

    countries: frozenset[str]
    states_by_country: dict[str, frozenset[str]]
    cities_by_country: dict[str, frozenset[str]]
    city_to_state_by_country: dict[str, dict[str, str]]


def repo_workbook_path() -> Path:
    """
    返回仓库根目录中的地区 Excel 数据源路径。

    Returns:
        Path: Excel 数据源路径。
    """

    return Path(__file__).resolve().parents[2] / _WORKBOOK_FILENAME


def packaged_snapshot_path() -> Path:
    """
    返回 SDK 内置地区 JSON 快照路径。

    Returns:
        Path: JSON 快照路径。
    """

    return Path(__file__).resolve().parents[1] / "data" / _SNAPSHOT_FILENAME


@lru_cache(maxsize=1)
def load_geo_index() -> GeoCodeIndex:
    """
    加载地区代码索引。

    Returns:
        GeoCodeIndex: 地区代码索引。

    Raises:
        FileNotFoundError: JSON 快照不存在时抛出。
    """

    snapshot = packaged_snapshot_path()

    if snapshot.exists():
        return build_geo_index_from_snapshot(json.loads(snapshot.read_text(encoding="utf-8")))

    raise FileNotFoundError(f"Packaged geo snapshot {_SNAPSHOT_FILENAME!r} could not be found.")


def build_geo_index_from_workbook(path: Path) -> GeoCodeIndex:
    """
    从 Excel 数据源构建地区代码索引。

    Args:
        path (Path): Excel 数据源路径。

    Returns:
        GeoCodeIndex: 地区代码索引。
    """

    return build_geo_index_from_snapshot(build_geo_snapshot(path))


def build_geo_snapshot(path: Path) -> dict[str, object]:
    """
    从 Excel 数据源构建可序列化的地区快照。

    Args:
        path (Path): Excel 数据源路径。

    Returns:
        dict[str, object]: 地区快照字典。
    """

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
    """
    从 JSON 快照构建地区代码索引。

    Args:
        snapshot (dict[str, object]): 地区快照字典。

    Returns:
        GeoCodeIndex: 地区代码索引。
    """

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
    """
    读取 Excel 压缩包中的共享字符串。

    Args:
        archive (zipfile.ZipFile): Excel 压缩包对象。

    Returns:
        list[str]: 共享字符串列表。
    """

    if "xl/sharedStrings.xml" not in archive.namelist():
        return []

    root = ET.fromstring(archive.read("xl/sharedStrings.xml"))
    values: list[str] = []
    for si in root.findall("a:si", _XML_NS):
        values.append("".join(node.text or "" for node in si.iterfind(".//a:t", _XML_NS)))
    return values


def _load_sheet_targets(archive: zipfile.ZipFile) -> list[tuple[str, str]]:
    """
    读取 Excel 工作表名称和 XML 路径。

    Args:
        archive (zipfile.ZipFile): Excel 压缩包对象。

    Returns:
        list[tuple[str, str]]: 工作表名称和 XML 路径列表。
    """

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
    """
    读取 Excel 单行数据并按列名返回。

    Args:
        row (ET.Element): 行 XML 节点。
        shared_strings (list[str]): 共享字符串列表。

    Returns:
        dict[str, str]: 列名到单元格文本的映射。
    """

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
