import datetime
import numpy as np
from abc import abstractmethod
from qudi.core.module import Base

class TimeTaggerInterface(Base):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    @abstractmethod
    def connect_tagger(self, position):
        pass

    @abstractmethod
    def get_counts(self, avg_time):
        pass