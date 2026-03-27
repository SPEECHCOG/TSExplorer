from .mediacontrols import MediaControls
from ..metadata import WidgetType, MediaPlayerState
from ..utils.mediaplayer import MediaPlayer
from ..utils.logger import get_logger
from tsexplorer.utils.io import load_numpy

import pathlib
import numpy as np

# For validating the kwargs
from schema import Schema, Optional, Use

from PySide6.QtWidgets import QWidget, QGridLayout
from PySide6.QtCore import QObject, Signal, Slot

from typing import Optional as Optional_t
from typing import Mapping, Any, Dict


class AudioWidget(QWidget):
    '''
    Defines an audio widget that can be used to play WAV data.

    Signals
    -------
    sign_cursor_moved: float, float, str
        Emitted when the position of the underlying player is updated.
        Contains the updated x and y position, (x in seconds), and the name of
        the widget which emitted the signal.
    sign_cursor_move_ended: float, float, str
        Emitted when the moving of the underlying player is stopped.
        Contains the updated x and y positions (x in seconds), and the name of
        the widget which emitted the signal.
    sign_ready:
        Emitted when the player is ready to play audio.
    sign_error: str
        Emitted if the component encounters any issues. Contains the relevant
        error message
    '''
    sign_cursor_moved = Signal(float, float, str, name="sign_cursor_moved")
    sign_cursor_move_ended = Signal(
            float, float, str, name="sign_cursor_move_ended"
    )
    sign_position_changed = Signal(float)
    sign_ready = Signal(name="sign_ready")
    sign_error = Signal(str, name="sign_error")

    _KWARGS_SCHEMA: Schema = Schema({
        "name": Schema(
            str, error=("Missing 'name'! This is likely an internal bug, "
                        "and not an user error")
        ),
        Optional("source_dirs"): [str],
        Optional("numpy_path"): Use(str),
        Optional("wav_file_names_path"): Use(str),
        Optional("sample_rate", default=16000): int,
        Optional("auto_play", default=False): bool
    })

    def __init__(
            self, parent: Optional_t[QObject] = None,
            **kwargs: Mapping[str, Any]
            ):
        '''
        Creates the widget, containing the audio controls

        Parameters
        ----------
        parent: Optional[QObject]
            The parent of this widget.
        kwargs: Mapping[str, Any]
            Any possible keyword arguments. Currently supported values:
                'auto_play': bool
                    If set to True, each sample can start playing automatically
        '''
        super().__init__(parent)

        # Validate user specified arguments
        kwargs = self._KWARGS_SCHEMA.validate(kwargs)

        self._logger = get_logger("audio-widget")
        # Create the layout
        layout = QGridLayout()
        self._controls = MediaControls(self)
        layout.addWidget(self._controls, 0, 0)
        self.setLayout(layout)

        self._props: Dict[str, Any] = kwargs

        self._logger.debug(f"Using auto-play?: {kwargs.get('auto_play')}")
        self._player = MediaPlayer(self)

        self._ready: bool = False
        self._wtype: WidgetType = WidgetType.AUDIO
        self._requires_update: bool = True

        # Connect the player to the audio-widget
        self._player.sign_duration_changed.connect(
                self._controls.on_duration_changed
        )

        self._player.sign_state_changed.connect(
                self._on_player_state_change
        )

        self._player.sign_error.connect(self._on_player_error)
        self._player.sign_position_changed.connect(
                self._on_player_update
        )

        # Connect controls to the actual player
        self._controls.sign_started.connect(self._player.play)
        self._controls.sign_paused.connect(self._player.pause)
        self._controls.sign_stopped.connect(self._player.stop)

        # Connect controls to the audio widget
        self._controls.sign_slider_moved.connect(
                self._on_slider_move
        )
        self._controls.sign_slider_released.connect(
                self._on_slider_released
        )
        
        # If the user provided a Numpy file, load it and use it instead
        self._preloaded_numpy_audio = None  # Will hold the audio matrix
        self._preloaded_sample_rate = None  # Optional: if you store sample rate separately

        numpy_path = kwargs.get("numpy_path", None)
        if numpy_path:
            try:
                self._logger.debug(f"Loading NumPy audio from: {numpy_path}")
                self._preloaded_numpy_audio = load_numpy(pathlib.Path(numpy_path))
                self._preloaded_sample_rate = kwargs.get("sample_rate", 16000)
            except Exception as e:
                self._logger.error(f"Failed to load NumPy audio: {e}")
                self.sign_error.emit(f"Failed to load NumPy audio: {e}")

    @property
    def wtype(self) -> WidgetType:
        ''' Returns the type of the widget.'''
        return self._wtype

    @property
    def requires_update(self) -> bool:
        '''
        Returns true if the data of the widget should be updated for every
        sample
        '''
        return self._requires_update

    def set_data(self, data: Mapping[str, Any]):
        '''
        Set the data that the widget will play.
        Supports both file paths and preloaded NumPy arrays.
        '''
        if self._preloaded_numpy_audio is not None:
            wav_file_name, sample_id = next(iter(data.items()))
            self._player.set_data_from_numpy(self._preloaded_numpy_audio[sample_id], self._preloaded_sample_rate)
        else:
            assert len(data) == 1, f"Expected only one value, got {len(data)}"
            key, value = next(iter(data.items()))

            if isinstance(value, pathlib.Path):
                self._player.set_data(value)
            elif isinstance(value, dict) and "audio" in value and "sample_rate" in value:
                audio_array = value["audio"]
                sample_rate = value["sample_rate"]
                assert isinstance(audio_array, np.ndarray), "Expected NumPy array for 'audio'"
                self._player.set_data_from_numpy(audio_array, sample_rate)
            else:
                raise ValueError("Unsupported data format for AudioWidget")

        if not self._ready:
            self._ready = True
            self.sign_ready.emit()
        elif self._props["auto_play"]:
            self._player.play()

    def shutdown(self):
        ''' Does needed cleanup before shutting down. Currently no-op'''
        return

    @Slot()
    def on_cursor_move(self, x: float, y: float, name: str):
        '''
        Updates the internal state of the application when the user moves
        the cursor

        Parameters
        ----------
        x: float
            The new position in seconds
        y: float
            the new y position
        name: str
            The name of the widget that sent this signal
        '''
        self._controls.on_position_change(int(1000*x))

    @Slot()
    def on_cursor_move_ended(self, x: float, y: float, name: str):
        '''
        Updates the internal state of the application to match the state of the
        cursor.

        Parameters
        ----------
        x: float
            The new x position (in seconds)
        y: float
            The new y position.
        name: str
            The name of the widget that send the signal
        '''
        # The control should already be in correct state, so update just the
        # underlying audio player this time.
        # This time, set the audio to start from here
        self._player.on_cursor_move_ended(int(1000*x))

    @Slot()
    def on_startup(self):
        ''' Handler that is called just before the annotation starts. '''
        if self._props["auto_play"]:
            self._player.play()

    @Slot()
    def _on_player_update(self, pos_ms: int):
        '''
        Called when the player updates its position.

        Parameters
        ----------
        pos_ms: int
            The updated position in milliseconds.
        '''
        self.sign_cursor_moved.emit(pos_ms*10**-3, 0.0, "audio")
        self._controls.on_position_change(pos_ms)

    @Slot()
    def _on_player_state_change(self, state: int):
        '''
        Called when the player updates its state.

        Parameters
        ----------
        state: int
            The updated state.
        '''
        state = MediaPlayerState(state)

        if state == MediaPlayerState.STOPPED:
            self.sign_cursor_moved.emit(0.0, 0.0, "audio")
        self._controls.on_player_state_changed(int(state))

    @Slot()
    def _on_player_error(self, err_msg: str):
        '''
        Called if the player encounters an error.

        Parameters
        ----------
        err_msg: str
            The error message from the player
        '''
        self._controls.on_player_error()
        self.sign_error.emit(err_msg)

    @Slot()
    def _on_slider_move(self, pos_ms: int):
        '''
        Emits the 'sign_cursor_moved' signal with the updated position

        Parameters
        ----------
        pos_ms: int
            The updated player position in milliseconds
        '''
        self.sign_cursor_moved.emit(pos_ms*10**-3, 0.0, "audio")
        self._player.on_cursor_move(pos_ms)

    @Slot()
    def _on_slider_released(self, pos_ms: int):
        '''
        Emits the 'sign_cursor_move_ended' signal with the updated position.

        Parameters
        ----------
        pos_ms: int
            The updated player position in milliseconds.
        '''
        self.sign_cursor_move_ended.emit(pos_ms*10**-3, 0, "audio")

        # Update also the underlying player
        self._player.on_cursor_move_ended(pos_ms)
        
        # There is a lag between signal connections when buffering audio, and since we want to
        # always resume audio play after the slider is released, we call play() also here.
        self._player.play()
