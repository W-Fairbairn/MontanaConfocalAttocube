import time

from qudi.interface.attocube_stage_interface import AttocubeStageInterface
from qudi.core.configoption import ConfigOption

class FakeAttocubeANC350(AttocubeStageInterface):
    z_stage_range = ConfigOption(name='z_range', default=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.z_pos = 1278e-6

    def on_activate(self):
        self.log.debug("FakeAttocubeANC350 activated.")
        self.z_pos = self.get_position()
        return True

    def on_deactivate(self):
        self.log.debug("FakeAttocubeANC350 deactivated.")
        return True

    def move_absolute(self, position):
        print(f"[DUMMY STAGE] Moving fake attocube stage to Z position {position * 1e6:.2f} um")
        self.z_pos = position
        time.sleep(0.1) #fake stage movement wait time
        return

    def get_position(self):
        return self.z_pos