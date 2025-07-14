import time
import numpy as np
from PySide2 import QtCore

from qudi.util.mutex import RecursiveMutex
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.module import LogicBase

class PsatLogic(LogicBase):
    _Psat = Connector(name='psat', interface='ProcessSetpointInterface')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


    def on_activate(self):
        Psat = self._Psat
        print("psat logic activated!")

        self._Psat().set_activity_state('ao0', True)


        #load power values from csv
        self.voltage_to_power_list = np.array([[0, 1], [1, 3], [2, 4], [3, 4.5], [4, 4.7], [5, 4.8]])
        return

    def on_deactivate(self):
        return

    def set_power(self, channel, power):
        print("Setting power to", power)
        #convert power to voltage
        voltage = self.power_to_voltage(power)
        print("converted to ", voltage, "volts")
        self._Psat().set_setpoint(channel, voltage)
        return

    def get_power(self, channel):
        value = self._Psat().get_setpoint(channel)
        #convert voltage to power
        print("Power is", self.volt_to_power(value))
        return value

    def set_ni_voltage(self, channel, value):
        self._Psat().set_setpoint(channel, value)
        return

    def volt_to_power(self, voltage):
        power = 0
        interp_voltage = np.linspace(0, max(self.voltage_to_power_list[:,0]), 1000)
        interp_power = np.interp(interp_voltage, self.voltage_to_power_list[:,0], self.voltage_to_power_list[:,1])
        for i in range(len(interp_voltage)):
            if abs(interp_voltage[i] - voltage) <= 0.01:
                power = interp_power[i+1]
                break
        return power

    def power_to_voltage(self, power):
        voltage = 0
        interp_power = np.linspace(0, max(self.voltage_to_power_list[:,1]), 1000)
        interp_voltage = np.interp(interp_power, self.voltage_to_power_list[:,1], self.voltage_to_power_list[:,0])
        #print(interp_voltage)
        for i in range(len(interp_power)):
            #print(abs(interp_power[i] - power))
            if abs(interp_power[i] - power) <= 0.01:
                voltage = interp_voltage[i+1]
                break
        return voltage

    def psatRun(self):
        fluorescence_array = []
        power_array = []
        for i in range(10):
            voltage = i/10*np.max(self.voltage_to_power_list[:,0])
            power_array.append(self.volt_to_power(voltage))
            self.set_power('ao0', voltage)
            fluorescence_array.append(self.get_power('ao0'))

        return [fluorescence_array, power_array]