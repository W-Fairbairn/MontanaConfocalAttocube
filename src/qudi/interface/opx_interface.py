from enum import IntEnum
from abc import abstractmethod
from qudi.core.module import Base


class OPXInterface(Base):

    @abstractmethod
    def connect_opx(self):
        pass
