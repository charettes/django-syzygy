from abc import ABC, abstractmethod


class QuorumBase(ABC):
    """
    An abstraction to allow multiple parties to obtain quorum before
    proceeding with a coordinated action.

    For a particular `namespace` the `join` method must be called
    `quorum` times and `poll` must be called ``quorum - 1`` times or
    for each party that got returned `False` when calling `join`.

    The `sever` method must be called instead of `join` by parties
    that do not intend to participate in attaining `namespace`'s quorum.
    It must result in other parties raising `QuorumDisolved` on their next
    `poll` for that `namespace`.
    """

    @abstractmethod
    def join(self, namespace: str, quorum: int) -> bool:
        """Join the `namespace` and return whether or not `quorum` was attained."""
        ...

    @abstractmethod
    def sever(self, namespace: str, quorum: int):
        """Sever the `namespace`'s quorum attainment process."""

    @abstractmethod
    def poll(self, namespace: str, quorum: int) -> bool:
        """
        Return whether or not `namespace`'s `quorum` was reached.

        Raise `QuorumDisolved` if the quorom attainment process was
        severed.
        """
        ...
