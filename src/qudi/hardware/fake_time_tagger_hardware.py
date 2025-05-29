import time
import numpy as np
from qudi.interface.timetagger_interface import TimeTaggerInterface
from qudi.core.configoption import ConfigOption


class FakeTimeTagger(TimeTaggerInterface):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

    def on_activate(self):
        return True

    def on_deactivate(self):
        return True

    def connect_tagger(self, position):
        return

    def get_counts(self, avg_time=0):
        print("getting counts from time tagger")
        time.sleep(avg_time)
        return
