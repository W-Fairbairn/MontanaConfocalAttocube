# -*- coding: utf-8 -*-
"""
This module is responsible for performing scanning probe measurements in order to find some optimal
position and move the scanner there.

Copyright (c) 2021, the qudi developers. See the AUTHORS.md file at the top-level directory of this
distribution and on <https://github.com/Ulm-IQO/qudi-iqo-modules/>

This file is part of qudi.

Qudi is free software: you can redistribute it and/or modify it under the terms of
the GNU Lesser General Public License as published by the Free Software Foundation,
either version 3 of the License, or (at your option) any later version.

Qudi is distributed in the hope that it will be useful, but WITHOUT ANY WARRANTY;
without even the implied warranty of MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.
See the GNU Lesser General Public License for more details.

You should have received a copy of the GNU Lesser General Public License along with qudi.
If not, see <https://www.gnu.org/licenses/>.
"""
import time
from multiprocessing.connection import Client

import numpy as np
from PySide2 import QtCore
import itertools
import copy as cp

from qudi.core.module import LogicBase
from qudi.util.mutex import RecursiveMutex, Mutex
from qudi.core.connector import Connector
from qudi.core.statusvariable import StatusVar
from qudi.util.fit_models.gaussian import Gaussian2D, Gaussian


class ScanningOptimizeLogic(LogicBase):
    """
    This module is responsible for performing scanning probe measurements in order to find some optimal
    position and move the scanner there.

    Example config for copy-paste:

    scanning_optimize_logic:
        module.Class: 'scanning_optimize_logic.ScanningOptimizeLogic'
        connect:
            scan_logic: scanning_probe_logic

    """

    # declare connectors
    _scan_logic = Connector(name='scan_logic', interface='ScanningProbeLogic')
    _z_stage = Connector(name='z_stage', interface='AttocubeStageInterface')
    _time_tagger = Connector(name='timetagger', interface='TimeTaggerInterface')

    # config options

    # status variables
    _scan_sequence = StatusVar(name='scan_sequence', default=None)
    _data_channel = StatusVar(name='data_channel', default=None)
    _scan_frequency = StatusVar(name='scan_frequency', default=None)
    _scan_range = StatusVar(name='scan_range', default=None)
    _scan_resolution = StatusVar(name='scan_resolution', default=None)

    # signals
    sigOptimizeStateChanged = QtCore.Signal(bool, dict, object)
    sigOptimizeSettingsChanged = QtCore.Signal(dict)

    #Alex's signals & vars for z stage
    sigZOptimizeUpdateGraph = QtCore.Signal(dict)
    sigZStageStartup = QtCore.Signal(float)


    _sigNextSequenceStep = QtCore.Signal()


    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        self._thread_lock = RecursiveMutex()
        self._result_lock = Mutex()

        self._stashed_scan_settings = dict()
        self._sequence_index = 0
        self._optimal_position = dict()
        self._last_scans = list()
        self._last_fits = list()

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        axes = self._scan_logic().scanner_axes
        channels = self._scan_logic().scanner_channels

        self.log.debug(f"Opt settings at startup, type {type(self._scan_range)} {self._scan_range, self._scan_resolution}")

        self._avail_axes = tuple(axes.values())
        if self._scan_sequence is None:
            if len(self._avail_axes) >= 3:
                self._scan_sequence = [(self._avail_axes[0].name, self._avail_axes[1].name),
                                       (self._avail_axes[2].name,)]
            elif len(self._avail_axes) == 2:
                self._scan_sequence = [(self._avail_axes[0].name, self._avail_axes[1].name)]
            elif len(self._avail_axes) == 1:
                self._scan_sequence = [(self._avail_axes[0].name,)]
            else:
                self._scan_sequence = list()


        if self._data_channel is None:
            self._data_channel = tuple(channels.values())[0].name
        print(self._data_channel)
        # check nd correct optimizer settings loaded from StatusVar
        new_settings = self.check_sanity_optimizer_settings(self.optimize_settings)
        if new_settings != self.optimize_settings:
            self._scan_range = new_settings['scan_range']
            self._scan_resolution = new_settings['scan_resolution']
            self._scan_frequency = new_settings['scan_frequency']

        self._stashed_scan_settings = dict()
        self._sequence_index = 0
        self._optimal_position = dict()
        self._last_scans = list()
        self._last_fits = list()

        self._sigNextSequenceStep.connect(self._next_sequence_step, QtCore.Qt.QueuedConnection)
        self._scan_logic().sigScanStateChanged.connect(
            self._scan_state_changed, QtCore.Qt.QueuedConnection
        )

        #z stage vars
        self.z_stage_opti_true = False

    def on_deactivate(self):
        """ Reverse steps of activation
        """
        self._scan_logic().sigScanStateChanged.disconnect(self._scan_state_changed)
        self._sigNextSequenceStep.disconnect()
        self.stop_optimize()
        return

    @property
    def data_channel(self):
        return self._data_channel

    @property
    def scan_frequency(self):
        return self._scan_frequency.copy() if self._scan_frequency!=None else None

    @property
    def scan_range(self):
        return self._scan_range.copy() if self._scan_range!=None else None

    @property
    def scan_resolution(self):
        return self._scan_resolution.copy() if self._scan_resolution!= None else None

    @property
    def scan_sequence(self):
        # serialization into status variable changes step type <tuple> -> <list>
        return [tuple(el) for el in self._scan_sequence]

    @scan_sequence.setter
    def scan_sequence(self, sequence):
        """
        @param sequence: list of string tuples giving the scan order, eg. [('x','y'),('z')]
        """
        axs_flat = []
        list(axs_flat.extend(item) for item in sequence)
        avail_axes = [ax.name for ax in self._avail_axes]
        if not all(elem in avail_axes for elem in axs_flat):
            raise ValueError(f"Optimizer sequence {sequence} must contain only"
                             f" available axes ({avail_axes})")

        self._scan_sequence = sequence

    @property
    def optimizer_running(self):
        return self.module_state() != 'idle'

    @property
    def optimize_settings(self):
        return {'scan_frequency': self.scan_frequency,
                'data_channel': self._data_channel,
                'scan_range': self.scan_range,
                'scan_resolution': self.scan_resolution,
                'scan_sequence': self.scan_sequence}

    @property
    def last_scans(self):
        with self._result_lock:
            return self._last_scans.copy()

    @property
    def last_fits(self):
        with self._result_lock:
            return self._last_fits.copy()

    def check_sanity_optimizer_settings(self, settings=None, plot_dimensions=None):
        # shaddows scanning_probe_logic::check_sanity. Unify code somehow?

        if not isinstance(settings, dict):
            settings = self.optimize_settings

        settings = cp.deepcopy(settings)
        hw_axes = self._scan_logic().scanner_axes
        sig_channels = self._scan_logic().scanner_channels

        def check_valid(settings, key):
            is_valid = True  # non present key -> valid
            if key in settings:
                if not isinstance(settings[key], dict):
                    is_valid = False
                else:
                    axes = settings[key].keys()
                    if axes != hw_axes.keys():
                        is_valid = False

            return is_valid

        # first check settings that are defined per scanner axis
        for key, val in settings.items():
            if not check_valid(settings, key):
                if key == 'scan_range':
                    settings['scan_range'] = {ax.name: abs(ax.value_range[1] - ax.value_range[0]) / 100 for ax in
                                              hw_axes.values()}
                if key == 'scan_resolution':
                    settings['scan_resolution'] = {ax.name: max(ax.min_resolution, min(16, ax.max_resolution))
                                                   for ax in hw_axes.values()}
                if key == 'scan_frequency':
                    settings['scan_frequency'] = {ax.name: max(ax.min_frequency, min(50, ax.max_frequency)) for ax
                                                  in hw_axes.values()}
                if key == 'data_channel':
                    settings['data_channel'] = list(sig_channels.keys())[0]

        # scan_sequence check, only sensibel if plot dimensions (eg. from confocal gui) are available
        if 'scan_sequence' in settings and plot_dimensions:
            dummy_seq = OptimizerScanSequence(tuple(self._scan_logic().scanner_axes.keys()),
                                              plot_dimensions)

            if len(dummy_seq.available_opt_sequences) == 0:
                raise ValueError(f"Configured optimizer dim= {plot_dimensions}"
                                 f" doesn't yield any sensible scan sequence.")

            if settings['scan_sequence'] not in [seq.sequence for seq in dummy_seq.available_opt_sequences]:
                new_seq = dummy_seq.available_opt_sequences[0].sequence
                settings['scan_sequence'] = new_seq

            if len(settings['scan_sequence']) != len(plot_dimensions):
                self.log.warning(f"Configured optimizer dim= {plot_dimensions}"
                                 f" doesn't fit the available sequences.")

        return settings

    @property
    def optimal_position(self):
        return self._optimal_position.copy()

    def set_optimize_settings(self, settings):
        """
        """
        with self._thread_lock:
            if self.module_state() != 'idle':
                settings_update = self.optimize_settings
                self.log.error('Can not change optimize settings when module is locked.')
            else:
                settings_update = dict()
                if 'scan_frequency' in settings:
                    self._scan_frequency.update(settings['scan_frequency'])
                    settings_update['scan_frequency'] = self.scan_frequency
                if 'data_channel' in settings:
                    self._data_channel = settings['data_channel']
                    settings_update['data_channel'] = self._data_channel
                if 'scan_range' in settings:
                    self._scan_range.update(settings['scan_range'])
                    settings_update['scan_range'] = self.scan_range
                if 'scan_resolution' in settings:
                    self._scan_resolution.update(settings['scan_resolution'])
                    settings_update['scan_resolution'] = self.scan_resolution
                if 'scan_sequence' in settings:
                    self.scan_sequence = settings['scan_sequence']
                    settings_update['scan_sequence'] = self.scan_sequence

            self.sigOptimizeSettingsChanged.emit(settings_update)
            return settings_update

    def toggle_optimize(self, start):
        if start:
            return self.start_optimize()
        return self.stop_optimize()

    def start_optimize(self):
        with self._thread_lock:
            if self.module_state() != 'idle':
                self.sigOptimizeStateChanged.emit(True, dict(), None)
                return 0

            # ToDo: Sanity checks for settings go here
            self.module_state.lock()
            with self._result_lock:
                self._last_scans = list()
                self._last_fits = list()
            self.sigOptimizeStateChanged.emit(True, dict(), None)

            # stash old scanner settings
            self._stashed_scan_settings = self._scan_logic().scan_settings

            # Set scan ranges
            curr_pos = self._scan_logic().scanner_target
            optim_ranges = {ax: (pos - self._scan_range[ax] / 2, pos + self._scan_range[ax] / 2) for
                            ax, pos in curr_pos.items()}
            actual_setting = self._scan_logic().set_scan_range(optim_ranges)
            # FIXME: Comparing floats by inequality here
            if any(val != optim_ranges[ax] for ax, val in actual_setting.items()):
                self.log.warning('Some optimize scan ranges have been changed by the scanner.')
                self.module_state.unlock()
                self.set_optimize_settings(
                    {'scan_range': {ax: abs(r[1] - r[0]) for ax, r in actual_setting.items()}}
                )
                self.module_state.lock()

            # Set scan frequency
            actual_setting = self._scan_logic().set_scan_frequency(self._scan_frequency)
            # FIXME: Comparing floats by inequality here
            if any(val != self._scan_frequency[ax] for ax, val in actual_setting.items()):
                self.log.warning('Some optimize scan frequencies have been changed by the scanner.')
                self.module_state.unlock()
                self.set_optimize_settings({'scan_frequency': actual_setting})
                self.module_state.lock()

            # Set scan resolution
            actual_setting = self._scan_logic().set_scan_resolution(self._scan_resolution)
            # FIXME: Comparing floats by inequality here
            if any(val != self._scan_resolution[ax] for ax, val in actual_setting.items()):
                self.log.warning(
                    'Some optimize scan resolutions have been changed by the scanner.')
                self.module_state.unlock()
                self.set_optimize_settings({'scan_resolution': actual_setting})
                self.module_state.lock()

            # optimizer scans are never saved
            self._scan_logic().set_scan_settings({'save_to_history': False})

            self._sequence_index = 0
            self._optimal_position = dict()
            self.sigOptimizeStateChanged.emit(True, self.optimal_position, None)
            self._sigNextSequenceStep.emit()
            return 0

    def _next_sequence_step(self):
        try:
            address = ('localhost', 6000)
            self.conn = Client(address, authkey=b'secret password')
            self.conn.send('start')
            time.sleep(0.1)
        except Exception as e:
            print(e)
            print("No connection to client, wont stop pulsed measurement")

        with self._thread_lock:

            if self.module_state() == 'idle':
                return

            # Execute current sequence step. Steps handled by scan_logic are started here.
            seq_step = self._scan_sequence[self._sequence_index]

            # Special handling for z-stage based optimization step.
            if len(seq_step) == 1 and seq_step[0] == 'z':
                # Run z step and then continue with the next sequence element.
                # Keep the optimizer locked while running.
                self._run_z_stage_optimize_step()
                self._sequence_index += 1
                if self._sequence_index >= len(self._scan_sequence):
                    self.stop_optimize()
                else:
                    self._sigNextSequenceStep.emit()
                return

            if self._scan_logic().toggle_scan(True, seq_step, self.module_uuid) < 0:
                self.log.error('Unable to start {0} scan. Optimize aborted.'.format(seq_step))
                self.stop_optimize()
            return

    def _scan_state_changed(self, is_running, data, caller_id):
        with self._thread_lock:
            if is_running or self.module_state() == 'idle' or caller_id != self.module_uuid:
                return
            elif data is not None:
                #self.log.debug(f"Trying to fit on data after scan of dim {data.scan_dimension}")

                try:
                    if data.scan_dimension == 1:
                        x = np.linspace(*data.scan_range[0], data.scan_resolution[0])
                        opt_pos, fit_data, fit_res = self._get_pos_from_1d_gauss_fit(
                            x,
                            data.data[self._data_channel]
                        )
                    else:
                        x = np.linspace(*data.scan_range[0], data.scan_resolution[0])
                        y = np.linspace(*data.scan_range[1], data.scan_resolution[1])
                        xy = np.meshgrid(x, y, indexing='ij')
                        opt_pos, fit_data, fit_res = self._get_pos_from_2d_gauss_fit(
                            xy,
                            data.data[self._data_channel].ravel()
                        )

                    position_update = {ax: opt_pos[ii] for ii, ax in enumerate(data.scan_axes)}
                    #self.log.debug(f"Optimizer issuing position update: {position_update}")
                    if fit_data is not None:
                        new_pos = self._scan_logic().set_target_position(position_update, move_blocking=True)
                        for ax in tuple(position_update):
                            position_update[ax] = new_pos[ax]

                        fit_data = {'fit_data': fit_data, 'full_fit_res': fit_res}

                    self._optimal_position.update(position_update)
                    with self._result_lock:
                        self._last_scans.append(data.copy())
                        self._last_fits.append(fit_res)
                    self.sigOptimizeStateChanged.emit(True, position_update, fit_data)

                    # Abort optimize if fit failed
                    if fit_data is None:
                        self.log.warning("Stopping optimization due to failed fit.")
                        self.stop_optimize()
                        return

                except:
                    self.log.exception("")

            self._sequence_index += 1

            # Continue optimizer sequence if there are steps left.
            if self._sequence_index >= len(self._scan_sequence):
                self.stop_optimize()
            else:
                self._sigNextSequenceStep.emit()
            return

    def _run_z_stage_optimize_step(self):
        """Run a z-stage based optimization step as part of the configured scan_sequence.

        This wraps the existing custom z-stage scan and emits optimizer updates in the same style
        as the scanner-based steps so the GUI can reflect the selected sequence order.
        """
        # Keep old behavior (including start/stop messaging) but don't unlock the optimizer module.
        try:
            self.start_z_stage_optimize()
        except Exception:
            self.log.exception('Z-stage optimization step failed.')
            # Emit a failed fit so the GUI can indicate invalid optimization.
            try:
                self.sigOptimizeStateChanged.emit(True, {'z': self._z_stage().get_position(1)}, None)
            except Exception:
                self.sigOptimizeStateChanged.emit(True, dict(), None)
            # Abort sequence on failure.
            self.stop_optimize()


    def z_scan(self, pos, times_to_avg):
        x_data = []
        y_data = []
        y_data_avg = []
        for x in pos:
            x_data.append(self._z_stage().get_position(1))
            for i in range(times_to_avg):
                t0 = time.time()
                self._z_stage().move_absolute(x)
                #print("time to move to position", time.time() - t0)
                y_data.append(self._time_tagger().get_counts())
                #print(self._time_tagger().get_counts())
            y_data_avg.append(np.median(y_data))
            y_data = []
        return x_data, y_data_avg

    def run_z_stage_scan_0_3000um(self, step_um=10.0, times_to_avg=3, dwell_time_s=0.0,
                                 start_um=0.0, stop_um=3000.0, reverse=False):
        """Run a simple Z scan by stepping the Attocube stage and reading counts.

        This is intended to feed a 1D plot (z vs counts) in the scanning GUI.

        Parameters
        ----------
        step_um : float
            Step size in µm.
        times_to_avg : int
            Number of count samples per point (median is used).
        dwell_time_s : float
            Optional dwell time between count samples.
        start_um, stop_um : float
            Scan range in µm.
        reverse : bool
            If True, scan from stop->start.

        Returns
        -------
        (np.ndarray, np.ndarray)
            z positions in meters and counts.
        """
        if times_to_avg < 1:
            times_to_avg = 1
        if step_um <= 0:
            raise ValueError('step_um must be > 0')

        start_m = float(start_um) * 1e-6
        stop_m = float(stop_um) * 1e-6
        step_m = float(step_um) * 1e-6

        # Build inclusive positions array
        if stop_m >= start_m:
            n = int(np.floor((stop_m - start_m) / step_m)) + 1
            pos = start_m + step_m * np.arange(n)
        else:
            n = int(np.floor((start_m - stop_m) / step_m)) + 1
            pos = start_m - step_m * np.arange(n)

        if reverse:
            pos = pos[::-1]

        x_data = []
        y_data_avg = []

        for z_target in pos:
            # Move stage to target z
            try:
                self._z_stage().move_absolute(float(z_target))
            except TypeError:
                # some implementations accept axis separately; fall back if needed
                self._z_stage().move_absolute(float(z_target))

            # Acquire counts multiple times and take median
            samples = []
            for _ in range(times_to_avg):
                try:
                    samples.append(float(self._time_tagger().get_counts()))
                except Exception:
                    self.log.exception('Failed to read counts from time_tagger')
                    samples.append(np.nan)
                if dwell_time_s and dwell_time_s > 0:
                    time.sleep(float(dwell_time_s))

            # Prefer the stage-reported position if available
            try:
                z_readback = float(self._z_stage().get_position(1))
            except Exception:
                try:
                    z_readback = float(self._z_stage().get_position())
                except Exception:
                    z_readback = float(z_target)

            x_data.append(z_readback)
            y_data_avg.append(float(np.nanmedian(samples)))

            opti_data = {'x': np.array(x_data, dtype=float), 'y': np.array(y_data_avg, dtype=float)}
            self.sigZOptimizeUpdateGraph.emit(opti_data)

        return np.array(x_data, dtype=float), np.array(y_data_avg, dtype=float)

    def fine_scan(self, v_forward, times_to_avg, DWELL_TIME):
        y_data_avg = []
        x_data_avg = []
        print("fine scan in z")
        for v in v_forward:
            self._z_stage().set_dc_voltage(1, v)
            y_data, x_data = [], []
            for i in range(times_to_avg):
                y_data.append(self._time_tagger().get_counts())
                x_data.append(self._z_stage().get_position(1))
                time.sleep(DWELL_TIME)
            y_data_avg.append(np.median(y_data))
            x_data_avg.append(np.mean(x_data))
            print("gonna output")
            print(y_data_avg)
            opti_data = {'x': np.array(x_data_avg), 'y': np.array(y_data_avg)}
            self.sigZOptimizeUpdateGraph.emit(opti_data)
        return x_data_avg, y_data_avg


    def start_z_stage_optimize(self):
        self.z_stage_opti_true = True
        print("z scan start")
        self._z_stage().set_dc_voltage(1, 0)
        print("dc voltage set to 0v")
        # move attocube stage using attocube hardware connection and read counts using time tagger connection
        #Get current position of z stage
        curr_pos = self._z_stage().get_position(1)
        print("1")
        print(curr_pos)
        #self.sigOptimizeStateChanged.emit(False, {'z': curr_pos}, 0)
        #optim_ranges = [curr_pos - self._scan_range['z'] / 2, curr_pos + self._scan_range['z'] / 2]
        print(self._scan_range['z'])
        #self._scan_logic().set_scan_range({'z' : optim_ranges})
        print("1")
        #generate some made up data - replace this with time tagger readings
        '''
        mu, sigma = curr_pos, 10e-6  # mean and standard deviation
        pos = np.linspace(optim_ranges[0], optim_ranges[1], self._scan_resolution['z'])[::-1]
        vals = (1.0 / (np.sqrt(2.0 * np.pi) * sigma) * np.exp(-np.power((pos - mu) / sigma, 2.0) / 2))

        while abs(self._z_stage().get_position(1) - pos[0]) > 1e-7:
            self._z_stage().move_absolute(pos[0])
        x_data, y_data = self.z_scan(pos, 3)
        print("finished first z scan")
        
        self.sigZOptimizeUpdateGraph.emit(opti_data)

        
        print("best value", best_value[0])
        # self._scan_logic().set_target_position({'z': best_value[0]}, move_blocking=True)
        #print("scan target position set")
        #print(best_fit)
        #print(fit_result)
        max_count_x = x_data[np.argmax(y_data)]
        max_count = np.max(y_data)
        #print([x_data[:], y_data[:]])
        print("pos of max counts (",max_count,"): ", max_count_x)
        #move stage to best value
        while abs(self._z_stage().get_position(1) - max_count_x) > 1e-7:
            self._z_stage().move_absolute(max_count_x)

        print("running finer z scan", max_count_x-1E-6, max_count_x+1E-6)
        fine_pos = np.linspace(max_count_x-1E-6, max_count_x+1E-6, 500)[::-1]
        while abs(self._z_stage().get_position(1) - fine_pos[0]) > 1e-7:
            self._z_stage().move_absolute(fine_pos[0])
        fine_x_data, fine_y_data = self.z_scan(fine_pos, 2)
        #print([fine_x_data, fine_y_data])
        print("scanned")
        max_count = np.max(fine_y_data)
        print("looking for ", max_count, " counts at x = ", fine_x_data[np.argmax(fine_y_data)])
        

        while abs(self._z_stage().get_position(1) - fine_x_data[0]) > 1e-7:
            self._z_stage().move_absolute(fine_x_data[0])
        pos2 = np.linspace(max_count_x-1.5e-6, max_count_x+1.5e-6, 300)[::-1]
        found = False
        count_arr = []
        #while not found:
        for x in pos:
            for i in range(3):
                t0 = time.time()
                self._z_stage().move_absolute(x)
                # print("time to move to position", time.time() - t0)
                count_arr.append(self._time_tagger().get_counts())
                # print(self._time_tagger().get_counts())
            counts = np.median(count_arr)
            count_arr = []
            if counts >= max_count*0.95:
                found = True
                print("max counts found")
                break
        if not found:
            print("max counts not found")
            self._z_stage().move_absolute(max_count_x)
            print("found:", found)
        '''
        SCAN_RANGE_UM = self._scan_range['z']*1E6  # microns
        NUM_POINTS = self._scan_resolution['z']  # resolution of scan
        DWELL_TIME = 0.02  # seconds per point (~50 Hz scan)
        times_to_avg = 10
        print(self._scan_range['z'])
        scan_range_volts = self._z_stage().um_to_volts(SCAN_RANGE_UM)
        print(curr_pos - self._scan_range['z'] / 2)
        if scan_range_volts > 60:
            scan_range_volts = 60
        print("scanning z over ", SCAN_RANGE_UM, " um")
        v_forward = np.linspace(0, scan_range_volts, NUM_POINTS)
        print("made array")
        print("moving to ", curr_pos - self._scan_range['z'] / 2)
        self._z_stage().move_absolute(curr_pos - self._scan_range['z'] / 2)
        time.sleep(0.5)
        x, y = self.fine_scan(v_forward, times_to_avg, DWELL_TIME)

        self._z_stage().set_dc_voltage(1, v_forward[np.argmax(y)])

        opti_data = {'x': np.array(x), 'y': np.array(y)}
        best_value, best_fit, fit_result = self._get_pos_from_1d_gauss_fit(opti_data['x'], opti_data['y'])
        test = {'fit_data': best_fit, 'full_fit_res': fit_result}
        self.sigOptimizeStateChanged.emit(False, {'z': self._z_stage().get_position(1)}, test)
        print("sig optimize state emitted")
        self.z_stage_opti_true = False
        try:
            self.conn.send('stop')
            print("sent message to client to start pulsed measurement")
        except Exception as e:
            print(e)
            print("failed to send message to client to start pulsed measurement")
        return

    def z_stage_startup_procedure(self):
        # get settings and current parameters so that on startup the ui is updated with stage current position
        curr_pos = self._z_stage().get_position(1)
        print("start up optimize logic", curr_pos)
        self.sigZStageStartup.emit(curr_pos)
        return

    def stop_optimize(self):
        """Stop the optimizer, stop any running scanner scan, restore stashed scan settings, and unlock."""
        with self._thread_lock:
            if self.module_state() == 'idle':
                self.sigOptimizeStateChanged.emit(False, dict(), None)
                return 0

            # Stop scan_logic scan if still running
            try:
                if self._scan_logic().module_state() != 'idle':
                    err = self._scan_logic().stop_scan()
                else:
                    err = 0
            except Exception:
                self.log.exception('Failed to stop scan_logic scan')
                err = -1

            # Restore previous scan settings
            if self._stashed_scan_settings:
                try:
                    self._scan_logic().set_scan_settings(self._stashed_scan_settings)
                except Exception:
                    self.log.exception('Failed to restore stashed scan settings')
            self._stashed_scan_settings = dict()

            # Unlock optimizer module
            try:
                self.module_state.unlock()
            except Exception:
                pass

            self.sigOptimizeStateChanged.emit(False, dict(), None)
            return err

    def _get_pos_from_2d_gauss_fit(self, xy, data):
        """Fit a 2D Gaussian and return (optimal_position, best_fit, fit_result)."""
        model = Gaussian2D()
        try:
            fit_result = model.fit(data, x=xy, **model.estimate_peak(data, xy))
        except Exception:
            x_min, x_max = xy[0].min(), xy[0].max()
            y_min, y_max = xy[1].min(), xy[1].max()
            x_middle = (x_max - x_min) / 2 + x_min
            y_middle = (y_max - y_min) / 2 + y_min
            self.log.exception('2D Gaussian fit unsuccessful.')
            return (x_middle, y_middle), None, None

        return (
            (fit_result.best_values['center_x'], fit_result.best_values['center_y']),
            fit_result.best_fit.reshape(xy[0].shape),
            fit_result,
        )

    def _prep_1d_fit_xy(self, x, y):
        """Sanitize 1D fit data.

        - removes NaN/inf
        - sorts by x
        - merges duplicate x by taking median y
        """
        x = np.asarray(x, dtype=float)
        y = np.asarray(y, dtype=float)
        m = np.isfinite(x) & np.isfinite(y)
        x = x[m]
        y = y[m]
        if x.size < 3:
            return x, y

        order = np.argsort(x)
        x = x[order]
        y = y[order]

        # Merge duplicates in x (stage readback can repeat)
        ux, inv = np.unique(x, return_inverse=True)
        if ux.size != x.size:
            y_med = np.zeros_like(ux, dtype=float)
            for i in range(ux.size):
                y_med[i] = float(np.nanmedian(y[inv == i]))
            x, y = ux, y_med

        return x, y

    def _smooth_1d(self, y, window=7):
        """Light smoothing for peak finding; keeps length identical."""
        y = np.asarray(y, dtype=float)
        if y.size < 3:
            return y
        w = int(max(3, window))
        if w % 2 == 0:
            w += 1
        if w > y.size:
            w = y.size if y.size % 2 == 1 else y.size - 1
        if w < 3:
            return y
        kernel = np.ones(w, dtype=float) / w
        pad = w // 2
        ypad = np.pad(y, (pad, pad), mode='edge')
        return np.convolve(ypad, kernel, mode='valid')

    def _get_pos_from_1d_gauss_fit(self, x, data):
        """Fit a 1D Gaussian and return (optimal_position, best_fit, fit_result).

        This version is tuned to be robust for z-stage focus scans:
        - sanitize x/y
        - use smoothed argmax as center guess
        - apply reasonable bounds
        - apply weights that emphasize the peak region
        - fall back to argmax if fit is unreliable
        """
        x, data = self._prep_1d_fit_xy(x, data)
        if x.size < 3:
            if x.size == 0:
                return (0.0,), None, None
            return (float(x[np.argmax(data)]),), None, None

        y = np.asarray(data, dtype=float)

        # Robust initial center guess
        y_smooth = self._smooth_1d(y, window=min(11, max(3, (y.size // 15) * 2 + 1)))
        center0 = float(x[int(np.nanargmax(y_smooth))])

        # Estimate a reasonable sigma from scan span (fallback)
        span = float(np.max(x) - np.min(x))
        if span <= 0:
            return (center0,), None, None
        dx = float(np.min(np.diff(x))) if x.size > 1 else span
        sigma_min = max(dx, span / max(10.0, y.size))
        sigma_max = max(sigma_min * 2, span / 2.0)

        # Weights: emphasize region around the expected peak
        wscale = max(span / 6.0, sigma_min)
        weights = 1.0 / (1.0 + ((x - center0) / wscale) ** 2)

        model = Gaussian()
        try:
            # Start with model defaults then tighten bounds
            p0 = model.estimate_peak(y, x)
            p0['center'] = center0
            # Build lmfit Parameters from p0 by doing a quick fit with bounds
            fit_result = model.fit(
                y,
                x=x,
                weights=weights,
                center=(center0, float(np.min(x)), float(np.max(x))),
                sigma=(p0.get('sigma', span / 6.0), sigma_min, sigma_max),
                amplitude=(max(float(np.nanmax(y) - np.nanmedian(y)), 0.0), 0.0, None),
                offset=(float(np.nanmedian(y)), float(np.nanpercentile(y, 1)), float(np.nanpercentile(y, 99))),
            )
        except Exception:
            self.log.exception('1D Gaussian fit unsuccessful; falling back to argmax.')
            return (center0,), None, None

        center = float(fit_result.best_values.get('center', center0))
        sigma = float(fit_result.best_values.get('sigma', sigma_min))

        # Quality gates / fallback
        if (not getattr(fit_result, 'success', True)) or not (np.min(x) <= center <= np.max(x)):
            return (center0,), None, fit_result
        if sigma <= sigma_min * 1.01 or sigma >= sigma_max * 0.99:
            # sigma pinned to bounds -> unstable fit
            return (center0,), None, fit_result

        return (center,), fit_result.best_fit, fit_result

class OptimizerScanSequence:
    def __init__(self, axes, dimensions=None, sequence=None):
        self._avail_axes = axes
        self._optimizer_dim = [2, 1] if dimensions is None else dimensions
        self._sequence = None
        if sequence in self._available_opt_seqs_raw():
            self.sequence = sequence

    def __eq__(self, other):
        if isinstance(other, OptimizerScanSequence):
            return self._sequence == other._sequence
        return False

    def __str__(self):
        out_str = ""
        if self.sequence:
            for step in self._sequence:
                if len(step) == 1:
                    out_str += f"{step[0]}"
                elif len(step) == 2:
                    out_str += f"{step[0]}{step[1]}"
                else:
                    raise ValueError
                out_str += ", "

            out_str = out_str.rstrip(', ')

        return out_str

    def __len__(self):
        if not self.sequence:
            return 0
        return len(self.sequence)

    @property
    def sequence(self):
        """
        @return: list of tuples
        """

        return self._sequence

    @sequence.setter
    def sequence(self, sequence):
        """
        @param sequence: list of tuples, eg. [('x','y'), ('z')]
        """
        if not sequence in self._available_opt_seqs_raw():
            raise ValueError(f"Given {sequence} sequence incompatible with axes= {self._avail_axes}, dims= {self._optimizer_dim}")

        self._sequence = sequence

    @property
    def available_opt_sequences(self):
        """
        Based on the given plot dimensions and axes configuration, give all possible permutations of scan sequences.
        """

        return [OptimizerScanSequence(self._avail_axes, self._optimizer_dim, seq) for seq in self._available_opt_seqs_raw()]

    def _available_opt_seqs_raw(self, remove_1d_in_2d=True):
        """
        @oaram remove_1d_in_2d: remove sequences where 1d steps are repeated in 2d steps, eg. [('x','y'), ('x')]
        """
        def get_n_in(comb_list, seq_step):
            if type(seq_step) != tuple:
                raise ValueError

            n_in = 0
            for old_step in comb_list:
                if type(old_step) != tuple:
                    raise ValueError
                if old_step == seq_step:
                    n_in += 1
                    continue
                if len(old_step) == 2 and len(seq_step) == 2:
                    if old_step[0] == seq_step[1] and old_step[1] == seq_step[0]:
                        n_in += 1
                        continue
            return n_in

        def add_comb(old_comb, new_seqs):
            out_comb = []

            for old_list in old_comb:
                for seq in new_seqs:
                    out_comb.append(combine(old_list, seq))

            if not old_comb:
                return [[seq] for seq in new_seqs]
            if not out_comb:
                return old_comb

            # clean doubles within combination
            out_clean = []
            for comb in out_comb:
                out_clean.append([el for el in comb if get_n_in(comb, el) == 1])
            out_comb = [el for el in out_clean if len(el) == len(out_comb[0])]

            return out_comb

        def combine(in1, in2):

            in1 = cp.deepcopy(in1)
            in2 = cp.deepcopy(in2)

            if type(in1) == str:
                in1 = tuple(in1)
            if type(in2) == str:
                in2 = tuple(in2)

            if type(in1) == list and type(in2) == list:
                in1.extend(in2)
                return in1
            elif type(in1) != list and type(in2) == list:
                in2.insert(0, in1)
                return in2
            elif type(in1) == list and type(in2) != list:
                in1.append(in2)
                return in1
            else:
                return [in1, in2]

        def remove_duplicates(comb_list):
            out_seqs = []
            for seq in comb_list:
                if seq not in out_seqs:
                    out_seqs.append(seq)

            return out_seqs

        def remove_1d_in_2d_axes_dupl(comb_list):
            out_seqs = []
            for seq in comb_list:
                is_1d_in_2d = False
                for step in seq:
                    if type(step) == tuple and len(step) == 1:
                        # if 1d step, check whether in any of the other 2 stpes
                        is_step_in = any([step[0] in s for s in seq if type(s)==tuple and len(s)==2])
                        if is_step_in:
                            is_1d_in_2d = True

                if not is_1d_in_2d:
                    out_seqs.append(seq)
            return out_seqs

        combs_2d = list(itertools.combinations(self._avail_axes, 2))
        combs_1d = list(itertools.combinations(self._avail_axes, 1))
        out_seqs = []

        for dim in self._optimizer_dim:
            if dim == 1:
                out_seqs = add_comb(out_seqs, combs_1d)
            elif dim == 2:
                out_seqs = add_comb(out_seqs, combs_2d)
            else:
                raise ValueError("Only support 1d and 2d optimization sequences.")

        # add permutations
        out_seqs_any_order = []
        for seq in out_seqs:
            out_seqs_any_order.extend([list(el) for el in list(itertools.permutations(seq))])
        out_seqs = out_seqs_any_order
        # clean up
        out_seqs = remove_duplicates(out_seqs)
        if remove_1d_in_2d:
            out_seqs = remove_1d_in_2d_axes_dupl(out_seqs)

        return out_seqs
