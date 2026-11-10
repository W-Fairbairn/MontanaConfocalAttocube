import time
from qudi.interface.attocube_stage_interface import AttocubeStageInterface
from qudi.core.configoption import ConfigOption
from pyanc350.v4 import Positioner


class AttocubeANC350(AttocubeStageInterface):
    """ Hardware module for a multi-axis Attocube ANC350 controller.

    Example config for copy-paste:

    attocube:
        module.Class: 'attocube_controller.AttocubeANC350'
        options:
            axis_ids:
                x: 0
                y: 1
                z: 2
            x_range: [0e-6, 3500e-6]
            y_range: [0e-6, 3500e-6]
            z_range: [0e-6, 3500e-6]
    """

    axis_ids = ConfigOption(name='axis_ids', default={'x': 0, 'y': 1, 'z': 2})
    x_range = ConfigOption(name='x_range', default=None)
    y_range = ConfigOption(name='y_range', default=None)
    z_range = ConfigOption(name='z_range', default=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.atc1 = None
        self.MICRONS_PER_V = 0.05  # calibration: 25 nm/V (example!)

    def on_activate(self):
        self.log.debug("AttocubeANC350 activated.")
        try:
            self.atc1 = Positioner()
        except Exception as error:
            self.log.error(f"Could not connect to attocube: {error}")
            return True
        self.atc1.disconnect()
        self.atc1.connect()
        for axis in self.axis_ids:
            idx = self._axis_index(axis)
            self.atc1.setAmplitude(idx, 40)
            self.atc1.setFrequency(idx, 200)
        return True

    def on_deactivate(self):
        self.log.debug("AttocubeANC350 deactivated.")
        return True

    def get_axes(self):
        return tuple(self.axis_ids.keys())

    def get_range(self, axis):
        return getattr(self, f'{axis}_range', None)

    def _axis_index(self, axis):
        try:
            return self.axis_ids[axis]
        except KeyError:
            raise ValueError(f"Unknown axis '{axis}'. Configured axes: {tuple(self.axis_ids)}")

    def set_voltage(self, axis, voltage):
        self.atc1.setAmplitude(self._axis_index(axis), voltage)

    def _reconnect(self):
        """Try to recover from a pyanc350 communication timeout by reconnecting."""
        try:
            if self.atc1 is None:
                self.atc1 = Positioner()
            try:
                self.atc1.disconnect()
            except Exception:
                pass
            self.atc1.connect()
        except Exception:
            self.log.exception('AttocubeANC350 reconnect failed')

    def step(self, axis, backward=False):
        """Take one step on the given axis in the requested direction with reconnect/retry."""
        idx = self._axis_index(axis)
        backward = bool(backward)
        last_err = None
        for attempt in range(3):
            try:
                self.atc1.startSingleStep(idx, backward)
                return
            except Exception as exc:
                last_err = exc
                self.log.warning(f'Attocube step failed (attempt {attempt + 1}/3): {exc}')
                time.sleep(0.2)
                self._reconnect()
        raise last_err

    def move_absolute(self, axis, position):
        """Move the given axis to an absolute position in meters.

        Includes a couple of retries to handle transient comm timeouts.
        """
        idx = self._axis_index(axis)
        last_err = None
        for attempt in range(3):
            try:
                self.atc1.setAxisOutput(idx, 1, 0)
                self.atc1.setTargetRange(idx, 1e-6)
                self.atc1.setTargetPosition(idx, position)
                self.atc1.startAutoMove(idx, 1, 0)
                time.sleep(0.5)
                self.atc1.startAutoMove(idx, 0, 0)
                return
            except Exception as exc:
                last_err = exc
                self.log.warning(f'Attocube move_absolute failed (attempt {attempt + 1}/3): {exc}')
                time.sleep(0.2)
                self._reconnect()
        raise last_err

    def set_dc_voltage(self, channel, volt):
        self.atc1.setDcVoltage(channel, volt)

    def um_to_volts(self, um):
        return um / self.MICRONS_PER_V

    def volts_to_millivolts(self, v):
        return int(v * 1000)

    def get_position(self, axis):
        idx = self._axis_index(axis)
        try:
            pos = self.atc1.getPosition(idx)
        except Exception:
            pos = 0
        return pos

    def stop(self, axis):
        """Stop any ongoing motion on the given axis."""
        idx = self._axis_index(axis)
        try:
            if self.atc1 is None:
                return
            self.atc1.startAutoMove(idx, 0, 0)
        except Exception:
            self.log.exception('Failed to stop Attocube ANC350 motion')
