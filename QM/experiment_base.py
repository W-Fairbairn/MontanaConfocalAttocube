"""
Base class for quantum experiments (Rabi, ODMR, etc.)
Defines the interface that all experiment classes must implement.
"""
from abc import ABC, abstractmethod
import numpy as np


class ExperimentBase(ABC):
    """
    Abstract base class for quantum measurement experiments.
    All experiment classes must inherit from this and implement the abstract methods.
    """

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
