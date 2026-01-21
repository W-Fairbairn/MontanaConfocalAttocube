import time
import numpy as np
from scipy.optimize import curve_fit
from PySide2 import QtCore

from qudi.util.mutex import RecursiveMutex
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.module import LogicBase

class PsatLogic(LogicBase):
    _aom = Connector(name='aom', interface='ProcessSetpointInterface')
    _time_tagger = Connector(name='timetagger', interface='TimeTaggerInterface')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)


    def on_activate(self):
        aom = self._aom
        print("psat logic activated!")

        self._aom().set_activity_state('ao3', True)


        #load power values from csv
        self.voltage_to_power_list = np.loadtxt("C:/Users/attocube/Desktop/power_to_voltage_data.txt")
        #print(self.voltage_to_power_list)
        return

    def on_deactivate(self):
        return

    def set_power(self, channel, power):
        print("Setting power to", power, "mW")
        #convert power to voltage
        voltage = self.power_to_voltage(power)
        #voltage = power
        print("converted to ", voltage, "volts")
        self._aom().set_setpoint(channel, voltage)
        return

    def get_power(self, channel):
        value = self.volt_to_power(self._aom().get_setpoint(channel))
        #convert voltage to power
        #print("Power is", value)
        return value

    def set_ni_voltage(self, channel, value):
        self._aom().set_setpoint(channel, value)
        return

    def volt_to_power(self, voltage):
        power = 0
        interp_voltage = np.linspace(0, max(self.voltage_to_power_list[:,0]), 10000)
        interp_power = np.interp(interp_voltage, self.voltage_to_power_list[:,0], self.voltage_to_power_list[:,1])
        for i in range(len(interp_voltage)):
            if abs(interp_voltage[i] - voltage) <= 0.01:
                power = interp_power[i]
                break
        return power

    def power_to_voltage(self, power):
        voltage = 0
        interp_power = np.linspace(0, max(self.voltage_to_power_list[:,1]), 10000)
        interp_voltage = np.interp(interp_power, self.voltage_to_power_list[:,1], self.voltage_to_power_list[:,0])
        #print(interp_voltage)
        #print(interp_voltage)
        for i in range(len(interp_power)):
            #print(abs(interp_power[i] - power), interp_voltage[i])
            if abs(interp_power[i] - power) <= 0.01:
                voltage = interp_voltage[i]
                break
        return voltage

    def psat_func(self, P, psat, I_at_inf):
        return I_at_inf*P/(psat + P)

    def psatRun(self):
        fluorescence_array = []
        power_array = []
        points = 30
        for i in range(points):
            power = (i/points)*np.max(self.voltage_to_power_list[:,1])
            print(i, power)
            power_array.append(power)
            #print(voltage, self.volt_to_power(voltage))
            self.set_power('ao3', power)
            print("real power: ",self.get_power('ao3'), "\n")
            if i == 0: time.sleep(0.9)
            time.sleep(0.5)
            counts = self._time_tagger().get_counts()
            fluorescence_array.append(counts)
            if counts >= 1e6:
                print("counts too high")
                self.set_power('ao3', 0)
                break
        popt, pcov = curve_fit(self.psat_func, power_array, fluorescence_array, p0=(5, np.max(fluorescence_array)))
        print(popt)
        psat_power = popt[0]
        self.set_power('ao3', psat_power)

        return fluorescence_array, power_array