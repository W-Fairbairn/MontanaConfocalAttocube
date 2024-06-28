
import numpy as np
import os
import pyqtgraph as pg
import re

from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.util.units import ScaledFloat
from qudi.util.helpers import natural_sort
from qudi.core.module import GuiBase

from qudi.util.colordefs import QudiPalettePale as palette
from PySide2 import QtCore, QtGui, QtWidgets
from qudi.util import uic
from qudi.util.widgets.plotting.image_widget import MouseTrackingImageWidget

class OPXControllerWindow(QtWidgets.QMainWindow):
    def __init__(self):
        this_dir = os.path.dirname(__file__)
        ui_file = os.path.join(this_dir, 'opx_controller.ui')

        # Load it
        super(OPXControllerWindow, self).__init__()
        uic.loadUi(ui_file, self)
        self.show()

"""
    This is the GUI Class for PoiManager

    example config for copy-paste:

    poi_manager_gui:
        module.Class: 'poimanager.poimanagergui.PoiManagerGui'
        options:
            data_scan_axes: xy  #optional, default: xy
        connect:
            poi_manager_logic: 'poi_manager_logic'
    """
class OPXControllerGUI(GuiBase):
    # declare connectors
    _opx_controller_logic = Connector(name='opx_controller_logic', interface='OPXControllerLogic')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._mw = None

    def on_activate(self):
        self._mw = OPXControllerWindow()
        #change central layout inhertied from MainWindow to be custom widget
        layout = QtWidgets.QVBoxLayout()
        self._mw.tidywidget.setLayout(layout)
        self._mw.setCentralWidget(self._mw.tidywidget)
        self._mw.show()

    def on_deactivate(self):
        self._mw.close()

    def show(self):
        """Make main window visible and put it above all other windows. """
        QtWidgets.QMainWindow.show(self._mw)
        self._mw.activateWindow()
        self._mw.raise_()


