"""
This module controls Quantum Machine OPX arbitrary wave generators.

Author: Alex Newman 2024
"""

from qudi.core.configoption import ConfigOption
from qudi.interface.opx_interface import OPXInterface


class OPXHardware(OPXInterface):

    def on_activate(self):
        pass

    def on_deactivate(self):
        pass

    def connect_opx(self):
        pass