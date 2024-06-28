# -*- coding: utf-8 -*-
"""
This module contains a OPX controller core class which gives capability to configure
OPX RF pulses (length, amplitude) as well as delays.
"""

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

# from qudi.opx_pulse_configurations import JM_Pulse_Sequence_Configuration


class OPXControllerLogic(LogicBase):
    #Declare connectors
    _opx = Connector(name='opx', interface='OPXHardware')

    #Options
    _opx_address = ConfigOption('opx_address', default='192.168.88.254')
    _octave_address = ConfigOption('octave_address', default='192.168.88.253')
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)

        # threading
        #might need this later? leaving this here for now just in case/as a reminder
        self._thread_lock = RecursiveMutex()

        self._pulse_sequence_config = None

        return

    def on_activate(self):
        """ Initialisation performed during activation of the module.
        """
        # self._pulse_sequence_config = JM_Pulse_Sequence_Configuration()
        return

    def on_deactivate(self):
        """ Perform actions during deactivation of the module"""
        return