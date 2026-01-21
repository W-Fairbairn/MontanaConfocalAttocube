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

    def move_absolute(self, position):
        #print(f"Moving attocube stage to Z position {position} m")
        # time.sleep(0.1) #fake stage movement wait time
        print("hi")
        self.atc1.setAxisOutput(1, 1, 0)
        print("hi")
        self.atc1.setTargetRange(1, 1e-6)
        print("hi")
        self.atc1.setTargetPosition(1, position)
        print("hi")
        self.atc1.startAutoMove(1, 1, 0)
        time.sleep(0.5)
        self.atc1.startAutoMove(1, 0, 0)
        '''print("hi")
        moving = 1
        target = 0
        while target == 0:
            connected, enabled, moving, target, eotFwd, eotBwd, error = self.atc1.getAxisStatus(1)  # find bitmask of status
            if target == 0:
                print('axis moving, currently at', self.atc1.getPosition(1))
            elif target == 1:
                print('axis arrived at', self.atc1.getPosition(1))
                self.atc1.startAutoMove(1, 0, 0)
            time.sleep(0.5)'''
        return

    def move_coarse(self, position):
        #print(f"Moving attocube stage to Z position {position} m")
        self.z_pos = position
        self.atc1.move_to(1, position, precision=0.5e-6)
        return

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