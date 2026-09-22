"""Background work.

Plain functions with explicit arguments (a session or a ``Runtime``, the rows, the clock) so the
route can run them inline, the tests can call them directly, and ``app/jobs/queue.py`` can wrap
them as procrastinate tasks: extraction on demand, the Doc re-check every 5 minutes, token health
daily.
"""

from __future__ import annotations

from app.jobs.extract import extraction_out, perform_extraction, run_extraction, start_extraction
from app.jobs.fetch_doc import fetch_missing_docs, fetch_notes_doc
from app.jobs.token_health import check_connection_health

__all__ = [
    "check_connection_health",
    "extraction_out",
    "fetch_missing_docs",
    "fetch_notes_doc",
    "perform_extraction",
    "run_extraction",
    "start_extraction",
]
