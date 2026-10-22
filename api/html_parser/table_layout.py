"""Column placement of HTML table cells under row/col spans, bounded by a cell budget."""
from __future__ import annotations

from .models import TablePlacement


def place_cells(spans: list[list[tuple[int, int]]], max_cells: int) -> TablePlacement | None:
    """Each cell's grid column, skipping columns held by rowspans from above; None once the grid would exceed `max_cells`."""
    num_rows = len(spans)
    covered_until: dict[int, int] = {}
    columns: list[list[int]] = []
    width = 0
    area = 0
    for row_index, row in enumerate(spans):
        column = 0
        row_columns: list[int] = []
        for rowspan, colspan in row:
            while covered_until.get(column, 0) > row_index:
                column += 1
            row_columns.append(column)
            rows_covered = min(rowspan, num_rows - row_index)
            area += rows_covered * colspan
            if area > max_cells:
                return None
            if rows_covered > 1:
                for covered in range(column, column + colspan):
                    covered_until[covered] = row_index + rows_covered
            column += colspan
            width = max(width, column)
        columns.append(row_columns)
    if num_rows * width > max_cells:
        return None
    return TablePlacement(columns=columns, width=width)

