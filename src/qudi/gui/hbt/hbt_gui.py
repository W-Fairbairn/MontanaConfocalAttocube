import os
from PySide2 import QtCore, QtWidgets, QtGui
import qudi.util.uic as uic
import pyqtgraph as pg

from qudi.core.connector import Connector
from qudi.util.colordefs import QudiPalettePale as palette
from qudi.core.module import GuiBase
from qudi.core.configoption import ConfigOption
from qudi.interface.simple_laser_interface import ControlMode, ShutterState, LaserState
from qudi.util.paths import get_artwork_dir

class HbtMainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'ui_hbt.ui')

        #load ui
        super().__init__()
        uic.loadUi(ui_file, self)

        self.setWindowTitle('qudi: HBT')
        return

class HbtGui(GuiBase):
    _hbt_logic = Connector(name='hbt_logic', interface='HbtLogic')
    time_window = ConfigOption(name='time_window', default=100, missing='info')

    def on_activate(self):
        self.logic = self._hbt_logic()
        self._mw = HbtMainWindow()
        self.show()
        self.hbt_image = pg.PlotDataItem(self.logic.bin_times/1000,
                                         self.logic.g2_data_normalised,
                                         pen=None,
                                         symbol='o',
                                         symbolPen=palette.c1,
                                         symbolBrush=palette.c1,
                                         symbolSize=3)

        self.hbt_fit_image = pg.PlotDataItem(self.logic.fit_times,
                                             self.logic.fit_g2,
                                             pen=pg.mkPen(palette.c2, width=2))

        # Add the display item to the ViewWidget, which was defined in the UI file.
        self._mw.hbt_plot_PlotWidget.addItem(self.hbt_image)
        self._mw.hbt_plot_PlotWidget.addItem(self.hbt_fit_image)

        # Text item for displaying fit result
        self.fit_text = pg.TextItem(text='', anchor=(0, 1), color=palette.c2)
        self.fit_text.setFont(QtGui.QFont('Arial', 12, QtGui.QFont.Bold))
        self._mw.hbt_plot_PlotWidget.addItem(self.fit_text)

        self._mw.hbt_plot_PlotWidget.setLabel(axis='left', text='g2(t)', units='normalised units')
        self._mw.hbt_plot_PlotWidget.setLabel(axis='bottom', text='Time', units='ns')
        self._mw.hbt_plot_PlotWidget.showGrid(x=True, y=True, alpha=0.8)
        self.set_time_window(self.time_window)

        #####################
        # Connecting user interactions
        self._mw.run_hbt_Action.toggled.connect(self.run_hbt_toggled)
        self._mw.fit_hbt_Action.triggered.connect(self.fit_clicked)
        self._mw.save_hbt_Action.triggered.connect(self.save_clicked)

        ##################
        # Handling signals from the logic
        self.logic.hbt_updated.connect(self.update_data)
        self.logic.hbt_fit_updated.connect(self.update_fit)

        return 0

    def run_hbt_toggled(self, run):
        if run:
            self.logic.start_hbt()
        else:
            self.logic.stop_hbt()

    def fit_clicked(self):
        self.logic.fit_hbt()

    def save_clicked(self):
        self.logic.save_hbt()

    def show(self):
        """Make window visible and put it above all other windows.
        """
        QtWidgets.QMainWindow.show(self._mw)
        self._mw.activateWindow()
        self._mw.raise_()
        return

    def set_time_window(self, t):
        self._mw.hbt_plot_PlotWidget.setXRange(-0.5 * t, 0.5 * t, padding=None)

    def on_deactivate(self):
        """ Deactivate the module
        """
        # disconnect signals
        self._mw.close()
        return

    def update_data(self):
        """ The function that grabs the data and sends it to the plot.
        """

        """ Refresh the plot widgets with new data. """
        # Update psat plot
        self.hbt_image.setData(self.logic.bin_times / 1000, self.logic.g2_data_normalised)

        return 0

    def update_fit(self):
        """ Refresh the plot widgets with new data. """
        if self.logic.hbt_fit_available:
            # Update hbt fit plot
            self.hbt_fit_image.setData(self.logic.fit_times / 1000, self.logic.fit_g2)

            # Display N = 1/(1 - g2(0)) on the plot
            g2_0 = self.logic.g2_0
            if g2_0 < 1.0:
                n_value = 1.0 / (1.0 - g2_0)
                self.fit_text.setText(f'N = {n_value:.1f}')
            else:
                self.fit_text.setText(f'g²(0) = {g2_0:.3f}')

            # Position text in the upper-left of the current view
            vb = self._mw.hbt_plot_PlotWidget.getViewBox()
            x_range, y_range = vb.viewRange()
            self.fit_text.setPos(x_range[0] + 0.05 * (x_range[1] - x_range[0]),
                                 y_range[1] - 0.05 * (y_range[1] - y_range[0]))

