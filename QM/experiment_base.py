"""
Base class for quantum experiments (Rabi, ODMR, etc.)
Defines the interface that all experiment classes must implement.
"""
from abc import ABC, abstractmethod
import threading
from multiprocessing.connection import Listener

import numpy as np
from qm.qua import *

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

    def refocus_loop(self):
        with while_(IO1):  # refocusing loop
            play("laser_ON", "AOM2")
            wait(wait_for_initialization * u.ns, "AOM2")
            align()

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
    def save_data(self):
        """
        Save the experimental data to disk.
        """
        pass

    @abstractmethod
    def get_plot_info(self) -> dict:
        """
        Return the axis labels and units.
        """
        pass
