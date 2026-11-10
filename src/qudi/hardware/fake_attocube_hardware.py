import time

from qudi.interface.attocube_stage_interface import AttocubeStageInterface
from qudi.core.configoption import ConfigOption


class FakeAttocubeANC350(AttocubeStageInterface):
    """ Dummy hardware module simulating a three-axis Attocube ANC350 stage.

    Example config for copy-paste:

    attocube_dummy:
        module.Class: 'fake_attocube_hardware.FakeAttocubeANC350'
        options:
            x_range: [-5000e-6, 5000e-6]
            y_range: [-5000e-6, 5000e-6]
            z_range: [-5000e-6, 5000e-6]
            step_size: 1e-6
    """

    x_range = ConfigOption(name='x_range', default=None)
    y_range = ConfigOption(name='y_range', default=None)
    z_range = ConfigOption(name='z_range', default=None)
    step_size = ConfigOption(name='step_size', default=1e-6)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._positions = {'x': 0.0, 'y': 0.0, 'z': 1278e-6}

    def on_activate(self):
        self.log.debug("FakeAttocubeANC350 activated.")
        return True

    def on_deactivate(self):
        self.log.debug("FakeAttocubeANC350 deactivated.")
        return True

    def get_axes(self):
        return tuple(self._positions.keys())

    def get_range(self, axis):
        return getattr(self, f'{axis}_range', None)

    def _check_axis(self, axis):
        if axis not in self._positions:
            raise ValueError(f"Unknown axis '{axis}'. Available axes: {tuple(self._positions)}")

    def move_absolute(self, axis, position):
        self._check_axis(axis)
        print(f"[DUMMY STAGE] Moving fake attocube {axis} axis to position {position * 1e6:.2f} um")
        self._positions[axis] = position
        time.sleep(0.1)  # fake stage movement wait time
        return

    def step(self, axis, backward=False):
        self._check_axis(axis)
        step = -self.step_size if backward else self.step_size
        self.move_absolute(axis, self._positions[axis] + step)
        return

    def get_position(self, axis):
        self._check_axis(axis)
        return self._positions[axis]

    def stop(self, axis):
        """Stop motion (dummy implementation)."""
        self._check_axis(axis)
        return
