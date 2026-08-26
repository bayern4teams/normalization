"""normsink — the destination writer, Source.txt decision 6 of the
M13-M22 program (docs/plan/M13-M22-program-plan.md), M19.

A new, physically SEPARATE package from `normio` — ADR-013's "a source
connector has no write vocabulary at all" stays literally true; this
package is where write vocabulary (`ensure_database`, `ensure_table`,
`insert_batch`, `ensure_side_table`) actually lives, on its own
`DestinationConnector` Protocol, never added to `normio.SourceConnector`.

Per the user's own standing hard rule for this milestone: the
self-write-refusal check (`normsink.safety`) is the FIRST thing built
and live-tested in this package, before any DDL-mirroring or
write-execution code exists — the safety check exists before the thing
it guards against does.
"""

from normsink.safety import SelfWriteRefusedError, assert_destination_is_not_the_source

__all__ = [
    "SelfWriteRefusedError",
    "assert_destination_is_not_the_source",
]
