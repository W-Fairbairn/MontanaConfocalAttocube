"""
Base class for quantum experiments (Rabi, ODMR, etc.)
Defines the interface that all experiment classes must implement.
"""
from abc import ABC, abstractmethod
import inspect
import threading
from multiprocessing.connection import Listener
from pathlib import Path

import numpy as np
from qm.qua import *
from qualang_tools.results.data_handler import DataHandler

from MontanaConfocalAttocube.QM.configuration import *


class ExperimentBase(ABC):
    """
    Abstract base class for quantum measurement experiments.
    All experiment classes must inherit from this and implement the abstract methods.
    """

    SIGNAL_HOST = "localhost"
    SIGNAL_PORT = 6000
    SIGNAL_AUTHKEY = b"secret password"

    def __init__(self):
        self.conn = None
        self._signal_listener = None
        self._signal_listener_thread = None
        self._signal_listener_closed = False
        self.pause_toggled = False

    def start_signal_listener(self):
        listener_thread = getattr(self, "_signal_listener_thread", None)
        if listener_thread is not None and listener_thread.is_alive():
            return listener_thread

        self._signal_listener_closed = False
        self._signal_listener_thread = threading.Thread(target=self.receive_signal, daemon=True)
        self._signal_listener_thread.start()
        return self._signal_listener_thread

    def close_signal_listener(self):
        self._signal_listener_closed = True

        conn = getattr(self, "conn", None)
        if conn is not None:
            try:
                conn.close()
            except Exception as ex:
                print(f"Error closing signal connection: {ex}")
            finally:
                self.conn = None

        listener = getattr(self, "_signal_listener", None)
        if listener is not None:
            try:
                listener.close()
            except Exception as ex:
                print(f"Error closing signal listener: {ex}")
            finally:
                self._signal_listener = None

    def _handle_signal_message(self, msg) -> bool:
        if msg == "start":
            if getattr(self, "qm", None) is not None:
                self.qm.set_io1_value(True)
            print("Paused")
            return False
        if msg == "stop":
            if getattr(self, "qm", None) is not None:
                self.qm.set_io1_value(False)
            print("Resumed")
            return False
        if msg == "close":
            return True
        return False

    def toggle_scan(self):
        self.pause_toggled = not self.pause_toggled
        self.qm.set_io2_value(self.pause_toggled)

    def receive_signal(self):
        print("Thread: Sleeping until signal received...")
        address = (self.SIGNAL_HOST, self.SIGNAL_PORT)
        listener = Listener(address, authkey=self.SIGNAL_AUTHKEY)
        self._signal_listener = listener

        try:
            while True:
                try:
                    self.conn = listener.accept()
                    print("connection accepted from", listener.last_accepted)
                    msg = self.conn.recv()
                    print(msg)
                    if self._handle_signal_message(msg):
                        break
                except (OSError, EOFError) as ex:
                    if self._signal_listener_closed:
                        break
                    print(f"Error: {ex}")
                    break
                except Exception as ex:
                    print(f"Error: {ex}")
                    break
        finally:
            self.close_signal_listener()

    def enable_calibration_db_caching(self):
        from tinydb import TinyDB
        from tinydb.storages import JSONStorage
        from tinydb.middlewares import CachingMiddleware

        octave_config = getattr(self.qmm, "_octave_config", None)
        calibration_db = getattr(octave_config, "calibration_db", None) if octave_config else None
        if calibration_db is None:
            return

        db = getattr(calibration_db, "_db", None)
        if db is None or isinstance(db.storage, CachingMiddleware):
            return

        db.close()
        calibration_db._db = TinyDB(
            calibration_db._file_path, indent=4, separators=(",", ": "), storage=CachingMiddleware(JSONStorage)
        )

    def refocus_loop(self):
        io1_flag = declare(bool)
        io2_flag = declare(bool)
        assign(io1_flag, IO1)
        assign(io2_flag, IO2)
        with while_(io1_flag | io2_flag):  # refocusing loop
            play("laser_ON", "AOM2")
            wait(wait_for_initialization * u.ns, "AOM2")
            align()
            assign(io1_flag, IO1)
            assign(io2_flag, IO2)

    def _update_pulse_lengths_from_rabi_freq(self, rabi_frequency_mhz):
        # Determine π and π/2 pulse lengths in ns, snapped to 4 ns clock.
        two_pi_pulse = (1 / ((rabi_frequency_mhz * u.MHz))) / 1e-9  # noqa: F405
        pi_pulse = two_pi_pulse / 2
        pi_by_2 = pi_pulse / 2
        while pi_by_2 < 16:
            pi_pulse = pi_pulse + two_pi_pulse
            pi_by_2 = pi_by_2 + two_pi_pulse

        config["pulses"]["x180_pulse"]["length"] = pi_pulse // 4 * 4
        config["pulses"]["x90_pulse"]["length"] = (pi_by_2) // 4 * 4
        config["pulses"]["-x90_pulse"]["length"] = (pi_by_2) // 4 * 4
        config["pulses"]["x270_pulse"]["length"] = (pi_pulse * 1.5) // 4 * 4

    @abstractmethod
    def compile_program(self):
        """
        Compile the QUA program with current settings.
        Called before starting the experiment.
        """
        pass

    @abstractmethod
    def start_program(self):
        """
        Start the experiment execution.
        Should handle both simulation and real execution modes.
        """
        pass

    @abstractmethod
    def stop_program(self):
        """
        Stop the currently running experiment.
        Should gracefully halt the job and clean up resources.
        """
        pass

    @abstractmethod
    def get_x(self) -> np.ndarray:
        """
        Get the x-axis data for plotting.

        Returns:
            np.ndarray: X-axis data (time for Rabi, frequency for ODMR)
        """
        pass

    @abstractmethod
    def get_y(self) -> np.ndarray:
        """
        Get the y-axis data for plotting.

        Returns:
            np.ndarray: Y-axis data (normalized counts or intensity)
        """
        pass

    @abstractmethod
    def fit(self) -> tuple:
        """
        Fit the experimental data.

        Returns:
            tuple: (x_fit, y_fit, text_results)
                - x_fit: x-axis data for the fitted curve
                - y_fit: y-axis data for the fitted curve
                - text_results: string with fitting results and parameters
        """
        pass

    @abstractmethod
    def get_save_data(self) -> dict:
        """
        Build the dict of data to persist for this experiment, from current instance
        state (not from values captured earlier, e.g. at __init__ or compile time --
        build it fresh here so it can't go stale).

        Returns:
            dict: data to save, e.g. {"t_vec": self.t_vec, "counts_data": self.counts}.
                Return an empty dict if there is nothing to save (e.g. Counter).
        """
        pass

    @abstractmethod
    def get_save_name(self) -> str:
        """
        Name used for the saved-data folder, e.g. "rabi", "cw_odmr", "t1".
        """
        pass

    def save_data(self):
        """
        Shared save implementation for all experiments. Subclasses should not
        override this -- implement get_save_data() / get_save_name() instead.
        """
        data = self.get_save_data()
        if not data:
            return

        data.setdefault("config", config)

        data_handler = DataHandler(root_data_folder=save_dir)
        data_handler.save_data(data=data, name=self.get_save_name())

    @abstractmethod
    def get_plot_info(self) -> dict:
        """
        Return the axis labels and units.
        """
        pass
