import os
from PySide2 import QtCore, QtWidgets, QtGui
import qudi.util.uic as uic
import pyqtgraph as pg

from qudi.core.connector import Connector
from qudi.util.colordefs import QudiPalettePale as palette
from qudi.core.module import GuiBase
from qudi.interface.simple_laser_interface import ControlMode, ShutterState, LaserState
from qudi.util.paths import get_artwork_dir

class PsatMainWindow(QtWidgets.QMainWindow):
    def __init__(self):
        # Get the path to the *.ui file
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'psat_ui.ui')

        #load ui
        super().__init__()
        uic.loadUi(ui_file, self)

        self.setWindowTitle('qudi: Laser')
        return

class PsatGUI(GuiBase):
    _psat_logic = Connector(name='psat_logic', interface='PsatLogic')

    def on_activate(self):
        self.logic = self._psat_logic()
        self._mw = PsatMainWindow()
        self.show()

        self._mw.setPowerButton.clicked.connect(self.setPower)
        self._mw.psatRunButton.clicked.connect(self.psatRun)

        return

    def on_deactivate(self):
        return

    def show(self):
        """Make main window visible and put it above all other windows."""
        # Show the Main Confocal GUI:
        self._mw.show()
        self._mw.activateWindow()
        self._mw.raise_()

    def setPower(self):
        laser_power = self._mw.powerValueSpinBox.value()
        print("trying to set power to", laser_power)
        self.logic.set_power('ao3', laser_power)

    def psatRun(self):
        counts, voltage = self.logic.psatRun()
        self._mw.testGraph.plot(voltage, counts)
        return

