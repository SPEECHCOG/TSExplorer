""" This file defines common utilities related to Qt """
from PySide6.QtCore import QObject


class SignalBlocker:
    '''
    Defines a simple context manager that blocks signals to a given QObject.
    '''
    def __init__(self, qobj: QObject):
        '''
        Creates the signal blocker

        Parameters
        ----------
        qobj: QObject
            The object for which the signals should be blocked
        '''
        self._qobj: QObject = qobj
        self._state = None

    def __enter__(self):
        '''Starts the blocking of signals'''
        self._state = self._qobj.blockSignals(True)

    def __exit__(self, exc_type, exc_val, exc_tb):
        '''Restores the previous state of the object'''
        self._qobj.blockSignals(self._state)

