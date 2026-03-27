''' Define interface for data displaying components'''

from abc import ABC

from typing import Dict
import numpy.typing as npt


class IComponent(ABC):
    '''
    Defines common interface for each data displaying component
    In addition to the functions, the widget should contain the following
    signals:
        sign_cursor_moved: float, float, str
            Emitted when the 'cursor' of the widget is moved. Should contain
            the new x and y position (as floats) and the name of the widget
            emitting the signals.
        sign_cursor_move_ended: float, float, str
            Emitted when the 'cursor' movement STOPS. Should contain the new
            x and y positions (as floats) and the name of the widget that
            emitted the signals.
        sign_ready:
            Emitted when the widget is ready (i.e. new data is displayed).
        sign_error: str
            Emitted if the component encounters any issues. Should contain
            the relevant error message
    '''

    @property
    def wtype(self) -> str:
        ''' Must return the type of the widget '''
        raise NotImplementedError("")

    @property
    def requires_update(self) -> bool:
        '''
        Returns True if the widget needs to be updated every time the sample
        changes, False otherwise
        '''
        raise NotImplementedError("")

    def set_data(self, data: Dict[str, npt.NDArray]):
        '''
        Updates the data that is displayed by the component. Will be called
        every time that the sample changes if 'requires_update' is True.
        Otherwise, will be called only once when the first sample is set.

        Parameters
        ----------
        data: Dict[str, npt.NDArray]
            The data to display. Can contain multiple items, which are
            differentiated using the labels as keys.
        '''
        raise NotImplementedError("")

    def shutdown():
        '''
        Called when the application is going to shutdown. Should release/handle
        any resources that are/need to be managed manually.
        '''
        raise NotImplementedError("")

    def on_cursor_move(x: float, y: float, name: str):
        '''
        A slot for signal indicating that cursor has been moved in one of the
        other data displaying widgets. If the component doesn't support any
        data displaying behaviour, can be left no-op. Otherwise, should update
        the components view with the new cursor position

        Parameters
        ----------
        x: float
            The new x position.
        y: float
            The new y position.
        name: str
            The name of the widget that emitted the signal.
        '''
        raise NotImplementedError("")

    def on_cursor_move_ended(x: float, y: float, name: str):
        '''
        A slot that is called when a cursor movement has ended. This can be
        as a replacement to 'on_cursor_move' if the widget can work with
        'approximately' real-time updates.

        Parameters
        ----------
        x: float
            The new x position.
        y: float
            The new y position.
        name: str
            The name of the widget that emitted the signal.
        '''
        raise NotImplementedError("")

    def on_startup():
        '''
        A slot that is called after all widgets have emitted 'sign_ready'
        signal, meaning the position from which the annotation can start. Using
        this handler, the widgets can execute any code that should be done when
        the user starts annotating the samples
        '''
        raise NotImplementedError("")
