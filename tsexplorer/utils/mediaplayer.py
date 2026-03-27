""" This file defines some small utilities for handling media"""

from . import logger
from ..utils.misc import clamp
from ..utils.vlc_utils import EventBlocker, VLC_ATTACH_SUCCESS
from ..metadata import MediaPlayerState

from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtWidgets import QFrame

from scipy.io.wavfile import write as write_wav
import tempfile
import numpy as np
import time
import platform
import pathlib
import multiprocessing as mp # For lock
from ..extern.vlc import vlc # Use vlc for the playing the actual videos/audios

from typing import Optional


class MediaPlayer(QObject):
    '''
    Defines a media player backend, that is capable of playing wav-files from
    raw memory buffers.

    Signals
    -------
    sign_error: str
        Emitted in case the player has an error. Contains the error message.
    sign_position_changed: int
        Emitted when the position of the player changes. Contains the new
        position as milliseconds.
    sign_state_changed: MediaPlayerState
        Emitted when the underlying state of the media-player changes. Contains
        the updated state (as an int).
    sign_duration_changed: int
        Emitted when the duration of the underlying data has changed. Contains
        the new duration
    '''
    sign_error = Signal(str, name="sign_error")
    sign_position_changed = Signal(float, name="sign_position_changed")
    sign_state_changed = Signal(int, name="sign_state_changed")

    sign_duration_changed = Signal(int, name="sign_duration_changed")

    # The interval for sending the position update intervals
    _UPDATE_INTERVAL_MS: int = 100

    def __init__(
            self, parent: Optional[QObject] = None
            ):
        super().__init__(parent)
        self._logger = logger.get_logger("mediaPlayer")

        # The VLC event system uses internally threads, and thus it is possible
        # that the event handlers cause a race-condition
        self._lock = mp.Lock()
        
        # We want to remove unnecessary overlay text and to disable hardware decoding (avoids GPU driver issues)
        # Set --verbose=2 if you want all of the VLC events printed on the command line
        flags = ["--verbose=2", "--no-video-title-show", "--avcodec-hw=none"]

        # OpenGL is more stable on Linux and macOS, Direct3D9 is more stable on Windows
        if platform.system() == "Linux":
            flags.append("--no-xlib") # Prevents crashes on Wayland-based Linux systems
            flags.append("--vout=opengl")
        elif platform.system() == "Windows":
            flags.append("--vout=direct3d9")
        elif platform.system() == "Darwin":
            flags.append("--vout=opengl")
        
        # Initialize the VLC instance
        self._instance = vlc.Instance(*flags)

        # The (currently empty) media-player.
        self._media_player = self._instance.media_player_new()

        # The currently played media will be stored here
        self._media = None

        # Set to True, if the player should be stopped manually before playing
        self._should_stop = False
        # Set to True, if the player was playing the user started to move the
        # cursor
        self._was_playing = False

        self._start_time_ms = 0
        # As the VLC doesn't directly attach to the Qt's event loop, we use the
        # VLC's event system and translate those events back to Qt's event
        # system.
        # NOTE: These event handlers will be called from different threads
        # -> Make sure that none of them will access any shared state
        self._event_mngr = self._media_player.event_manager()
        self._connect_events()
        self._player_state: MediaPlayerState = MediaPlayerState.STOPPED

    def connect_to_frame(self, frame: QFrame):
        '''
        Connect the player to a certain QFrame, which is used for displaying
        possible contents of the file.

        Parameters
        ----------
        frame: QFrame
            The frame where the video will be displayed at.
        '''
        window_id = int(frame.winId())
        # The exact implementation of this depends on the used platform.
        if platform.system() == "Linux":
            # for Linux using the X Server.
            # NOTE: Should work in Wayland under XWayland. The current GTK3
            # build of VLC seems to use similar solution under wayland
            self._media_player.set_xwindow(window_id)
        elif platform.system() == "Windows":
            # for Windows
            self._media_player.set_hwnd(window_id)
        elif platform.system() == "Darwin":
            # for MacOS
            self._media_player.set_nsobject(window_id)

    def get_duration(self) -> Optional[int]:
        '''
        Returns the duration of the current media in milliseconds. If no media
        is set, or the duration cannot be queried, returns None.
        '''
        if self._media is None:
            return None
        # Returns -1 on error -> Convert to None
        dur = self._media.get_duration()
        return dur if dur != -1 else None

    @Slot(object)
    def set_data(self, filepath: pathlib.Path):
        '''
        Updates the data that is played from the widget

        Parameters
        ----------
        filepath: pathlib.Path
            Path to the file containing the wav-file.
        '''
        # Just assume that the given media type is supported, and don't do any
        # extra checks.
        # Create new media, and set it to play
        self._media = self._instance.media_new(str(filepath))
        self._media_player.set_media(self._media)

        # Parse the metadata (to get e.g. the duration of the data)
        self._media.parse()

        new_duration = self._media.get_duration()
        self.sign_duration_changed.emit(new_duration)

    @Slot(int)
    def on_cursor_move(self, pos_ms: int):
        '''
        Called when the user has moved the cursor.

        Parameters
        ----------
        pos_ms: int
            The updated position in milliseconds
        '''
        
        if not self._media_player.is_playing():
            self._media_player.play()
            
            # Wait briefly to allow decoding to start
            time.sleep(0.05)  # 50 ms is usually enough
            self._media_player.pause()
        else:
            self._media_player.pause()
            self.sign_state_changed.emit(int(MediaPlayerState.PAUSED))  # Emit paused state

        self._seek(pos_ms)

        # Only update frame if video is attached
        # get_hwnd() --> Windows
        # get_xwindow() --> Linux
        # get_nsobject() --> macOS
        if self._media_player.get_hwnd() or self._media_player.get_xwindow() or self._media_player.get_nsobject():
            self._media_player.set_pause(1) # 1 = VLC enters paused mode, but renders the frame at the current playback position. 0 = VLC resumes playback.

    @Slot(int)
    def on_cursor_move_ended(self, offset_ms: int):
        '''
        Called when the 'cursor' has moved to its final position. Currently
        updates the player position.

        Parameters
        ----------
        offset_ms: int
            The new position as milliseconds
        '''
        
        duration = self._media.get_duration()
        
        # clamp the new position to a reasonable range
        x = clamp(offset_ms, 0, duration)
        self._seek(x)

        # Always resume playback after slider release
        self._media_player.play()
        self._player_state = MediaPlayerState.PLAYING
        self.sign_state_changed.emit(int(self._player_state))

    @Slot()
    def play(self):
        '''
        Start to play the media from the current location of the buffer
        '''
        # If already called, do nothing
        if self._media_player.is_playing():
            return

        # For some reason the player must be explicitly stopped if the sample
        # has ended. Otherwise the audio won't play again
        if self._should_stop:
            self._should_stop = False
            self._force_stop()

        self._logger.debug(f"Starting to play from {self._start_time_ms} (ms)")
        self._media_player.play()
        self._media_player.set_time(self._start_time_ms)
        self._start_time_ms = 0
        self._player_state = MediaPlayerState.PLAYING
        self.sign_state_changed.emit(int(self._player_state))

    @Slot()
    def pause(self):
        ''' Pause the player to its current state.'''
        if not self._media_player.is_playing():
            return

        self._player_state = MediaPlayerState.PAUSED
        self._media_player.pause()
        self.sign_state_changed.emit(int(self._player_state))

    @Slot()
    def stop(self):
        ''' Stop the player, and reset it to its original state'''

        # Remove the event handler to ensure that no unnecessary signals
        # are sent.
        with EventBlocker(
                self._event_mngr, vlc.EventType.MediaPlayerStopped,
                self._on_stopped
                ):
            self._media_player.stop()
        self._player_state = MediaPlayerState.STOPPED
        self.sign_state_changed.emit(int(self._player_state))

    def set_time(self, new_time_ms: int):
        '''
        Sets the player to the given time (expressed from the beginning of the media)
        
        Parameters
        ----------
        new_time_ms: int
            The new time for the media (in milliseconds)
        '''
        self._seek(new_time_ms)

    def _connect_events(self):
        ''' Connects all relevant event handlers'''
        # The VLC has extensive event system, which is used here to map back to
        # Qt's signals and slot system

        event_types = [
                vlc.EventType.MediaPlayerTimeChanged,
                vlc.EventType.MediaDurationChanged,
                vlc.EventType.MediaPlayerEncounteredError,
                vlc.EventType.MediaPlayerStopped
        ]

        event_handlers = [
                self._on_media_time_change,
                self._on_duration_change,
                self._on_error,
                self._on_stopped,
        ]

        for event, handler in zip(event_types, event_handlers):
            out = self._event_mngr.event_attach(event, handler)
            if out != VLC_ATTACH_SUCCESS:
                raise RuntimeWarning(f"Failed to attach handler for {event}")

        # NOTE: Currently just hope that the audio has buffered enough.
        # Getting more exact buffering information would require wrapping
        # the libvlc_event_t p_obj union.
        # self._event_mngr.event_attach(
        #         vlc.EventType.MediaPlayerBuffering, self._on_buffering
        # )

    def _seek(self, offset_ms: int):
        '''
        Seek the position of the data

        Parameters
        ----------
        offset_ms: int
            The offset from the start in milliseconds
        '''
        if self._media is None:
            return

        # There is no media playing -> Setting the value won't do anything
        # -> Set starting point to be at the given offset
        if not self._media_player.is_playing():
            self._start_time_ms = offset_ms
            return

        # Otherwise, set the time
        self._logger.debug(f"Setting position to {offset_ms}")
        self._media_player.set_time(offset_ms)

    def _force_stop(self):
        '''
        Stop the player manually, without activating the
        vlc.EventType.MediaPlayerStopped event
        '''
        with EventBlocker(
                self._event_mngr, vlc.EventType.MediaPlayerStopped,
                self._on_stopped
                ):
            self._media_player.stop()

    def _on_media_time_change(self, event: vlc.Event):
        '''
        Called when the time of the media has changed
        (i.e. the audio has progressed). Notifies the listeners of
        'sign_position_changed' about the new position.
        NOTE: The VLC seems to have quite a low polling rate, and thus this
        is not updated very often.

        Parameters
        ----------
        event: vlc.Event
            A standard VLC event.
        '''
        # This can be called from a different thread -> Acquire lock
        with self._lock:
            new_pos = self._media_player.get_time()
            self.sign_position_changed.emit(new_pos)

    def _on_duration_change(self, event: vlc.Event):
        '''
        Called when the duration of the media has changed. In most practical
        situations this won't be called, as we are not streaming data, and
        thus the duration of a single media does not change during its
        lifetime.

        Parameters
        ----------
        event: vlc.Event
            Standard VLC event.
        '''
        # This can be called from a different thread -> Acquire lock
        with self._lock:
            new_duration = self._media.get_duration()
            self.sign_duration_changed.emit(new_duration)

    def _on_error(self, event: vlc.Event):
        '''
        Called when the media player encounters an error event.

        Parameters
        ----------
        event: vlc.Event
            The corresponding event.
        '''
        # This can be called from a different thread -> Acquire lock
        with self._lock:
            # The event doesn't contain any information about the error, and
            # parsing the VLC's error information is not straight forward.
            # -> Display a generic error message for now
            self.sign_error.emit("MediaPlayer backend encountered an error!")

    def _on_stopped(self, event: vlc.Event):
        '''
        Called when the media is stopped. Notifies listeners of
        'sign_state_changed' about the change in the state.

        Parameters
        ----------
        event: vlc.Event
            Standard VLC event.
        '''
        # This can be called from a different thread -> Acquire lock
        with self._lock:
            self._player_state = MediaPlayerState.STOPPED
            self.sign_state_changed.emit(int(self._player_state))
            self._should_stop = True
    
    def set_data_from_numpy(self, audio_data: np.ndarray, sample_rate: int):
        '''
        Converts a NumPy array to a temporary WAV file and loads it.
        '''
        
        # Convert to supported format
        if audio_data.dtype == np.float16:
            audio_data = audio_data.astype(np.float32)
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=".wav") as tmp_wav:
            write_wav(tmp_wav.name, sample_rate, audio_data)
            self.set_data(pathlib.Path(tmp_wav.name))
