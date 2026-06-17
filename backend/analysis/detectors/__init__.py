"""Prose-quality detectors — pure functions that take text (and sometimes
database model shapes) and return structured findings.

Each detector is independently testable. The only shared dependency is
``text_segmentation`` (a sibling) and ``database.models`` (a layer below).
The consolidated runner that calls all detectors lives one level up in
``analysis.audit``; public result types are re-exported through the
``analysis`` facade.
"""
