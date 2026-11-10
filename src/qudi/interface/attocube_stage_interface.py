from abc import abstractmethod
from qudi.core.module import Base


class AttocubeStageInterface(Base):
    """ Interface for a multi-axis Attocube positioner stage.

    Implementations identify axes by a string label (e.g. 'x', 'y', 'z') as returned by
    get_axes(). All positions/distances are in meters.
    """

    @abstractmethod
    def get_axes(self):
        """ Return a tuple of available axis labels, e.g. ('x', 'y', 'z'). """
        pass

    @abstractmethod
    def get_range(self, axis):
        """ Return the configured (min, max) travel range in meters for the given axis,
        or None if not configured.
        """
        pass

    @abstractmethod
    def move_absolute(self, axis, position):
        """ Move the given axis to an absolute position in meters. """
        pass

    @abstractmethod
    def get_position(self, axis):
        """ Return the current position of the given axis in meters. """
        pass

    @abstractmethod
    def step(self, axis, backward=False):
        """ Perform a single discrete step on the given axis.

        @param str axis: axis label
        @param bool backward: step direction; False steps forward/positive, True backward/negative
        """
        pass

    @abstractmethod
    def stop(self, axis):
        """ Stop any ongoing motion on the given axis. """
        pass
