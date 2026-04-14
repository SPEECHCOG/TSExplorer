from .mediacontrols import MediaControls
from ..metadata import WidgetType, MediaPlayerState
from ..utils.mediaplayer import MediaPlayer
from ..utils.logger import get_logger
from ..utils.misc import clamp
from tsexplorer.utils.io import load_numpy

import platform
import pathlib
# For validating the kwargs
from schema import Schema, Optional, Use, And

from PySide6 import QtWidgets
from PySide6.QtWidgets import QWidget, QFrame, QGridLayout
from PySide6.QtCore import QObject, Signal, Slot
from PySide6 import QtGui

from typing import Optional as Optional_t
from typing import Mapping, Any, Tuple, Dict


class VideoWidget(QWidget):
    '''
    Defines a video widget that can be used to play video clips from a given
    starting point.

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
        Emitted when the player is ready to play.
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
        Optional("source_path"): Use(str),
        Optional("source_dirs"): [Use(str)],
        Optional("auto_play", default=False): bool,
        Optional("looped_play", default=False): bool,
    
        # The following are ignored when source_dirs is provided
        Optional("clip_length_s", default=0.0): And(Use(float), lambda x: x > 0),
        Optional("overhead_before_clip_ms", default=0.0): And(Use(float), lambda x: x >= 0),
        Optional("overhead_after_clip_ms", default=0.0): And(Use(float), lambda x: x >= 0),
        Optional("overlap_s", default=0.0): And(Use(float), lambda x: x > 0),
        Optional("id_mapping_numpy_file"): Use(str),
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

        kwargs = self._KWARGS_SCHEMA.validate(kwargs)
        
        self._logger = get_logger("video-widget")
        
        self._use_dir_mode = kwargs.get("source_dirs", None) is not None

        if self._use_dir_mode:
            dirs = kwargs["source_dirs"]
            
            if isinstance(dirs, list):
                if len(dirs) != 1:
                    raise ValueError("VideoWidget only supports one directory in source_dirs.")
                src_dir = pathlib.Path(dirs[0])
            else:
                raise ValueError("source_dirs must be a list of strings.")

            if not src_dir.is_dir():
                raise ValueError(f"source_dirs entry is not a directory: {src_dir}")

            # Collect all video files (simple approach)
            self._video_files = sorted(
                p for p in src_dir.iterdir()
                if p.suffix.lower() in {".mp4", ".avi", ".mov", ".mkv"}
            )
            if len(self._video_files) == 0:
                raise ValueError("source_dirs contains no usable video files.")

            self._logger.debug(f"Loaded {len(self._video_files)} videos from {src_dir}")

        else:
            if "source_path" not in kwargs:
                raise ValueError("Either source_dirs or source_path must be provided.")

            self._fp = pathlib.Path(kwargs.get("source_path"))

        # These will be set on '_create_layout'
        self._frame = None
        self._controls = None
        self._palette = None
        
        # Create the UI
        self._create_layout()
        
        self._player = MediaPlayer(self)
        self._player.connect_to_frame(self._frame)

        if not self._use_dir_mode:
            self._player.set_data(self._fp)        

        self._logger.debug(f"Using auto-play?: {kwargs.get('auto_play')}")
        
        if not self._use_dir_mode:
            overlap_s = kwargs.pop("overlap_s")
            kwargs["overlap_ms"] = 1e3 * overlap_s

            clip_length_s = kwargs.pop("clip_length_s")
            kwargs["clip_length_ms"] = 1e3 * clip_length_s

            # If the user provided a Numpy file containing ID mappings, load it and use it in _get_start_and_stop_times
            self._id_mapping_list = None
            id_mapping_numpy_file = kwargs.get("id_mapping_numpy_file", None)
            if id_mapping_numpy_file:
                try:
                    self._logger.debug(f"Loading ID mapping NumPy file from: {id_mapping_numpy_file}")
                    self._id_mapping_list = load_numpy(pathlib.Path(id_mapping_numpy_file))
                except Exception as e:
                    self._logger.error(f"Failed to load ID mapping NumPy file: {e}")
                    self.sign_error.emit(f"Failed to load ID mapping NumPy file: {e}")
        else:
            self._id_mapping_list = None

        self._props: Dict[str, Any] = kwargs
        
        # Set to True if the overlap could be applied
        self._left_overlap: bool = False
        self._right_overlap: bool = False

        self._ready: bool = False
        self._wtype: WidgetType = WidgetType.VIDEO
        self._requires_update: bool = True
        
        # We define dummy values for directory mode so that the player state resets do not fail
        if self._use_dir_mode:
            self._start_time_ms = 0
            self._stop_time_ms = 0

        self._player.sign_state_changed.connect(self._on_player_state_change)

        self._player.sign_error.connect(self._on_player_error)
        self._player.sign_position_changed.connect(self._on_player_update)

        # Connect controls to the actual player
        self._controls.sign_started.connect(self._player.play)
        self._controls.sign_paused.connect(self._player.pause)
        self._controls.sign_stopped.connect(self._player.stop)

        # Connect controls to the video widget
        self._controls.sign_slider_moved.connect(self._on_slider_move)
        self._controls.sign_slider_released.connect(self._on_slider_released)

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

        Parameters
        ----------
        data: Mapping[str, Any]
            The data to play out. Should contain only one value.
        '''
        
        order_num = next(iter(data.values()))

        if self._use_dir_mode:
            # No video slicing --> straightforward file index
            if not (0 <= order_num < len(self._video_files)):
                raise IndexError("Video index out of range.")

            fp = self._video_files[order_num]
            self._player.set_data(fp)

            # Dummy duration update because the slider needs something
            dur_ms = self._player.get_duration()
            self._controls.on_duration_changed(dur_ms)
            self._controls.on_position_change(0)

            if not self._ready:
                self._ready = True
                self.sign_ready.emit()
            elif self._props["auto_play"]:
                self._player.play()
            return

        # Single-video logic
        start_ms, stop_ms = self._get_start_and_stop_times(order_num)
        self._start_time_ms = start_ms
        self._stop_time_ms = stop_ms

        dur_ms = stop_ms - start_ms
        self._player.set_time(start_ms)
        self._controls.on_duration_changed(dur_ms)
        self._controls.on_position_change(0)

        if not self._ready:
            self._ready = True
            self.sign_ready.emit()
        
        # If every widget is ready and auto play is on, start to play the clip.
        elif self._props["auto_play"]:
            self._player.play()


    def shutdown(self):
        ''' Does the needed cleanup before shutting down. Currently no-op'''
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
        # Convert the timestamp to relative position of the cursor in the media
        # controls
        pos_ms = int(1e3*x)
        if self._left_overlap:
            pos_ms += int(self._props["overlap_ms"])
        self._controls.on_position_change(pos_ms)

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

        # Convert the timestamp into an absolute timestamp for the player
        abs_pos_ms = int(1e3*x) + self._start_time_ms
        if self._left_overlap:
            abs_pos_ms += int(self._props["overlap_ms"])

        # The control should already be in correct state, so update just the
        # underlying media player this time.
        self._player.on_cursor_move_ended(abs_pos_ms)

    @Slot()
    def on_startup(self):
        ''' Handler that is called just before the annotation will start. '''
        if self._props["auto_play"]:
            self._player.play()

    def _create_layout(self):
        '''
        Creates the layout for the video-player.
        '''
        layout = QGridLayout()
        # The video will be displayed in the QFrame.
        self._controls = MediaControls(self)

        # On MacOS, use the native system container to embed the video-player
        # seems to be removed -> Use QFrame on all platforms

        self._frame = QFrame()

        # if platform.system() == "Darwin":
        #     self._frame = QtWidgets.QMacCocoaViewContainer(0)
        # else:
        #     self._frame = QFrame()

        self._palette = self._frame.palette()
        self._palette.setColor(QtGui.QPalette.Window, QtGui.QColor(0, 0, 0))
        self._frame.setPalette(self._palette)
        self._frame.setAutoFillBackground(True)

        # Use ratio of 3/4 and 1/4 of the available space for the video
        # and controls
        layout.addWidget(self._frame, 0, 0, 3, 1)
        layout.addWidget(self._controls, 3, 0)
        self.setLayout(layout)

    @Slot()
    def _on_player_update(self, pos_ms: int):
        '''
        Called when the player updates its position.

        Parameters
        ----------
        pos_ms: int
            The updated position in milliseconds.
        '''
        
        if self._use_dir_mode:
            # No video slicing --> we don't use the "overlapping" logic
            self.sign_cursor_moved.emit(pos_ms * 1e-3, 0.0, "video")
            self._controls.on_position_change(pos_ms)

            if self._props["looped_play"]:
                # We want to seek slightly before the end of the file so that VLC never reaches its STOPPED
                # state to make things run smoother (closing and then reopening the file causes lag)
                if self._player.get_duration() - pos_ms < 300: # 300-ms tolerance since MP4s can stop 20-280 ms too early (key frames)
                    self._player.set_time(0)
                    #self._player.play()
            return
        
        # NOTE: Now the pos_ms is the absolute position of the player, while we want the position in relation to the current clip!
        rel_pos_ms = pos_ms - self._start_time_ms
        if self._left_overlap:
            rel_pos_ms -= int(self._props["overlap_ms"])
        rel_pos_ms = clamp(rel_pos_ms, 0, int(self._props["clip_length_ms"]))

        self.sign_cursor_moved.emit(rel_pos_ms*10**-3, 0.0, "video")

        # The controls cursor position is the current position - start-time
        self._controls.on_position_change(pos_ms - self._start_time_ms)
        
        if self._props["looped_play"]:
            # Check if we have reached the end of the video, and start playing the video from the beginning
            if pos_ms >= self._stop_time_ms:
                self._player.set_time(self._start_time_ms)
                self._player.play()
        else:
            # Check if we have reached the end of the video, and stop the player
            if pos_ms >= self._stop_time_ms:
                # We want to ensure we have the correct preview frame displayed (i.e. first frame of the video clip),
                # otherwise the GUI will mistakenly display a preview of the very first frame of the long video.
                self._player.set_time(self._start_time_ms)
                
                # Only after that, we actually stop the video
                self._player.stop()
                self._player.sign_state_changed.emit(int(MediaPlayerState.STOPPED))
                
                
                
                

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
                
        if self._use_dir_mode:
            if state == MediaPlayerState.STOPPED:
                if self._props.get("looped_play", False):
                    self._player.set_time(0)
                    self._player.play()
                else:
                    self.sign_cursor_moved.emit(0.0, 0.0, "video")
                return

        if state == MediaPlayerState.STOPPED:
            self.sign_cursor_moved.emit(0.0, 0.0, "video")
            # Reset the media-player to the correct starting point
            self._player.set_time(self._start_time_ms)
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
    def _on_slider_move(self, rel_pos_ms: int):
        '''
        Emits the 'sign_cursor_moved' signal with the updated position

        Parameters
        ----------
        rel_pos_ms: int
            The updated player position in milliseconds. NOTE: this position is
            relative to the start of the slider (0 ms).
        '''
        self._logger.debug(f"Cursor position {rel_pos_ms}")
        
        if self._use_dir_mode:
            # Directory mode --> direct movement
            self.sign_cursor_moved.emit(rel_pos_ms * 1e-3, 0.0, "video")
            self._player.on_cursor_move(rel_pos_ms)
            return
        
        extern_pos_ms = rel_pos_ms
        if self._left_overlap:
            extern_pos_ms -= int(self._props["overlap_ms"])
        extern_pos_ms = clamp(extern_pos_ms, 0, int(self._props["clip_length_ms"]))

        self.sign_cursor_moved.emit(extern_pos_ms*10**-3, 0.0, "video")
        abs_pos_ms = self._start_time_ms + rel_pos_ms
        if self._left_overlap:
            abs_pos_ms += int(self._props["overlap_ms"])
        self._player.on_cursor_move(abs_pos_ms)

    @Slot()
    def _on_slider_released(self, rel_pos_ms: int):
        '''
        Emits the 'sign_cursor_move_ended' signal with the updated position.

        Parameters
        ----------
        rel_pos_ms: int
            The updated player position in milliseconds. Note that this
            position is relative to the start of the slider (0 ms).
        '''

        if self._use_dir_mode:
            # Directory mode --> direct movement
            self.sign_cursor_move_ended.emit(rel_pos_ms * 1e-3, 0, "video")
            self._player.on_cursor_move_ended(rel_pos_ms)
            return
        
        # Calculate the position for the external cursors (which don't know
        # about the overlap)
        extern_pos_ms = rel_pos_ms
        if self._left_overlap:
            extern_pos_ms -= int(self._props["overlap_ms"])
        extern_pos_ms = clamp(extern_pos_ms, 0, int(self._props["clip_length_ms"]))
        self._logger.debug(f"Extern position: {extern_pos_ms}")
        self.sign_cursor_move_ended.emit(extern_pos_ms*10**-3, 0, "video")

        # Update also the underlying player
        abs_pos_ms = self._start_time_ms + rel_pos_ms

        self._logger.debug(f"Cursor pos: {rel_pos_ms}, player pos {abs_pos_ms}")
        self._player.on_cursor_move_ended(abs_pos_ms)

    def _get_start_and_stop_times(self, order_num: int) -> Tuple[int, int]:
        '''
        Calculates the start and stop times for the current clip.

        Parameters
        ----------
        order_num: int
            The order number of the clip to be played
        '''
        
        if self._use_dir_mode:
            raise RuntimeError("_get_start_and_stop_times should not be used in directory mode.")
        
        clip_length_ms = self._props["clip_length_ms"]
        overlap_ms = self._props["overlap_ms"]
        overhead_before_ms = float(self._props.get("overhead_before_clip_ms", 0.0))
        overhead_after_ms = float(self._props.get("overhead_after_clip_ms", 0.0))
        hop_ms = clip_length_ms - overlap_ms
        
        # We check if there is an ID mapping existing
        if self._id_mapping_list is not None:
            corrected_order_num = self._id_mapping_list[order_num]
        else:
            corrected_order_num = order_num
        
        # Base start and stop times
        base_start_ms = corrected_order_num * hop_ms
        base_stop_ms = base_start_ms + clip_length_ms
        
        # Apply overhead
        start_time_ms = max(0, round(base_start_ms - overhead_before_ms))
        stop_time_ms = round(base_stop_ms + overhead_after_ms)
        
        video_duration_ms = self._player.get_duration()

        # If the clip would go beyond the video duration for some reason, we clamp it
        stop_time_ms = min(stop_time_ms, video_duration_ms)
        
        # Set right overlap flag only if the clip is truncated
        self._right_overlap = (stop_time_ms < base_stop_ms + overhead_after_ms)

        return start_time_ms, stop_time_ms

