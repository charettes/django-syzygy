from abc import ABC, abstractmethod


class QuorumBase(ABC):
    """
    An abstraction to allow multiple clusters to obtain quorum before
    proceeding with deployment stage.
    """

    @abstractmethod
    def join(self, namespace: str, quorum: int) -> bool:
        """Join the `namespace` and return whether or not `quorum` was reached."""
        ...

    @abstractmethod
    def poll(self, namespace: str, quorum: int) -> bool:
        """Return whether or not `namespace`'s `quorum` was reached."""
        ...
