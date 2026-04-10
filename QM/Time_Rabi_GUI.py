"""
        TIME RABI
The program consists in playing a mw pulse and measure the photon counts received by the SPCM
across varying mw pulse durations.
The sequence has a reference measurement window at the end of the laser pulse to normalize the photon counts.

The data is then post-processed to determine the pi pulse duration for the specified amplitude.

Prerequisites:
    - Ensure calibration of the different delays in the system (calibrate_delays).
    - Having updated the different delays in the configuration.
    - Having updated the NV frequency, labeled as "NV_IF_freq", in the configuration.
    - Set the desired pi pulse amplitude, labeled as "mw_amp_NV", in the configuration

Next steps before going to the next node:
    - Update the pi pulse duration, labeled as "mw_len_NV", in the configuration.
"""
from qm import QuantumMachinesManager
from qm.qua import *
from qm import SimulationConfig
import matplotlib.pyplot as plt
from configuration import *
from qualang_tools.results.data_handler import DataHandler
import pyqtgraph as pg
from PyQt5 import QtCore, QtWidgets, QtGui, uic
import os
import threading
import time
import numpy as np
from qudi.util.colordefs import QudiPalettePale as palette
from scipy.optimize import curve_fit
from Time_Rabi import Rabi


class RabiMainWindow(QtWidgets.QMainWindow):
    def __init__(self, gui_ref=None):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'GUI/rabi.ui')

        # load ui
        super().__init__()
        uic.loadUi(ui_file, self)

        self.setWindowTitle('Rabi Oscillation Measurement')
        # Set background to dark gray and text to white
        self.setStyleSheet("background-color: rgb(48, 47, 47); color: rgb(150, 150, 150);")
        self.setWindowIcon(QtGui.QIcon(os.path.join(this_dir, 'GUI/assets/icon.jpg')))
        self.gui_ref = gui_ref  # Reference to RabiGui
        return

    def closeEvent(self, event):
        if self.gui_ref is not None:
            self.gui_ref.handle_window_close()
        super(RabiMainWindow, self).closeEvent(event)


class RabiGui(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.running = False
        self._mw = RabiMainWindow(gui_ref=self)
        self.image = pg.PlotDataItem(np.array([]),
                                     np.array([]),
                                     pen=None,
                                     symbol='o',
                                     symbolPen=palette.c1,
                                     symbolBrush=palette.c1,
                                     symbolSize=3)

        self.fit_image = pg.PlotDataItem(np.array([]),
                                         np.array([]),
                                         pen=pg.mkPen(palette.c2, width=2))

        # Add the display item to the ViewWidget, which was defined in the UI file.
        self._mw.rabi_plot_PlotWidget.addItem(self.image)
        self._mw.rabi_plot_PlotWidget.addItem(self.fit_image)

        self._mw.rabi_plot_PlotWidget.setLabel(axis='left', text='Normalised Signal', units='normalised units')
        self._mw.rabi_plot_PlotWidget.setLabel(axis='bottom', text='Time', units='ns')
        self._mw.rabi_plot_PlotWidget.showGrid(x=True, y=True, alpha=0.8)
        self._mw.rabi_plot_PlotWidget.setBackground(pg.mkColor(48, 47, 47))  # Set background to dark gray

        # Style the textbox to match the plot widget color scheme
        bg_color = pg.mkColor(48, 47, 47)  # Dark gray background
        text_color = pg.mkColor(150, 150, 150)  # White text
        text_palette = QtGui.QPalette()
        text_palette.setColor(QtGui.QPalette.Base, bg_color)
        text_palette.setColor(QtGui.QPalette.Text, text_color)
        self._mw.fit_results_Text.setPalette(text_palette)

        # Style the toolbar to match the plot widget color scheme
        toolbar_palette = QtGui.QPalette()
        toolbar_palette.setColor(QtGui.QPalette.Button, bg_color)
        toolbar_palette.setColor(QtGui.QPalette.ButtonText, text_color)
        toolbar_palette.setColor(QtGui.QPalette.Window, bg_color)
        toolbar_palette.setColor(QtGui.QPalette.WindowText, text_color)
        self._mw.counting_control_ToolBar.setPalette(toolbar_palette)

        self._mw.run_rabi_Action.toggled.connect(self.run_toggled)
        self._mw.fit_rabi_Action.triggered.connect(self.fit_clicked)
        self._mw.save_rabi_Action.triggered.connect(self.save_clicked)

        # Initialize QTimer for plot updates
        self.plot_timer = QtCore.QTimer()
        self.plot_timer.timeout.connect(self.update_plot_data)
        self.plot_update_interval = 100  # Update plot every 100ms

    def run_toggled(self, run):
        if run:
            # Start the measurement in a separate thread
            self.running = True
            self.program_thread = threading.Thread(target=program.start_program, daemon=True)
            self.program_thread.start()
            # Start the QTimer for safe GUI updates from the Qt event loop
            self.plot_timer.start(self.plot_update_interval)
        else:
            self.running = False
            # Stop the timer
            self.plot_timer.stop()
            program.stop_program()

    def fit_clicked(self):
        x, y, text = program.fit()
        self.fit_image.setData(x, y)
        self._mw.fit_results_Text.setPlainText(text)
        pass

    def save_clicked(self):
        program.save_data()

    def show(self):
        self._mw.show()
        self._mw.activateWindow()
        self._mw.raise_()
        return

    def on_deactivate(self):
        self._mw.close()
        return

    def update_plot_data(self):
        """
        Update the plot data from the program.
        This method is called by QTimer at regular intervals and runs in the Qt event loop,
        so it's safe to update GUI elements directly without threading issues.
        """
        if self.running:
            try:
                x_data = program.get_x()
                y_data = program.get_y()
                if x_data is not None and y_data is not None:
                    self.image.setData(x_data, y_data)
            except Exception as e:
                print(f"Error updating plot data: {e}")


    def handle_window_close(self):
        # Save if there is data and not already saved
        if program.counts is not None and program.counts_ref is not None and program.iteration is not None:
            program.save_data()
        # Halt the job if running
        try:
            if hasattr(program, 'job') and program.job is not None:
                program.job.halt()
        except Exception as e:
            print(f"Error halting the job on window close: {e}")


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)
    program = Rabi()
    rabi_gui = RabiGui()
    rabi_gui.show()
    sys.exit(app.exec_())
