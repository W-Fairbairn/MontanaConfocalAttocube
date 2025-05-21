from qudi.interface.attocube_stage_interface import AttocubeStageInterface

class FakeAttocubeANC350(AttocubeStageInterface):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.z_pos = 0.0

    def on_activate(self):
        self.log.debug("FakeAttocubeANC350 activated.")
        return True

    def on_deactivate(self):
        self.log.debug("FakeAttocubeANC350 deactivated.")
        return True

    def move_absolute(self, position):
        print(f"[DUMMY STAGE] Moving fake attocube stage to Z position {position * 1e6:.2f} um")
        self.z_pos = position

    def get_position(self):
        return self.z_pos