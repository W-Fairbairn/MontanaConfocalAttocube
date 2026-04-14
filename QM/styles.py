"""
GUI Styling module for the Rabi Oscillation Measurement application.
Contains color definitions and palette configurations.
"""

from PyQt6.QtGui import QColor, QPalette
from qudi.util.colordefs import QudiPalettePale as palette


# Color definitions
class Colors:
    """Main color palette for the application"""
    BG_DARK = QColor(48, 47, 47)      # Dark gray background
    TEXT_LIGHT = QColor(150, 150, 150) # Light gray text


# Window and main widget styles
MAIN_WINDOW_STYLESHEET = "background-color: rgb(48, 47, 47); color: rgb(150, 150, 150);"

PLOT_WIDGET_BG = (48, 47, 47)  # Dark gray for plot background


def get_textbox_palette():
    """Create and return a palette configured for text boxes"""
    text_palette = QPalette()
    text_palette.setColor(QPalette.ColorRole.Base, Colors.BG_DARK)
    text_palette.setColor(QPalette.ColorRole.Text, Colors.TEXT_LIGHT)
    return text_palette


def get_toolbar_palette():
    """Create and return a palette configured for toolbars"""
    toolbar_palette = QPalette()
    toolbar_palette.setColor(QPalette.ColorRole.Button, Colors.BG_DARK)
    toolbar_palette.setColor(QPalette.ColorRole.ButtonText, Colors.TEXT_LIGHT)
    toolbar_palette.setColor(QPalette.ColorRole.Window, Colors.BG_DARK)
    toolbar_palette.setColor(QPalette.ColorRole.WindowText, Colors.TEXT_LIGHT)
    return toolbar_palette
