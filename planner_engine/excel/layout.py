"""Workbook layout metadata helpers for Excel planner sheets."""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Any
from zipfile import ZipFile
import re
import xml.etree.ElementTree as ElementTree


class PlannerWorkbookError(ValueError):
    """Raised when planner workbook structure cannot be parsed."""


@dataclass(frozen=True)
class CellRange:
    """A cell range parsed from workbook XML."""

    min_col: int
    min_row: int
    max_col: int
    max_row: int
    reference: str

    def contains(self, row: int, column: int) -> bool:
        """Return whether a cell is inside this range."""

        return (
            self.min_row <= row <= self.max_row
            and self.min_col <= column <= self.max_col
        )

    def intersects_rows(self, start_row: int, end_row: int) -> bool:
        """Return whether the range overlaps a row interval."""

        return not (self.max_row < start_row or self.min_row > end_row)

    def intersects_columns(self, start_column: int, end_column: int) -> bool:
        """Return whether the range overlaps a column interval."""

        return not (self.max_col < start_column or self.min_col > end_column)


@dataclass(frozen=True)
class SheetLayout:
    """Merged-cell and validation layout for a sheet."""

    merged_ranges: tuple[CellRange, ...]
    data_validation_ranges: tuple[CellRange, ...]


class LayoutMixin:
    """Resolve visible headings to actual data-entry cells."""

    def _header_map(
        self,
        worksheet: Any,
        header_row: int,
        data_start_row: int,
        data_end_row: int,
    ) -> dict[str, int]:
        """Map normalized header labels to actual entry column indexes."""

        headers: dict[str, int] = {}
        for cell in worksheet[header_row]:
            normalized = self._normalize_label(cell.value)
            if normalized:
                headers[normalized] = self._entry_column_for_header(
                    sheet_name=worksheet.title,
                    header_row=header_row,
                    header_column=cell.column,
                    data_start_row=data_start_row,
                    data_end_row=data_end_row,
                )
        return headers

    def _entry_column_for_header(
        self,
        sheet_name: str,
        header_row: int,
        header_column: int,
        data_start_row: int,
        data_end_row: int,
    ) -> int:
        """Resolve a visible header cell to the workbook's data-entry column."""

        layout = self._sheet_layout(sheet_name)
        header_range = self._merged_range_containing(
            layout,
            row=header_row,
            column=header_column,
        )
        if header_range is None:
            return header_column

        for validation_range in layout.data_validation_ranges:
            if (
                validation_range.intersects_rows(data_start_row, data_end_row)
                and validation_range.intersects_columns(
                    header_range.min_col,
                    header_range.max_col,
                )
            ):
                return max(validation_range.min_col, header_range.min_col)

        for merged_range in layout.merged_ranges:
            if (
                merged_range.min_col == header_range.min_col
                and merged_range.max_col == header_range.max_col
                and merged_range.intersects_rows(data_start_row, data_end_row)
            ):
                return merged_range.min_col

        return header_column

    def _merged_range_containing(
        self,
        layout: SheetLayout,
        row: int,
        column: int,
    ) -> CellRange | None:
        """Return the merged range containing a cell, if any."""

        for merged_range in layout.merged_ranges:
            if merged_range.contains(row, column):
                return merged_range
        return None

    def _sheet_layout(self, sheet_name: str) -> SheetLayout:
        """Load sheet merged ranges and validation ranges from workbook XML."""

        if sheet_name not in self._sheet_layout_cache:
            self._sheet_layout_cache[sheet_name] = self._load_sheet_layout(sheet_name)
        return self._sheet_layout_cache[sheet_name]

    def _load_sheet_layout(self, sheet_name: str) -> SheetLayout:
        """Read workbook XML layout metadata without modifying the workbook."""

        namespace = {
            "m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main",
        }
        rel_namespace = {
            "pr": "http://schemas.openxmlformats.org/package/2006/relationships",
        }

        with ZipFile(self.planner_path) as workbook_archive:
            workbook_root = ElementTree.fromstring(
                workbook_archive.read("xl/workbook.xml")
            )
            relationship_root = ElementTree.fromstring(
                workbook_archive.read("xl/_rels/workbook.xml.rels")
            )
            relationships = {
                relationship.attrib["Id"]: self._resolve_workbook_target(
                    relationship.attrib["Target"]
                )
                for relationship in relationship_root.findall(
                    "pr:Relationship",
                    rel_namespace,
                )
            }

            sheet_target: str | None = None
            relationship_key = (
                "{http://schemas.openxmlformats.org/officeDocument/2006/"
                "relationships}id"
            )
            for sheet in workbook_root.findall(".//m:sheet", namespace):
                if sheet.attrib["name"] == sheet_name:
                    sheet_target = relationships[sheet.attrib[relationship_key]]
                    break

            if sheet_target is None:
                raise PlannerWorkbookError(f"Unknown planner month: {sheet_name}")

            sheet_root = ElementTree.fromstring(workbook_archive.read(sheet_target))
            merged_ranges = tuple(
                self._parse_cell_range(merge_cell.attrib["ref"])
                for merge_cell in sheet_root.findall(
                    ".//m:mergeCells/m:mergeCell",
                    namespace,
                )
            )
            data_validation_ranges: list[CellRange] = []
            for data_validation in sheet_root.findall(
                ".//m:dataValidations/m:dataValidation",
                namespace,
            ):
                for reference in data_validation.attrib.get("sqref", "").split():
                    data_validation_ranges.append(self._parse_cell_range(reference))

        return SheetLayout(
            merged_ranges=merged_ranges,
            data_validation_ranges=tuple(data_validation_ranges),
        )

    def _resolve_workbook_target(self, target: str) -> str:
        """Resolve workbook relationship targets to archive paths."""

        if target.startswith("/xl/"):
            return target.lstrip("/")
        if target.startswith("xl/"):
            return target
        return str(PurePosixPath("xl") / target)

    def _parse_cell_range(self, reference: str) -> CellRange:
        """Parse an Excel cell or cell range reference."""

        if ":" not in reference:
            column, row = self._split_cell_reference(reference)
            column_number = self._column_number(column)
            return CellRange(
                min_col=column_number,
                min_row=row,
                max_col=column_number,
                max_row=row,
                reference=reference,
            )

        start, end = reference.split(":", maxsplit=1)
        start_column, start_row = self._split_cell_reference(start)
        end_column, end_row = self._split_cell_reference(end)
        return CellRange(
            min_col=self._column_number(start_column),
            min_row=start_row,
            max_col=self._column_number(end_column),
            max_row=end_row,
            reference=reference,
        )

    def _split_cell_reference(self, reference: str) -> tuple[str, int]:
        """Split a cell reference into column letters and row number."""

        match = re.fullmatch(r"([A-Z]+)(\d+)", reference)
        if match is None:
            raise PlannerWorkbookError(f"Invalid cell reference: {reference}")
        return match.group(1), int(match.group(2))

    def _column_number(self, column: str) -> int:
        """Convert Excel column letters to a 1-based column number."""

        column_number = 0
        for character in column:
            column_number = column_number * 26 + ord(character) - 64
        return column_number

    def _normalize_label(self, value: Any) -> str:
        """Normalize worksheet labels and headings for matching."""

        if value is None:
            return ""
        normalized = " ".join(str(value).strip().upper().replace("\n", " ").split())
        return normalized.lstrip("▸").strip()
