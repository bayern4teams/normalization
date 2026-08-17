"""normdict — read-only dictionary loader (Source.txt §58). Full
CRUD/versioning/custom-overlay subsystem (§59) lands in M6.
"""

from normdict.loader import DictionaryLoader, DictionaryNotFoundError
from normdict.models import Dictionary

__all__ = ["Dictionary", "DictionaryLoader", "DictionaryNotFoundError"]
