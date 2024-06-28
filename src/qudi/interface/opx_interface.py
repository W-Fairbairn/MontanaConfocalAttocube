"""
Interface file for Quantum Machines OPX where pulses can be configured and data streamed.

Author: Alex Newman 2024
"""

from enum import IntEnum
from abc import abstractmethod
from qudi.core.module import Base


class OPXInterface(Base):

    @abstractmethod
    def connect_opx(self):
        pass
