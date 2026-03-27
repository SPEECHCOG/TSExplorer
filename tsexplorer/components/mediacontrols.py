''' This file defines commonly used components with media widgets'''
from ..utils.misc import clamp
from ..utils.logger import get_logger
from ..utils.qt_utils import SignalBlocker
from ..metadata import MediaPlayerState

from PySide6.QtWidgets import (QWidget, QSlider, QHBoxLayout,
                               QToolButton, QStyle)
from PySide6.QtCore import QObject, Signal, Slot, Qt

from typing import Optional


class MediaControls(QWidget):
    '''
    Defines a classical three button layout (play, stop, pause) for controlling
    media player

    Signals
    -------
    sign_paused:
        Emitted when the pause button is pressed.
    sign_stopped:
        Emitted when the stop button is pressed.
    sign_started:
        Emitted when the start button is pressed.
    sign_slider_moved: int
        Emitted when the user moves the slider. Contains the update position in
        milliseconds
    sign_slider_released: int
        Emitted when the user releases the slider. Contains the final position
        of the slider in milliseconds
    '''
    sign_paused = Signal()
    sign_stopped = Signal()
    sign_started = Signal()
    sign_slider_moved = Signal(int)
    sign_slider_released = Signal(int)

    def __init__(self, parent: Optional[QObject] = None):
        '''
        Creates the application's controls.

        Parameters
        ----------
        parent: Optional[QObject]
            Parent object of this widget. Should probably be the media player
            these buttons are attached to.
        '''
        super().__init__(parent)

        self._logger = get_logger("media-controls")
        self._player_state = MediaPlayerState.STOPPED
        # Create the controls
        layout = QHBoxLayout()

        self._play_btn = QToolButton(self)
        self._play_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaPlay))
        self._stop_btn = QToolButton(self)
        self._stop_btn.setIcon(self.style().standardIcon(QStyle.SP_MediaStop))
        self._slider = QSlider(Qt.Orientation.Horizontal)

        layout.addWidget(self._play_btn)
        layout.addWidget(self._stop_btn)
        layout.addWidget(self._slider)
        self.setLayout(layout)

        self._play_btn.clicked.connect(self._handle_start_pause_click)
        self._stop_btn.clicked.connect(self.sign_stopped)
        self._slider.valueChanged.connect(self.sign_slider_moved)
        self._slider.sliderReleased.connect(self._on_slider_release)

    @Slot(float)
    def on_position_change(self, new_pos: int):
        '''
        Updates the slider to the current position

        Parameters
        ----------
        new_pos: int
            the new position as milliseconds.
        '''
        smin, smax = self._slider.minimum(), self._slider.maximum()
        new_pos = clamp(new_pos, smin, smax)
        if new_pos < smin or new_pos > smax:
            self._logger.warning(f"{new_pos} out of bounds ({smin}, {smax})")
        with SignalBlocker(self._slider):
            self._slider.setValue(new_pos)

    @Slot()
    def on_player_error(self):
        '''
        Called if the player-backend has an error. Disables all buttons
        '''
        self._stop_btn.setEnabled(False)

    @Slot(int)
    def on_player_state_changed(self, state: int):
        '''
        Updates the controls button based on the current state of the player.

        Parameters
        ----------
        state: int
            The state of the player
        '''
        state = MediaPlayerState(state)
        # If the state has not changed, this is a no-op
        if self._player_state == state:
            return

        self._player_state = state

        # Update the state
        if state == MediaPlayerState.STOPPED:
            # If we are stopped, we disable the stop button
            # and update its icon
            self._logger.debug("Stopped!")
            self._stop_btn.setEnabled(False)
            self._play_btn.setIcon(
                    self.style().standardIcon(QStyle.SP_MediaPlay)
            )
            self._slider.setValue(0)

        elif state == MediaPlayerState.PLAYING:
            # In playing state we need to enable the stop button.
            self._stop_btn.setEnabled(True)
            self._play_btn.setIcon(
                    self.style().standardIcon(QStyle.SP_MediaPause)
            )
        elif state == MediaPlayerState.PAUSED:
            # Same thing in paused state.
            self._stop_btn.setEnabled(True)
            self._play_btn.setIcon(
                    self.style().standardIcon(QStyle.SP_MediaPlay)
            )

    @Slot()
    def on_duration_changed(self, duration: int):
        '''
        Updates the controls range to match the new duration.

        Parameters
        ----------
        duration: int
            The updated duration of the played data, in milliseconds
        '''
        self._slider.setRange(0, duration)

    @Slot()
    def _handle_start_pause_click(self):
        '''
        Handle a click in the play/pause button and emit correct signal based
        on the current state
        '''
        if self._player_state == MediaPlayerState.PLAYING:
            self.sign_paused.emit()
        else:
            self.sign_started.emit()

    @Slot()
    def _on_slider_release(self):
        '''
        Emits the 'sign_slider_released' signal with the current position of
        the slider.
        '''
        self.sign_slider_released.emit(self._slider.value())
