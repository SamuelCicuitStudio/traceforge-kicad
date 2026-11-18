"""Read-only live-board BOM fields. No file save or zone fill."""

from __future__ import annotations


def snapshot(board):
    parts = []
    for footprint in board.GetFootprints():
        props = {str(field.GetName()): str(field.GetText()) for field in footprint.GetFields()}
        parts.append(
            dict(
                reference=footprint.GetReference(),
                value=footprint.GetValue(),
                footprint=str(footprint.GetFPID().GetLibItemName()),
                properties=props,
                dnp=bool(footprint.IsDNP()),
                exclude_bom=bool(footprint.IsExcludedFromBOM()),
            )
        )
    return dict(board=board.GetFileName(), parts=parts, source="live PCB fields")
