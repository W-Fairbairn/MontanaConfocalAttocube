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
from qm.qua import *
import pyqtgraph as pg

from PyQt6 import QtCore, QtWidgets, QtGui, uic
from PyQt6.QtGui import QColor, QAction
from PyQt6.QtWidgets import QComboBox
from PyQt6.QtCore import QSettings

import os
import threading
import numpy as np
from qudi.util.colordefs import QudiPalettePale as palette
from Time_Rabi import Rabi
from Time_Rabi import SettingsDialogRabi
from CW_ODMR_GUI import CW_ODMR
from CW_ODMR_GUI import SettingsDialogODMR
from Counter import Counter
from Counter import SettingsDialogRabi as SettingsDialogCounter
from experiment_base import ExperimentBase
from styles import Colors, MAIN_WINDOW_STYLESHEET, PLOT_WIDGET_BG, get_textbox_palette, get_toolbar_palette
from experiment_base import ExperimentBase
from styles import Colors, MAIN_WINDOW_STYLESHEET, PLOT_WIDGET_BG, get_textbox_palette, get_toolbar_palette

# Initialize QSettings for persistent storage
settings = QSettings("Diamond", "QM_Experiment")


class MainWindow(QtWidgets.QMainWindow):
    # dynamically loaded UI elements
    rabi_plot_PlotWidget: pg.PlotWidget
    fit_results_Text: QtWidgets.QPlainTextEdit
    counting_control_ToolBar: QtWidgets.QToolBar
    run_rabi_Action: QAction
    fit_rabi_Action: QAction
    save_rabi_Action: QAction
    settings_Action: QAction

    def __init__(self, gui_ref=None, experiment="Rabi"):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'GUI/rabi.ui')

        # load ui
        super().__init__()
        uic.loadUi(ui_file, self)

        self.experiment = experiment
        self.update_window_title()
        # Set background to dark gray and text to white
        self.setStyleSheet(MAIN_WINDOW_STYLESHEET)
        self.setWindowIcon(QtGui.QIcon(os.path.join(this_dir, 'GUI/assets/icon.jpg')))
        self.gui_ref = gui_ref  # Reference to RabiGui
        return

    def update_window_title(self):
        """Update window title based on current experiment"""
        if self.experiment == "Rabi":
            self.setWindowTitle('Rabi Oscillation Measurement')
        elif self.experiment == "ODMR":
            self.setWindowTitle('CW Optically Detected Magnetic Resonance (ODMR)')
        elif self.experiment == "Counter":
            self.setWindowTitle('Photon Counter')
        else:
            self.setWindowTitle('Quantum Measurement')

    def closeEvent(self, event):
        if self.gui_ref is not None:
            self.gui_ref.handle_window_close()
        super(MainWindow, self).closeEvent(event)


