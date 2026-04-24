"""
旧版 geo 模块兼容入口。
"""

from .generator.geo import (
    GeoCodeIndex,
    build_geo_index_from_snapshot,
    build_geo_index_from_workbook,
    build_geo_snapshot,
    load_geo_index,
    packaged_snapshot_path,
    repo_workbook_path,
)

__all__ = [
    "GeoCodeIndex",
    "build_geo_index_from_snapshot",
    "build_geo_index_from_workbook",
    "build_geo_snapshot",
    "load_geo_index",
    "packaged_snapshot_path",
    "repo_workbook_path",
]
