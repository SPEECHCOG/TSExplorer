from .. import defaults
from ..utils import convert
from ..utils import logger
from ..utils.misc import fontsize_to_int
from ..metadata import WidgetType

from typing import Dict, Mapping, Any
from typing import Optional as Optional_t  # To avoid name conflict

import numpy as np
import numpy.typing as npt

# For validating keyword arguments
from schema import Schema, And, Optional, Use

from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtCore import QObject, Slot, Signal
from PySide6.QtGui import QFont
import pyqtgraph as pg


class SpectrogramWidget(QWidget):
    '''
    This class is used to display spectrograms using Qt's graphing capabilities.

    Signals
    --------
    sign_cursor_moved: float, float, str
        Emitted when the vertical line used to mark current location in the
        temporal axis is moved. Contains the new x and y positions
        (x in seconds) and the name of the widget that emitted the signal.
    sign_cursor_move_ended: float, float, str
        Emitted when the move of the cursor stops completely. Contains the
        new x and y positions (x in seconds) and the name of the widget that
        emitted the signal.
    sign_ready:
        Emitted when the widget is ready (i.e. drawn the data)
    sign_error: str
        Emitted if the component encounters any issues. Contains the relevant
        error message
    '''
    sign_cursor_moved = Signal(float, float, str, name="sign_cursor_moved")
    sign_cursor_move_ended = Signal(
            float, float, str, name="sign_cursor_move_ended"
    )
    sign_ready = Signal(name="sign_ready")
    sign_error = Signal(str, name="sign_error")
    _styles: Dict[str, str] = {"color": "#000", "font-size": "14px"}

    _KWARGS_SCHEMA: Schema = Schema({
        "name": Schema(
            str, error=("Missing 'name'! This is likely an internal bug, "
                        "and not an user error")
            ),
        "n_mel":  And(int, lambda n: n > 0),
        "hop_ms": And(int, lambda n: n > 0),
        "sr": And(Use(float), lambda n: n > 0),
        Optional("source_dirs", default=None): [str]
    })

    def __init__(
            self, parent: Optional_t[QObject] = None,
            **kwargs: Mapping[str, Any]
            ):
        '''
        Creates a spectrogram widget, which displays a spectrogram from a given
        audio file.

        Parameters
        ----------
        parent: Optional[QObject]
            The parent object for this widget. Default None.
        kwargs: Mapping[str, Any]
            Possible keyword arguments. Currently all keyword arguments are
            dismissed.
        '''
        super().__init__(parent)
        self._logger = logger.get_logger("spectrogram")
        self._canvas = pg.PlotWidget()

        # Disable the context-menu
        fig = self._canvas.getPlotItem()
        fig.setMenuEnabled(False)

        self._mesh = None
        self._cbar = None
        self._vline = None
        layout = QVBoxLayout()
        layout.addWidget(self._canvas)
        self.setLayout(layout)

        # Validate and save the keyword arguments
        kwargs = self._KWARGS_SCHEMA.validate(kwargs)
        self._props: Dict[str, Any] = kwargs

        self._ready: bool = False

        # "constant" properties of the class
        self._wtype: WidgetType = WidgetType.SPECTROGRAM
        self._requires_update: bool = True

        # Extract font-style information from global options
        self._font_opts: Dict[str, str] = {
                "label":  {
                    "color": defaults.RCPARAMS["label-font"]["color"],
                    "fontsize": defaults.RCPARAMS["label-font"]["size"]
                },
                "ticks": {
                    "fontsize": defaults.RCPARAMS["tick-font"]["size"]
                }
        }

    @property
    def wtype(self) -> WidgetType:
        ''' Returns the type of this widget'''
        return self._wtype

    @property
    def requires_update(self) -> bool:
        '''
        Returns True if the widget needs to be updated during every sample
        '''
        return self._requires_update

    def set_data(self, data: Dict[str, npt.NDArray]):
        '''
        Sets the data for this widget, and displays it.

        Parameters
        ----------
        data: Dict[str, npt.NDArray]
            The data to display. Should contain only 1 item!
        '''

        if len(data) != 1:
            self.sign_error(f"Expected only 1 item, got {len(data)} items")
            return

        data = next(iter(data.values()))

        if self._mesh is None:
            # Create the coordinates for the plot, by first converting
            # the x values to frames
            x_coords = convert.frames_to_seconds(
                    np.arange(data.shape[1]+1), hop_ms=self._props["hop_ms"]
            )

            # And then convert the y-values to mel frequency bins
            y_coords = convert.to_mel_freqs(
                    self._props["n_mel"]+1, fmin=0.0,
                    fmax=0.5*self._props["sr"]
            )

            x, y = np.meshgrid(x_coords, y_coords, indexing='ij')
            self._mesh = pg.PColorMeshItem(
                    x, y, data.T, colorMap=pg.colormap.get("magma")
            )

            fig = self._canvas.getPlotItem()
            fig.addItem(self._mesh)

            # Create the colorbar
            self._cbar = pg.ColorBarItem(
                    limits=(data.min(), data.max()),
                    values=(data.min(), data.max()),
                    colorMap="magma", interactive=False
            )
            # Add the colorbar to the right-most column, and make it span the
            # along the whole height of the plot
            ncols = fig.layout.columnCount()
            nrows = fig.layout.rowCount()
            fig.layout.addItem(self._cbar, 0, ncols+1, nrows-1, 1)

            fig.setLabel("bottom", "Time", units='s', **self._font_opts["label"])
            fig.setLabel("left", "Frequency", units="hz", **self._font_opts["label"])
            fig.setXRange(0, x_coords.max())
            fig.setYRange(0, y_coords.max())
            fig.setMouseEnabled(x=False, y=False)
            fig.disableAutoRange()

            # If tick-fontsize is provided ,use it
            if self._font_opts["ticks"]["fontsize"] is not None:
                fontsize = fontsize_to_int(self._font_opts["ticks"]["fontsize"])
                font = QFont("Times", fontsize)
                fig.getAxis("bottom").setTickFont(font)
                fig.getAxis("left").setTickFont(font)

            # Add the horizontal line that indicates the current time.
            self._vline = fig.addLine(
                    x=0, movable=True, pen=pg.mkPen("#F51320"),
                    bounds=(0, x_coords.max())
            )
            self._vline.sigPositionChanged.connect(
                    self._on_cursor_move_internal
            )
            self._vline.sigPositionChangeFinished.connect(
                    self._on_cursor_move_ended_internal
            )
        else:
            x_coords = convert.frames_to_seconds(
                    np.arange(data.shape[1]+1), hop_ms=self._props["hop_ms"]
            )
            y_coords = convert.to_mel_freqs(
                    self._props["n_mel"]+1, fmin=0.0,
                    fmax=0.5*self._props["sr"]
            )
            # y_coords = np.arange(data.shape[0]+1)
            x, y = np.meshgrid(x_coords, y_coords, indexing="ij")
            self._mesh.setData(x, y, data.T)

            fig = self._canvas.getPlotItem()
            fig.setXRange(0, x_coords.max())
            fig.setYRange(0, y_coords.max())

            self._cbar.setLevels((data.min(), data.max()))

            # Reset the vline position and set the correct bounds for it
            was_blocked = self._vline.blockSignals(True)
            self._vline.setBounds((0, x_coords.max()))
            self._vline.setValue(0)
            self._vline.blockSignals(was_blocked)

        # Ensure that the signal is emitted only once
        if not self._ready:
            self._ready = True
            self.sign_ready.emit()

    def shutdown(self):
        '''
        Called when the application is going to shutdown. Currently, does
        nothing
        '''
        return

    @Slot()
    def on_cursor_move(self, x: float, y: float, name: str):
        '''
        Handler for event where the 'cursor' line is moved. If the moved line
        is inside the current plot, does nothing. If signal was sent from a
        another plot, syncs the cursor positions.

        Parameters
        ----------
        x: float
            The new x position.
        y: float
            The new y position.
        name: str
            The name of the widget that emitted the message.
        '''
        if name == self._props["name"]:
            return
        was_blocked = self._vline.blockSignals(True)
        self._vline.setValue((x, y))
        self._vline.blockSignals(was_blocked)

    @Slot()
    def on_cursor_move_ended(self, x, y, name: str):
        '''
        Handler for cases where the 'cursor' movement has ended. Currently
        doesn't do anything (as 'on_cursor_move' is used for real-time updates)

        Parameters
        ----------
        x: float
            The new x position.
        y: float
            The new y position.
        name: str
            The name of the widget that emitted the signal.
        '''
        return

    @Slot()
    def on_startup(self):
        ''' Called just before the annotation is started. No-op'''
        return

    @Slot()
    def _on_cursor_move_internal(self, line: pg.InfiniteLine):
        '''
        Internal implementation for handling the cursor move.

        Parameters
        ----------
        line: pg.InfiniteLine
            The moved line

        '''
        x, y = tuple(line.pos())
        self.sign_cursor_moved.emit(x, y, self._props["name"])

    def _on_cursor_move_ended_internal(self, line: pg.InfiniteLine):
        '''
        Internal implementation for handling the cursor move stopped signal.
        Just converts the signal to match the signal defined in the API.

        Parameters
        ----------
        line: pg.InfiniteLine
            The moved line
        '''
        x, y = tuple(line.pos())
        self.sign_cursor_move_ended.emit(x, y, self._props["name"])
