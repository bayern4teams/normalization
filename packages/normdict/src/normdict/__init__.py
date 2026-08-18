"""normdict — read-only built-in dictionary loader (Source.txt §58) plus
the user custom-dictionary CRUD/versioning/rollback subsystem (§59,
landed in M6).
"""

from normdict.custom_store import (
    BuiltinIdCollisionError,
    CustomDictionaryDeletedError,
    CustomDictionaryError,
    CustomDictionaryNotFoundError,
    CustomDictionaryStore,
)
from normdict.loader import DictionaryLoader, DictionaryNotFoundError
from normdict.models import Dictionary

__all__ = [
    "BuiltinIdCollisionError",
    "CustomDictionaryDeletedError",
    "CustomDictionaryError",
    "CustomDictionaryNotFoundError",
    "CustomDictionaryStore",
    "Dictionary",
    "DictionaryLoader",
    "DictionaryNotFoundError",
]
