"""
This module performs an HBT and saves data appropriately

Qudi is free software: you can redistribute it and/or modify
it under the terms of the GNU General Public License as published by
the Free Software Foundation, either version 3 of the License, or
(at your option) any later version.

Qudi is distributed in the hope that it will be useful,
but WITHOUT ANY WARRANTY; without even the implied warranty of
MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
GNU General Public License for more details.

You should have received a copy of the GNU General Public License
along with Qudi. If not, see <http://www.gnu.org/licenses/>.

Copyright (c) the Qudi Developers. See the COPYRIGHT.txt file at the
top-level directory of this distribution and at <https://github.com/Ulm-IQO/qudi/>
"""
import time
import numpy as np
from scipy.optimize import curve_fit
from PySide2 import QtCore

from qudi.util.mutex import RecursiveMutex
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.module import LogicBase
import TimeTagger as tt

class HbtLogic(LogicBase):
    _time_tagger = Connector(name='timetagger', interface='TimeTaggerInterface')
    '''
    This is the logic for running HBT experiments
    '''
    _channel_apd_0 = ConfigOption(name='timetagger_channel_apd_0', missing='error')
    _channel_apd_1 = ConfigOption(name='timetagger_channel_apd_1', missing='error')
    _bin_width = ConfigOption(name='bin_width', default=800, missing='info')
    _n_bins = ConfigOption(name='bins', default=5000, missing='info')

    hbt_updated = QtCore.Signal()
    hbt_fit_updated = QtCore.Signal()
    hbt_saved = QtCore.Signal()
    sigStart = QtCore.Signal()
    sigStop = QtCore.Signal()

    def __init__(self, config, **kwargs):
        super().__init__(config=config, **kwargs)
        print("hbt logic setup")
        self.fit_times = []
        self.bin_times = []
        self.fit_g2 = []
        self.g2_data = []
        self.g2_data_normalised = []
        self.hbt_available = False
        self._setup_measurement()
        self._close_measurement()
        print(self.bin_times)

    def on_activate(self):
        """ Connect and configure the access to the FPGA.
        """
        self._number_of_gates = int(100)
        self.g2_data = np.zeros_like(self.bin_times)
        self.g2_data_normalised = np.zeros_like(self.bin_times)
        self.fit_times = self.bin_times
        self.fit_g2 = np.zeros_like(self.fit_times)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update)

        self.sigStart.connect(self._start_hbt)
        self.sigStop.connect(self._stop_hbt)

    def _setup_measurement(self):
        self._tagger = tt.createTimeTagger()
        self.coin = tt.Correlation(self._tagger, self._channel_apd_0, self._channel_apd_1,
                                   binwidth=self._bin_width, n_bins=self._n_bins)
        self.bin_times = self.coin.getIndex()

    def _close_measurement(self):
        self.coin.stop()
        self.coin = None
        self._tagger = None

    def start_hbt(self):
        self.sigStart.emit()

    def stop_hbt(self):
        self.sigStop.emit()

    def _start_hbt(self):
        self._setup_measurement()
        self.coin.clear()
        self.coin.start()
        self.timer.start(500)  # 0.5s

    def update(self):
        self.bin_times = self.coin.getIndex()
        self.g2_data = self.coin.getData()
        self.hbt_available = True
        lvl = np.mean(self.g2_data[0:100])
        if lvl > 0:
            self.g2_data_normalised = self.g2_data / lvl
        else:
            self.g2_data_normalised = np.zeros_like(self.g2_data)
        self.hbt_updated.emit()

    def pause_hbt(self):
        if self.coin is not None:
            self.coin.stop()

    def continue_hbt(self):
        if self.coin is not None:
            self.coin.start()

    def _stop_hbt(self):
        if self.coin is not None:
            self._close_measurement()

        self.timer.stop()
    def on_deactivate(self):
        """ Reverse steps of activation

        @return int: error code (0:OK, -1:error)
        """
        return 0