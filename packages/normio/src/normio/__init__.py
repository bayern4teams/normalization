"""normio — read-only source connectors and the Parquet+DuckDB sidecar
store. See docs/adr/ADR-013-normalization-storage.md.
"""

from normio.connector import SourceConnector
from normio.sidecar_store import SidecarStore

__all__ = ["SidecarStore", "SourceConnector"]
