import time
from qudi.interface.attocube_stage_interface import AttocubeStageInterface
from qudi.core.configoption import ConfigOption
#from pylablib.devices import Attocube
from pyanc350.v4 import Positioner
class AttocubeANC350(AttocubeStageInterface):
    z_stage_range = ConfigOption(name='z_range', default=None)

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.atc1 = None
        self.z_pos = None
        self.MICRONS_PER_V = 0.05  # calibration: 25 nm/V (example!)

    def on_activate(self):
        self.log.debug("AttocubeANC350 activated.")
        try:
            self.atc1 = Positioner()
        except Exception as error:
            print("Could not connect to attocube", error)
        self.atc1.disconnect()
        self.atc1.connect()
        self.z_pos = self.get_position(1)
        self.atc1.setAmplitude(1, 40)
        self.atc1.setFrequency(1, 200)
        return True

    def on_deactivate(self):
        self.log.debug("AttocubeANC350 deactivated.")
        return True

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

    def step(self, backward):
        """Take one step in the requested direction with reconnect/retry."""
        last_err = None
        backward = bool(backward)
        for attempt in range(3):
            try:
                self.atc1.startSingleStep(1, backward)
                return
            except Exception as exc:
                last_err = exc
                self.log.warning(f'Attocube step failed (attempt {attempt + 1}/3): {exc}')
                time.sleep(0.2)
                self._reconnect()
        raise last_err

    def move_absolute(self, position):
        """Move Z axis to an absolute position in meters.

        Includes a couple of retries to handle transient comm timeouts.
        """
        last_err = None
        for attempt in range(3):
            try:
                self.atc1.setAxisOutput(1, 1, 0)
                self.atc1.setTargetRange(1, 1e-6)
                self.atc1.setTargetPosition(1, position)
                self.atc1.startAutoMove(1, 1, 0)
                time.sleep(0.5)
                self.atc1.startAutoMove(1, 0, 0)
                return
            except Exception as exc:
                last_err = exc
                # communication timeout recovery
                self.log.warning(f'Attocube move_absolute failed (attempt {attempt+1}/3): {exc}')
                time.sleep(0.2)
                self._reconnect()
        # If we get here, all retries failed
        raise last_err

    def set_dc_voltage(self, channel, volt):
        print("setting dc voltage to ", volt ," V")
        #print(f"Moving attocube stage to Z position {position} m")
        self.atc1.setDcVoltage(channel, volt)
        return

    def um_to_volts(self, um):
        return um / self.MICRONS_PER_V

    def volts_to_millivolts(self, v):
        return int(v * 1000)


    def get_position(self, axis):
        try:
            pos = self.atc1.getPosition(axis)
        except:
            pos = 0
        return pos

    def stop(self):
        """Stop any ongoing motion on the Z axis."""
        try:
            if self.atc1 is None:
                return
            self.atc1.startAutoMove(1, 0, 0)
        except Exception:
            self.log.exception('Failed to stop Attocube ANC350 motion')
        return
