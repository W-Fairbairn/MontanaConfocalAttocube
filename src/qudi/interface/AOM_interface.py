from abc import abstractmethod
from qudi.core.module import Base

class AOM_interface(Base):
    @abstractmethod
    def get_power(self):
        """ Return actual laser power

        @return float: Laser power in watts
        """
        pass

    @abstractmethod
    def set_power(self, power):
        """ Set power setpoint.

        @param float power: power to set
        """
        pass