from abc import ABC, abstractmethod


class QuorumBase(ABC):
    """
    An abstraction to allow multiple clusters to obtain quorum before
    proceeding with deployment stage.

    For a particular `namespace` the `join` method must be called
    `quorum` times and `poll` must be called ``quorum - 1`` times or
    for each member that got returned `False` when calling `join`.
    """

    @abstractmethod
    def join(self, namespace: str, quorum: int) -> bool:
        """Join the `namespace` and return whether or not `quorum` was reached."""
        ...

    @abstractmethod
    def poll(self, namespace: str, quorum: int) -> bool:
        """Return whether or not `namespace`'s `quorum` was reached."""
        ...
