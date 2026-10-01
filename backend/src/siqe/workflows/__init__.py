"""Temporal workflow definitions.

Workflow code must be deterministic: no I/O, no ``datetime.now()``, no random numbers, no
threads. Do all of that in activities (``siqe.activities``). See AGENTS.md.
"""
