"""Image I/O, edit pipeline and export.

Every user image is opened through ``siqe.imaging.io.open_image`` (AGENTS.md rule 4). The edit
formulas live in ``siqe.imaging.ops``; the browser's WebGL preview implements the same
formulas, and ``tests/fixtures/ops_parity.json`` keeps the two in step.
"""
