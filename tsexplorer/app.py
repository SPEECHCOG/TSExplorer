'''This file contains the main definition of the application'''

from .components import Window
from . import defaults

import sys
from typing import List, Tuple, Any, Optional

from PySide6.QtWidgets import QApplication

import pyqtgraph as pg
# Set global config options for pyqtgraph
pg.setConfigOption("foreground", "k")
pg.setConfigOption("background", "w")


class Application:
    '''
    The main application that maintains the lifetime and ownership of all the
    other widgets in the application
    '''

    def __init__(self, config_file: str, args: List[str]):
        '''
        The constructor for the application.

        Parameters
        ----------
        config_file: str
            Path to the configuration file. (should be a YAML file)
        *args: Tuple[Any, ...]
            Any possible arguments from the command line.

        '''
        self._app = QApplication(args)

        style = self._get_stylesheet()
        if style is not None:
            self._app.setStyleSheet(style)
        self._window = Window(config_file)

    def run_to_completion(self) -> None:
        '''
        The main function responsible for running the application
        to the completion. Will raise a system error if something unusual
        happens (i.e. exit code != 0)
        '''
        if not self._window.init_success:
            sys.exit(0)
        self._window.resize(800, 600)  # TODO: Read from config
        self._window.show()
        self._app.processEvents()
        sys.exit(self._app.exec())

    def _get_stylesheet(self) -> Optional[str]:
        '''
        Get the style-sheet based on the options set by user. If no options are
        set, allow Qt to determine the font settings automatically

        Returns
        -------
        Optional[str]
            The stylesheet for the application. None if no settings are set.
        '''
        app_font_settings = defaults.RCPARAMS["application-font"]
        if (app_font_settings["size"] is None and
                app_font_settings["color"] is None):
            return None

        # If either one of the keys were set, create a style-sheet
        style = "* {"
        if app_font_settings["size"] is not None:
            style += "font-size: {size}; ".format(
                size=app_font_settings["size"]
            )
        if app_font_settings["color"] is not None:
            style += "color: {color}; ".format(
                color=app_font_settings["color"]
            )
        style += "}"
        return style



