import datetime
import numpy as np
from abc import abstractmethod
from qudi.core.module import Base

class AttocubeStageInterface(Base):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


    @abstractmethod
    def move_absolute(self, position):
        pass

    @abstractmethod
    def get_position(self):
        pass