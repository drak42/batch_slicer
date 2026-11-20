"""Define the minimal contract shared by executable backends."""

from collections.abc import Sequence
from typing import Generic, Protocol, TypeVar


ResultT = TypeVar("ResultT")


class Backend(Protocol, Generic[ResultT]):
    """Represent a backend that executes a complete command."""

    def run(self, command: Sequence[str]) -> ResultT:
        """Execute ``command`` and return its backend-specific result."""
        ...