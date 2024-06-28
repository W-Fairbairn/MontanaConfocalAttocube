import os
import numpy as np
import time
from datetime import datetime
from collections import OrderedDict
from PySide2 import QtCore

from qudi.core.module import LogicBase
from qudi.core.connector import Connector
from qudi.core.configoption import ConfigOption
from qudi.core.statusvariable import StatusVar
from qudi.util.mutex import RecursiveMutex
from qudi.util.datastorage import TextDataStorage


class OPXControllerLogic(LogicBase):
    #Declare connectors
    _opx = Connector(name='opx', interface='OPXHardware')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # threading
        #might need this later? leaving this here for now just in case
        self._thread_lock = RecursiveMutex()
        return

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        return

    def on_deactivate(self):
        """ Perform actions during deactivation of the module"""
        return