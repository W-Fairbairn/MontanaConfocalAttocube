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
import datetime
import numpy as np
from scipy.optimize import curve_fit
from PySide2 import QtCore

from qudi.util.mutex import RecursiveMutex
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.module import LogicBase
from qudi.util.datastorage import TextDataStorage
import TimeTagger as tt


def fit_func(t, A, B, tau1, tau2):
    return 1 - A * np.exp(-np.abs(t) / tau1) + B * np.exp(-np.abs(t) / tau2)


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
        self.hbt_fit_available = False
        self.coin = None

    def on_activate(self):
        """ Connect and configure the access to the FPGA.
        """
        self._number_of_gates = int(100)

        # Get the tagger from the connected hardware module (avoids singleton warning)
        self._tagger = self._time_tagger().tagger

        # Set channel number scheme to suppress deprecation warning
        tt.setTimeTaggerChannelNumberScheme(tt.TT_CHANNEL_NUMBER_SCHEME_ONE)

        # Do an initial setup/teardown to populate bin_times
        self._setup_measurement()
        self._close_measurement()

        self.g2_data = np.zeros_like(self.bin_times)
        self.g2_data_normalised = np.zeros_like(self.bin_times)
        self.fit_times = self.bin_times
        self.fit_g2 = np.zeros_like(self.fit_times)

        self.timer = QtCore.QTimer()
        self.timer.timeout.connect(self.update)

        self.sigStart.connect(self._start_hbt)
        self.sigStop.connect(self._stop_hbt)

    def _setup_measurement(self):
        self.coin = tt.Correlation(self._tagger, self._channel_apd_0, self._channel_apd_1,
                                   binwidth=self._bin_width, n_bins=self._n_bins)
        self.bin_times = self.coin.getIndex()

    def _close_measurement(self):
        if self.coin is not None:
            self.coin.stop()
            self.coin = None

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

    def fit_hbt(self):
        """Fit the current g2 data using the fit_func model."""
        if not self.hbt_available:
            self.log.warning('No HBT data available to fit.')
            return

        try:
            times_ns = self.bin_times / 1000.0  # convert ps to ns
            data = self.g2_data_normalised

            # Estimate initial parameters from data
            dip_depth = 1.0 - np.min(data)  # antibunching dip depth

            # Initial parameter guesses: A (dip depth), B (bunching), tau1, tau2
            p0 = [dip_depth, 0.1, 20.0, 100.0]
            bounds = ([0, 0, 0.1, 0.1],        # lower bounds
                      [2, 2, 1e5, 1e5])         # upper bounds
            popt, pcov = curve_fit(fit_func, times_ns, data, p0=p0,
                                   bounds=bounds, maxfev=10000)

            # Generate smooth fit curve
            self.fit_times = np.linspace(times_ns.min(), times_ns.max(), 2000)
            self.fit_g2 = fit_func(self.fit_times, *popt)
            # Convert fit_times back to ps to match bin_times units for GUI display
            self.fit_times = self.fit_times * 1000.0

            self.g2_0 = fit_func(0, *popt)
            self.hbt_fit_available = True
            self.log.info(f'HBT fit parameters: A={popt[0]:.4f}, B={popt[1]:.4f}, '
                          f'tau1={popt[2]:.4f} ns, tau2={popt[3]:.4f} ns, '
                          f'g2(0)={self.g2_0:.4f}')
            self.hbt_fit_updated.emit()
        except Exception as e:
            self.log.error(f'HBT fit failed: {e}')

    def _stop_hbt(self):
        if self.coin is not None:
            self._close_measurement()

        self.timer.stop()

    def save_hbt(self, tag=None):
        """Save the current HBT data and fit to file."""
        if not self.hbt_available:
            self.log.warning('No HBT data available to save.')
            return

        timestamp = datetime.datetime.now()
        metadata = {
            'Bin width (ps)': self._bin_width,
            'Number of bins': self._n_bins,
            'Channel APD 0': self._channel_apd_0,
            'Channel APD 1': self._channel_apd_1,
        }

        if self.hbt_fit_available:
            metadata['g2(0) fit'] = self.g2_0
            if self.g2_0 < 1.0:
                metadata['N = 1/(1-g2(0))'] = 1.0 / (1.0 - self.g2_0)

        tag = f'{tag}_' if tag else ''
        nametag = f'{tag}HBT'

        # Build data array: time (ns) | raw counts | normalised g2
        data = np.column_stack([
            self.bin_times / 1000.0,
            self.g2_data,
            self.g2_data_normalised
        ])
        column_headers = ['Time (ns)', 'Raw counts', 'g2(t) normalised']

        data_storage = TextDataStorage(root_dir=self.module_default_data_dir,
                                       column_formats='.15e')
        file_path, _, _ = data_storage.save_data(data,
                                                  metadata=metadata,
                                                  nametag=nametag,
                                                  timestamp=timestamp,
                                                  column_headers=column_headers,
                                                  column_dtypes=[float] * len(column_headers))

        # Save fit data alongside if available
        if self.hbt_fit_available:
            fit_data = np.column_stack([
                self.fit_times / 1000.0,
                self.fit_g2
            ])
            fit_headers = ['Time (ns)', 'g2(t) fit']
            data_storage.save_data(fit_data,
                                   metadata=metadata,
                                   nametag=f'{tag}HBT_fit',
                                   timestamp=timestamp,
                                   column_headers=fit_headers,
                                   column_dtypes=[float] * len(fit_headers))

        self.log.info(f'HBT data saved to: {file_path}')
        self.hbt_saved.emit()

    def on_deactivate(self):
        """ Reverse steps of activation

        @return int: error code (0:OK, -1:error)
        """
        return 0