class MainGui(QtCore.QObject):
    def __init__(self):
        super().__init__()
        self.running: bool = False
        self.program: ExperimentBase | None = None
        self.settings_dialog = None
        self.experiments = ["Counter", "Rabi", "ODMR"]
        # Load the last selected experiment from persistent storage, default to "Rabi"
        self.current_experiment: str = settings.value("current_experiment", "Counter")

        # Store graph data for each experiment to enable flipping between them
        self.graph_data_storage = {}
        for exp in self.experiments:
            if exp not in settings.value("graph_data_storage", {}):
                settings.setValue(f"graph_data_storage/{exp}", {
                    "x_data": np.array([]),
                    "y_data": np.array([]),
                    "x_fit": np.array([]),
                    "y_fit": np.array([]),
                    "fit_text": ""
                })

        # Create the main window
        self._mw = MainWindow(gui_ref=self, experiment=self.current_experiment)

        # Create experiment selector dropdown
        self.experiment_selector = QComboBox()
        self.experiment_selector.addItems(self.experiments)
        self.experiment_selector.setCurrentText(self.current_experiment)
        self.experiment_selector.currentTextChanged.connect(self.on_experiment_changed)

        # Add the experiment selector to the toolbar
        self._mw.counting_control_ToolBar.addSeparator()
        self._mw.counting_control_ToolBar.addWidget(QtWidgets.QLabel("Experiment:"))
        self._mw.counting_control_ToolBar.addWidget(self.experiment_selector)

        # Initialize the plot items
        self.image = pg.PlotDataItem(np.array([]),
                                     np.array([]),
                                     pen=None,
                                     symbol='o',
                                     symbolPen=palette.c1,
                                     symbolBrush=palette.c1,
                                     symbolSize=3)

        self.fit_image = pg.PlotDataItem(np.array([]),
                                         np.array([]),
                                         pen=pg.mkPen(palette.c2, width=3))

        # Add the display item to the ViewWidget, which was defined in the UI file.
        self._mw.rabi_plot_PlotWidget.addItem(self.image)
        self._mw.rabi_plot_PlotWidget.addItem(self.fit_image)

        self._mw.rabi_plot_PlotWidget.setLabel(axis='left', text='Normalised Signal', units='normalised units')
        self._mw.rabi_plot_PlotWidget.setLabel(axis='bottom', text='Time', units='ns')
        self._mw.rabi_plot_PlotWidget.showGrid(x=True, y=True, alpha=0.8)
        self._mw.rabi_plot_PlotWidget.setBackground(pg.mkColor(*PLOT_WIDGET_BG))  # Set background to dark gray

        # Style the textbox to match the plot widget color scheme
        self._mw.fit_results_Text.setPalette(get_textbox_palette())

        # Style the toolbar to match the plot widget color scheme
        self._mw.counting_control_ToolBar.setPalette(get_toolbar_palette())

        self._mw.run_rabi_Action.toggled.connect(self.run_toggled)  # type: ignore
        self._mw.fit_rabi_Action.triggered.connect(self.fit_clicked)  # type: ignore
        self._mw.save_rabi_Action.triggered.connect(self.save_clicked)  # type: ignore
        self._mw.settings_Action.triggered.connect(self.settings_clicked)  # type: ignore

        # Initialize QTimer for plot updates
        self.plot_timer = QtCore.QTimer()
        self.plot_timer.timeout.connect(self.update_plot_data)  # type: ignore
        self.plot_update_interval = 100  # Update plot every 100ms

        # Initialize the program
        self.init_program()

    def init_program(self):
        """Initialize the appropriate program based on current experiment"""
        match self.current_experiment:
            case "Rabi":
                self.program = Rabi()
                self.settings_dialog = SettingsDialogRabi(self._mw)
            case "ODMR":
                self.program = CW_ODMR()
                self.settings_dialog = SettingsDialogODMR(self._mw)
            case "Counter":
                self.program = Counter()
                self.settings_dialog = SettingsDialogCounter(self._mw)
        self.update_plot_labels()

    def on_experiment_changed(self, experiment_name):
        """Handle experiment selection change, preserving graph data"""
        if self.running:
            QtWidgets.QMessageBox.warning(
                self._mw,
                "Measurement Running",
                "Please stop the current measurement before changing experiments."
            )
            self.experiment_selector.setCurrentText(self.current_experiment)
            return

        # Save current experiment's graph data before switching
        self.save_graph_data()

        self.current_experiment = experiment_name
        self._mw.experiment = experiment_name
        self._mw.update_window_title()

        # Save the selected experiment to persistent storage
        self.save_experiment_selection()

        # Re-initialize program with new experiment type
        self.init_program()

        # Update plot labels based on experiment
        self.update_plot_labels()

        # Restore the saved graph data for the new experiment
        self.restore_graph_data()

    def update_plot_labels(self):
        """Update plot axis labels based on the current experiment"""
        try:
            labels = self.program.get_plot_info()
            self._mw.rabi_plot_PlotWidget.setLabel(axis='left', text=labels["y_text"], units=labels["y_units"])
            self._mw.rabi_plot_PlotWidget.setLabel(axis='bottom', text=labels["x_text"], units=labels["x_units"])
        except Exception as e:
            print(f"Error getting plot info from program: {e}")
            self._mw.rabi_plot_PlotWidget.setLabel(axis='left', text="y data", units="")
            self._mw.rabi_plot_PlotWidget.setLabel(axis='bottom', text="x data", units="")


    def save_graph_data(self):
        """Save current graph data for the active experiment"""
        try:
            # Store in the appropriate experiment slot
            x_data = self.image.xData if self.image.xData is not None else np.array([])
            y_data = self.image.yData if self.image.yData is not None else np.array([])
            x_fit = self.fit_image.xData if self.fit_image.xData is not None else np.array([])
            y_fit = self.fit_image.yData if self.fit_image.yData is not None else np.array([])

            self.graph_data_storage[self.current_experiment] = {
                "x_data": x_data.copy() if len(x_data) > 0 else np.array([]),
                "y_data": y_data.copy() if len(y_data) > 0 else np.array([]),
                "x_fit": x_fit.copy() if len(x_fit) > 0 else np.array([]),
                "y_fit": y_fit.copy() if len(y_fit) > 0 else np.array([]),
                "fit_text": self._mw.fit_results_Text.toPlainText()
            }
        except Exception as e:
            print(f"Error saving graph data: {e}")

    def restore_graph_data(self):
        """Restore saved graph data for the current experiment"""
        data = self.graph_data_storage.get(self.current_experiment, {})
        x_data = data.get("x_data", np.array([]))
        y_data = data.get("y_data", np.array([]))
        x_fit = data.get("x_fit", np.array([]))
        y_fit = data.get("y_fit", np.array([]))
        fit_text = data.get("fit_text", "")

        self.image.setData(x_data, y_data)

        # Only set fit data if it exists
        if len(x_fit) > 0 and len(y_fit) > 0:
            self.fit_image.setData(x_fit, y_fit)
        else:
            self.fit_image.setData(np.array([]), np.array([]))

        self._mw.fit_results_Text.setPlainText(fit_text)

    def save_experiment_selection(self):
        """Save the currently selected experiment to QSettings"""
        settings.setValue("current_experiment", self.current_experiment)

    def error_message(self, message):
        """Display an error message in a message box"""
        QtWidgets.QMessageBox.critical(self._mw, "Error", message)

    def run_toggled(self, run):
        if run:
            # Clear the fit from the previous run
            self.fit_image.setData(np.array([]), np.array([]))
            self._mw.fit_results_Text.setPlainText("")

            # Start the measurement in a separate thread
            self.running = True
            self.program_thread = threading.Thread(target=self.program.start_program, daemon=True)
            self.program_thread.start()
            # Start the QTimer for safe GUI updates from the Qt event loop
            self.plot_timer.start(self.plot_update_interval)
        else:
            self.running = False
            # Stop the timer
            self.plot_timer.stop()
            self.program.stop_program()

    def fit_clicked(self):
        """Fit the data - for Counter, rolling average is automatic; for others, perform fitting"""
        if self.current_experiment == "Counter":
            # For Counter, rolling average is already displayed via continuous update
            QtWidgets.QMessageBox.information(
                self._mw,
                "Rolling Average",
                "The red line shows the 10-point rolling average, which updates continuously during measurement."
            )
        else:
            # For Rabi and ODMR, compute and display the fit
            x, y, text = self.program.fit()
            if x is not None and y is not None:
                self.fit_image.setData(x, y)
                self._mw.fit_results_Text.setPlainText(text)

    def save_clicked(self):
        self.program.save_data()

    def settings_clicked(self):
        self.settings_dialog.exec()

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
                x_data = self.program.get_x()
                y_data = self.program.get_y()
                if x_data is not None and y_data is not None:
                    self.image.setData(x_data, y_data)

                    # For Counter experiment, also update the rolling average fit line and statistics
                    if self.current_experiment == "Counter":
                        x_fit, y_fit, fit_text = self.program.fit()
                        if len(x_fit) > 0 and len(y_fit) > 0:
                            self.fit_image.setData(x_fit, y_fit)
                            # Update the fit results text with average counts
                            self._mw.fit_results_Text.setPlainText(fit_text)

                    # Continuously save data during measurement
                    self.save_graph_data()
            except Exception as e:
                print(f"Error updating plot data: {e}")

    def handle_window_close(self):
        # Save the currently selected experiment before closing
        self.save_experiment_selection()

        # Save if there is data and not already saved
        if hasattr(self.program, 'counts') and hasattr(self.program, 'counts_ref'):
            if self.program.counts is not None and self.program.counts_ref is not None:
                if hasattr(self.program, 'iteration') and self.program.iteration is not None:
                    self.program.save_data()
        # Halt the job if running
        try:
            if hasattr(self.program, 'job') and self.program.job is not None:
                self.program.job.halt()
        except Exception as e:
            print(f"Error halting the job on window close: {e}")


if __name__ == "__main__":
    import sys

    app = QtWidgets.QApplication(sys.argv)
    main_gui = MainGui()
    main_gui.show()
    sys.exit(app.exec())
