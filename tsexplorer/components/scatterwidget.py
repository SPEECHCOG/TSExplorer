'''
This file defines a widget that shows an embedded scatterplot from matplotlib
'''
from .. import defaults
from ..utils import colorbase
from ..utils import io
from ..utils.misc import rgba_to_str, rgba_to_ints, fontsize_to_int, deprecated
from ..utils.logger import get_logger
from ..metadata import SampleID, Path, SampleState, WidgetType

from typing import Mapping, Dict, Any, Tuple, List, Iterable
from typing import Optional as Optional_t  # To avoid name conflict
import pathlib
import warnings
import itertools as it

import numpy as np
import numpy.typing as npt

# For validating the kwargs
from schema import Schema, Optional, Regex

from PySide6.QtCore import QObject, Slot, Signal, Qt, QPointF
from PySide6.QtWidgets import QWidget, QVBoxLayout
from PySide6.QtGui import QMouseEvent, QPen, QBrush, QFont

import matplotlib as mpl
import pyqtgraph as pg


class ScatterWidget(QWidget):
    '''
    A Qt widget that embeds a matplotlib plot to the component. Supports also
    a cursor that displays the current setting.


    Signals
    --------
    sign_ready
        Emitted when the widget is in usable state (i.e. data is set)
    sign_cursor_moved: float, float, str
        Emitted when the cursor starts moving.
    sign_cursor_move_ended: float, float, str
        Emitted when the cursor moving has ended.
    sign_error: str
        Emitted if the component encounters any issues. Contains the relevant
        error message
    sign_user_selected_sample: SampleID
        Emitted when user clicks a sample from the scatter plot to put a sample
        to a queue
    sign_user_set_sample: SampleID
        Emitted when the user clicks a sample from the scatter plot, and wants
        to change the current sample to this sample.
    '''
    sign_ready = Signal(name="sign_ready")
    sign_cursor_moved = Signal(float, float, str, name="sign_cursor_moved")
    sign_cursor_move_ended = Signal(
            float, float, str, name="sign_cursor_move_ended"
    )
    sign_error = Signal(str, name="sign_error")
    sign_user_selected_sample = Signal(int, name="sign_user_selected_sample")
    sign_user_set_sample = Signal(int, name="sign_user_set_sample")

    # Some constants for ease of use.
    _HOVER: str = "hover"
    _DEFAULT_COLORS: List[str] = colorbase.get_colors("default")

    _KWARGS_SCHEMA: Schema = Schema({
        "name": Schema(
            str, error=("Missing 'name'! This is likely a internal bug ",
                        "and not an user error!")
        ),
        "labels": Schema(
            [str], error=("Missing 'labels'! This is likely a internal bug ",
                          "and not an user error!")
        ),
        Optional("source_path", default=None): str,
        Optional(
            "colors", default=None
            ): Schema([Regex("^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")]),

        Optional("cmap", default=None): str,
        Optional("base_marker_size", default=10): int,
        Optional("plot_title", default=None): str,
        Optional("plot_title_fontsize", default="12pt"): str,
        Optional("multiple_modalities", default=False): bool,
        Optional("source_paths", default=None): [str],
        Optional("modality_names", default=None): [str],
    })

    def __init__(
            self, parent: Optional_t[QObject] = None,
            **kwargs: Mapping[str, Any]
            ):
        '''
        The constructor for the widget.

        Parameters
        ----------
        parent: Optional[QObject]
            The parent of this widget. Default None.
        kwargs: Mapping[str, Any]
            Optional keyword arguments. Currently used arguments:
                - labels: List[str]
                - name: str
                - source_path: str
                - colors: str, Optional,
        '''
        super().__init__(parent)

        self._logger = get_logger("scatter-widget")
        layout = QVBoxLayout()

        self._canvas = pg.PlotWidget()

        # Disable context-menu
        fig = self._canvas.getPlotItem()
        fig.setMenuEnabled(False)

        self._scatters: Dict[str, pg.ScatterPlotItem] = {}

        layout.addWidget(self._canvas)
        self.setLayout(layout)

        # Validate the keyword arguments
        kwargs = self._KWARGS_SCHEMA.validate(kwargs)

        # Initialize modality index
        self._active_modality = 0

        self.multiple_modalities = kwargs.get("multiple_modalities", False)
        
        # Check if we want to display multiple data modalities
        if self.multiple_modalities:
            if not kwargs.get("source_paths"):
                raise ValueError("When multiple_modalities=True, 'source_paths' is required.")
            if not kwargs.get("modality_names"):
                raise ValueError("When multiple_modalities=True, 'modality_names' is required.")

            self._source_paths = kwargs["source_paths"]
            self._modality_names = kwargs["modality_names"]

            if len(self._source_paths) < 2:
                raise ValueError("multiple_modalities=True requires at least two source_paths.")
            if len(self._modality_names) != len(self._source_paths):
                raise ValueError("'modality_names' must match number of 'source_paths'.")
            kwargs["source_path"] = self._source_paths[0]
        else:
            # We display only a single modality
            if not kwargs.get("source_path"):
                raise ValueError("When multiple_modalities=False, 'source_path' is required.")

            self._source_paths = [kwargs["source_path"]]
            self._modality_names = ["default"]

        self._props: Dict[str, Any] = kwargs
        
        self.base_marker_size = self._props.get("base_marker_size", 10)
        
        self._plot_title = kwargs.get("plot_title")
        self._plot_title_fontsize = kwargs.get("plot_title_fontsize")

        cmap: str = kwargs.get("cmap")
        colors = kwargs.pop("colors")

        self._props["colors"] = self._construct_colors(cmap, colors)
        brushes, pens = self._create_brushes_and_pens(
                it.cycle(self._props["colors"])
        )

        # Keep count of the current sample, and the lastly modified sample
        self._last_mod_sample: Optional[SampleID] = None
        self._last_mod_state: Optional[SampleState] = None

        # Keep count of the current sample and its state (needed for
        # highlighting the currently selected sample)
        self._current_sample: Optional[SampleID] = None
        self._current_state: Optional[SampleState] = None

        # All possible pens && brushes for this plot
        self._available_brushes: Dict[str, QBrush] = brushes
        self._available_pens: Dict[str, QPen] = pens

        # Store the list of brushes & pens used to paint a given point
        self._current_brushes = []
        self._current_pens = []

        # Store the points in a tree structure for rapid lookup
        self._scale: float = 0
        self._points: Optional_t[npt.NDArray] = None
        self._tree = None

        # Set to True when the widget can display the data.
        self._ready: bool = False

        # Some "constant" properties of the widget
        self._wtype: WidgetType = WidgetType.SCATTER
        self._requires_update: bool = False

        # The font-options
        self._font_opts: Dict[str, Dict[str, str]] = {
                "label": {
                    "fontsize": defaults.RCPARAMS["label-font"]["size"]
                },
                "ticks": {
                    "fontsize": defaults.RCPARAMS["tick-font"]["size"],
                }
        }
        
        self._overlays: Dict[int, pg.ScatterPlotItem] = {}
        self._overlay_states: Dict[int, str] = {}
        
        self._canvas.getViewBox().sigRangeChanged.connect(self._on_zoom)

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

    @property
    def file(self) -> Optional_t[str]:
        '''
        Returns the file used for the current dimensionality reduction. If multiple modalities are enabled, return the
        active modality path. Otherwise, return the single source_path.
        '''
        if self.multiple_modalities:
            return self._source_paths[self._active_modality]
        return self._props["source_path"]

    def set_modality(self, modality_index: int):
        ''' Sets the currently active modality. '''
        
        if not self.multiple_modalities:
            return
            
        if modality_index < 0 or modality_index >= len(self._source_paths):
            raise IndexError("Invalid modality index")
            
        self._active_modality = modality_index

    def set_data(self, data: npt.NDArray):
        '''
        Sets the data that is displayed in the widget. The data should be
        2-dimensional.
        Parameters
        ----------
        data: npt.NDArray
            The data to display
        Raises
        ------
        ValueError
            If the data is not 2-dimensional
        '''

        self._logger.debug("In 'set_data'")
        if (data.shape[0] != 2 and data.shape[1] != 2) or data.ndim != 2:
            raise ValueError(("Expected data with 2D features, but got"
                             f" {data.shape}"))

        if data.shape[0] == 2:
            data = data.T

        x, y = data[:, 0], data[:, 1]
        
        # Scale to [-1, 1] range
        x_min, x_max = np.min(x), np.max(x)
        y_min, y_max = np.min(y), np.max(y)

        x = 2 * (x - x_min) / (x_max - x_min) - 1
        y = 2 * (y - y_min) / (y_max - y_min) - 1

        # Currently, a separate ScatterPlotItem is created for each label, so
        # that the legend shows the correct values. However, all the points
        # are drawn to the 'un-selected' ScatterPlotItem, and then just colored
        # according to the state of the sample
        # (i.e. is it labeled or selected etc.)

        if len(self._scatters) == 0:
            # Set the widget to adjust automatically its boundaries when
            # the data-changes.

            self._legend = pg.LegendItem(
                    offset=(30, 5),
                    labelTextSize=self._font_opts["label"]["fontsize"]
            )
            
            self._legend.setBrush(pg.mkBrush(255, 255, 255, 200))  # White with alpha=200 (alpha is from 0 to 255 and it stands for opacity)
            self._legend.setPen(pg.mkPen(color='black', width=1))  # Thin black border for the legend
            self._legend.setParentItem(self._canvas.getPlotItem())
            
            # We want to lock the legend in place, so that nobody can accidentally move it away from the plot
            self._legend.mouseDragEvent = lambda ev: None
            
            # Add "current sample" legend item first
            current_sample_legend_item = pg.ScatterPlotItem(
                x=[0], y=[0],  # Dummy coordinates
                brush=pg.mkBrush(255, 255, 255, 0),  # Transparent brush
                pen=pg.mkPen("#ffea00", width=6),
                size=12,
                hoverable=False
            )
            self._legend.addItem(current_sample_legend_item, "current sample")

            # Add remaining legend items
            for key in [SampleState.SELECTED, *self._props["labels"]]:
                display_name = "queued" if key == SampleState.SELECTED else key
                marker_symbol = 's' if key == SampleState.SELECTED else 'o'
                
                if key == SampleState.SELECTED:
                    self.queued_sample_color = self._available_pens[key].color()
                
                # Legend-only item (fixed size)
                legend_item = pg.ScatterPlotItem(
                    x=[0], y=[0],  # Dummy coordinates
                    size=8,  # Fixed size
                    pen=self._available_pens[key],
                    brush=self._available_brushes[key],
                    symbol=marker_symbol,
                    hoverable=False
                )
                self._legend.addItem(legend_item, display_name)

                # Actual scatter item (zoom-responsive)
                sct = pg.ScatterPlotItem(
                    pen=self._available_pens[key],
                    brush=self._available_brushes[key],
                    hoverable=True,
                    tip=self._format_tooltip,
                    hoverBrush=self._available_brushes[self._HOVER],
                    name=display_name
                )
                self._scatters[key] = sct

                def make_mouse_click_event_handler(scatter_item):
                    def handler(ev):
                        if ev.button() in (Qt.MouseButton.LeftButton, Qt.MouseButton.RightButton):
                            pts = scatter_item.pointsAt(ev.pos())
                            if len(pts) > 0:
                                self._on_mouse_press(scatter_item, pts, ev)
                    return handler

                sct.mouseClickEvent = make_mouse_click_event_handler(sct)
                self._canvas.addItem(sct)

            self._scatters[SampleState.UNLABELED].setData(x, y)
            self._canvas.getPlotItem().showGrid(x=True, y=True)
            
            # If the plot title was specified, add it
            if self._plot_title is not None:
                self._canvas.getPlotItem().setTitle(self._plot_title, size=self._plot_title_fontsize,
                                                    color=self._font_opts["label"].get("color", "black"))

            # If the tick-fontsize was specified, use it
            if self._font_opts["ticks"]["fontsize"] is not None:
                fontsize = fontsize_to_int(self._font_opts["ticks"]["fontsize"])
                font = QFont("Times", fontsize)
                self._canvas.getAxis("bottom").setTickFont(font)
                self._canvas.getAxis("left").setTickFont(font)

        else:
            self._scatters[SampleState.UNLABELED].setData(x, y)
            # Make sure that all of the new points are visible
            self._canvas.autoRange()

        self._points = np.column_stack((x, y))

        # NOTE: Check if the pens are already set. If so, don't change them.
        # Otherwise set every one of those the to the base color
        # Set the brushes and pens
        self._maybe_set_colors()
        
        # Reconstruct overlays for labeled samples after data update
        for sample_id, state in self._overlay_states.items():
            x, y = self._points[sample_id]

            # Remove old overlay if it exists
            old_overlay = self._overlays.pop(sample_id, None)
            if old_overlay is not None:
                self._canvas.removeItem(old_overlay)
            
            if self.queued_sample_color == self._available_pens[state].color():
                marker_symbol = 's'
            else:
                marker_symbol = 'o'
            
            # Create new overlay with updated coordinates
            overlay = pg.ScatterPlotItem(
                x=[x], y=[y],
                brush=self._available_brushes[state],
                pen=self._available_pens[state],
                size=self.base_marker_size,
                data=[sample_id],
                symbol=marker_symbol,
                hoverable=True,
                tip=self._format_tooltip
            )
            overlay.setZValue(5)
            overlay.sigClicked.connect(self._on_overlay_clicked)
            self._canvas.addItem(overlay)
            self._overlays[sample_id] = overlay


        # Ensure that 'ready' signal is only emitted once.
        if not self._ready:
            self._logger.debug("Emitting 'sign_ready'")
            self._ready = True
            self.sign_ready.emit()
        
        # Re-highlight sample with yellow ring after data update (i.e. switching visualization algorithm)
        if self._current_sample is not None:
            self._highlight_selected_sample(self._current_sample)
        
        self._on_zoom()


    def shutdown(self):
        '''
        Called when the application is going to shutdown. Currently does
        nothing.
        '''
        return

    @Slot()
    def on_sample_state_change(self, sample_id: SampleID, state: str):
        '''
        Updates the state of a given sample by changing its color.

        Parameters
        ----------
        sample_id: SampleID
            The sample which state needs to updated
        state: str
            The new state for the given sample.

        Raises
        ------
        RuntimeError
            If the given state is unknown

        '''
        self._logger.debug(f"Got sid: {sample_id} and state: {state}")

        # If this is called before the data is ready, defer the application
        # of the coloring
        if not self._ready:
            self._current_sample = sample_id
            self._current_state = state
            return

        if state not in self._available_pens:
            self._logger.error((f"Unknown state {state!r}. Possible states "
                                f"are {', '.join(self._available_pens.keys())}"
                                ))
            self.sign_error.emit((f"Unknonw state {state!r}. Possible states "
                                  "are: "
                                  f"{','.join(self._available_pens.keys())}"))
            return

        # If the current sample is the same as the previous sample, we keep the
        # selected marker. Otherwise, we remove the selected marker from the
        # previous sample, and add it to the new sample

        # Cases
        # 1) The sample is same and state is unselected -> Update just the
        #    color of the sample, but keep the selected marker
        # 2) The sample is same, and state is SELECTED -> Update the color,
        #    but don't change the state of the previous sample
        # 3) The sample is new, and the last modified but the state is
        #    unselected -> New sample selected -> Change the selection marker
        # 4) The sample is same as the last modified and not a new sample and
        #    state is changed
        #   from selected to unselected -> Don't change selection marker.

        is_current_sample = (self._current_sample is not None and
                             self._current_sample == sample_id)
        is_last_modified = (self._last_mod_sample is not None and
                            self._last_mod_sample == sample_id)

        is_new_sample = not is_current_sample and not is_last_modified

        # Case 1 -> Pick sample for the first time -> Update color and ring
        # remove selection from last sample
        case1 = is_new_sample and state == SampleState.UNLABELED

        # Case 2 -> Is current sample but state annotated -> Update only color
        case2 = not is_new_sample and state == SampleState.ANNOTATED

        # Case 3 -> Is new sample, and the state is selected -> Update color,
        # don't remove ring
        case3 = (is_new_sample and state == SampleState.SELECTED)

        # Case 4 -> Is last modified, but not current and state is UNLABELED
        # -> Update color, don't remove the ring
        case4 = (not is_new_sample and is_last_modified
                 and state == SampleState.UNLABELED)

        self._logger.debug(f"Case 1: {case1} | 2 {case2} | 3 {case3} | 4 {case4}")

        if case1:
            self._current_pens[self._current_sample] = self._available_pens[
                    self._current_state
            ]

        # NOTE: if the sample was only selected, it is not processed yet, and
        # thus we don't make it "last_sample" yet.
        if state != SampleState.SELECTED:
            self._current_sample = sample_id
            self._current_state = state

        self._last_mod_sample = sample_id
        self._last_mod_state = state
        
        # Remove yellow ring overlay only if the current sample is being updated
        if sample_id == self._current_sample and self._current_sample is not None:
            old_ring = self._overlays.pop(f"ring_{self._current_sample}", None)
            if old_ring is not None:
                self._canvas.removeItem(old_ring)

        # In all cases set the new sample id to selected.
        #new_pen = self._available_pens[SampleState.SELECTED]
        new_brush = self._available_brushes[state]

        #self._current_pens[sample_id] = new_pen
        self._current_pens[sample_id] = self._available_pens[state]
        self._current_brushes[sample_id] = new_brush

        # Update the colors
        self._scatters[SampleState.UNLABELED].setPen(self._current_pens)
        self._scatters[SampleState.UNLABELED].setBrush(self._current_brushes)
        
        # Remove overlay if reverting to UNLABELED
        if state == SampleState.UNLABELED:
            overlay = self._overlays.pop(sample_id, None)
            if overlay is not None:
                self._canvas.removeItem(overlay)
                self._overlay_states.pop(sample_id, None)
        
        # Add overlay if labeling
        else:
            x, y = self._points[sample_id]

            # Remove previous overlay if it exists (e.g. re-labeling)
            old_overlay = self._overlays.pop(sample_id, None)
            if old_overlay is not None:
                self._canvas.removeItem(old_overlay)
            
            if self.queued_sample_color == self._available_pens[state].color():
                marker_symbol = 's'
            else:
                marker_symbol = 'o'
            
            # Create and add new overlay
            overlay = pg.ScatterPlotItem(
                x=[x], y=[y],
                brush=self._available_brushes[state],
                pen=self._available_pens[state],
                size=self.base_marker_size + 5,
                data=[sample_id],
                symbol=marker_symbol,
                hoverable=True,
                tip=self._format_tooltip
            )
            overlay.setZValue(5)  # Ensure the sample is above all other points
            overlay.sigClicked.connect(self._on_overlay_clicked)
            self._canvas.addItem(overlay)
            self._overlays[sample_id] = overlay
            self._overlay_states[sample_id] = state
        
        self._on_zoom()

    def serialize(self, session_dir: Path) -> Dict[str, Any]:
        '''
        Serializes the current selection of the application to a JSON-serializable
        format

        Parameters
        ----------
        session_dir: Path
            The path to the currently used session directory.

        Returns
        -------
        Dict[str, Any]
            The serialized version of the widget
        '''
        payload = {}
        payload["props"] = self._props

        fpath = pathlib.Path(session_dir) / f"{self._props['name']}_points.npy"
        io.dump_npy(fpath, self._points)
        payload["points"] = str(fpath)

        # Store the currently highlighted sample
        payload["current_sample"] = self._current_sample
        payload["current_state"] = self._current_state

        # Store lastly modified sample
        payload["last_mod_sample"] = self._last_mod_sample
        payload["last_mod_state"] = self._last_mod_state
        
        # Store all labeled samples and their states
        payload["labeled_samples"] = [(sample_id, state) for sample_id, state in self._overlay_states.items()]
        
        return payload

    # ----- SLOTS ----->
    @Slot()
    def deserialize(self, payload: Dict[str, Any]):
        '''
        Deserializes and restores the state of this widget based on the given
        payload.

        Parameters
        ----------
        payload: Dict[str, Any]
            The previously saved state of this widget
        '''
        self._props = payload["props"]

        brushes, pens = self._create_brushes_and_pens(
                it.cycle(self._props["colors"])
        )
        self._available_brushes = brushes
        self._available_pens = pens

        # Update the current sample & state BEFORE calling set data to ensure
        # that the highlight is not overriden.
        self._current_sample = payload["current_sample"]
        self._current_state = payload["current_state"]

        self._last_mod_sample = payload["last_mod_sample"]
        self._last_mod_state = payload["last_mod_state"]
        # Set 'ready' to False to ensure that the 'sign_ready' gets emitted,
        # and thus the state get synced with the db.
        self._ready = False
        points = payload["points"]
        self.set_data(points)
        
        # Remove any lingering yellow ring overlay from the previous session
        if self._current_sample is not None:
            old_ring = self._overlays.pop(f"ring_{self._current_sample}", None)
            if old_ring is not None:
                self._canvas.removeItem(old_ring)
        
        # Restore overlays for labeled samples
        self._overlays = {}
        self._overlay_states = {}
        for sample_id, state in payload.get("labeled_samples", []):
            if state != SampleState.UNLABELED:
                x, y = self._points[sample_id]
                if self.queued_sample_color == self._available_pens[state].color():
                    marker_symbol = 's'
                else:
                    marker_symbol = 'o'
                overlay = pg.ScatterPlotItem(
                    x=[x], y=[y],
                    brush=self._available_brushes[state],
                    pen=self._available_pens[state],
                    size=self.base_marker_size + 5,
                    data=[sample_id],
                    symbol=marker_symbol,
                    hoverable=True,
                    tip=self._format_tooltip
                )
                overlay.setZValue(5)
                overlay.sigClicked.connect(self._on_overlay_clicked)
                self._canvas.addItem(overlay)
                self._overlays[sample_id] = overlay
                self._overlay_states[sample_id] = state

    @Slot(float, float, str)
    def on_cursor_move(self, x: float, y: float, name: str):
        ''' no-op implementation of on_cursor_move just to make it work with
        the interface. '''
        return

    @Slot(float, float, str)
    def on_cursor_move_ended(self, x: float, y: float, name: str):
        ''' no-op implementation of on_cursor_move_ended to remain consistent
        with the API. '''
        return

    @Slot()
    def on_state_update(self, payload: List[Tuple[str, str, str]]):
        '''
        Updates the state of the widget with the most up-to-date information
        from the database.

        Parameters
        ----------
        payload: List[Tuple[str, str, str]]
        '''

        # This is practically the same thing as in 'on_sample_state_change'. However,
        # here the updates are batched together and sent as one update to the underlying widget.
        for sid, status, label in payload:
            
            if sid >= len(self._current_brushes):
                # The indexing assumes that sid < len(self._current_brushes). However,
                # when multiple ScatterWidgets exist, some receive state updates before
                # their data is fully initialized, causing sid to be greater than the list
                # size. This causes an IndexError, which does not affect the GUI at all
                # (but we still want to remove the error to avoid confusions).
                continue
            
            self._logger.debug(f"Updating {sid} -> {status}, {label}")

            # If the sample is not the last sample, update its color normally
            if self._current_sample is None or sid != self._current_sample:
                key = status if status != SampleState.ANNOTATED else label
                self._current_brushes[sid] = self._available_brushes[key]
                self._current_pens[sid] = self._available_pens[key]

            # If the sample is last, and it is annotated, set its brush, but
            # not the pen (as that is already set to be in the highlight color)
            elif self._current_sample is not None and sid == self._current_sample:
                if status == SampleState.ANNOTATED:
                    self._current_brushes[sid] = self._available_brushes[label]
                elif status == SampleState.UNLABELED:
                    self._current_brushes[sid] = self._available_brushes[
                            SampleState.UNLABELED
                    ]
                self._logger.debug((f"{sid} is the last sample -> No update "
                                    "to pen"))
        
        if SampleState.UNLABELED not in self._scatters:
            # In the case of multiple ScatterWidgets, it is possible that the widget
            # receives state updates before it has been fully initialized, so in these
            # cases we want to avoid a KeyError.
            return
        
        self._scatters[SampleState.UNLABELED].setBrush(self._current_brushes)
        self._scatters[SampleState.UNLABELED].setPen(self._current_pens)

    @Slot()
    def on_startup(self):
        '''Called just before the annotation is started. No-op'''
        return
    # ----- Private ---->

    @Slot()
    def _on_mouse_press(self, scatter_item: pg.ScatterPlotItem, points: List[QPointF], event: QMouseEvent):
        '''
        Handles left and right mouse clicks on scatter points.
            Left click: set current sample.
            Right click: queue sample.
        '''
        if self._points is None or len(points) == 0:
            return

        sample_id = points[0].index()
        if sample_id < 0 or sample_id >= self._points.shape[0]:
            return

        btn = event.button()

        if btn == Qt.MouseButton.LeftButton:
            # Left click: highlight and set sample
            if sample_id == self._current_sample:
                return
            self._highlight_selected_sample(sample_id)
            self.sign_user_set_sample.emit(sample_id)

        elif btn == Qt.MouseButton.RightButton:
            # Right click: queue sample
            if sample_id in self._overlays or f"ring_{sample_id}" in self._overlays:
                return
            
            self.sign_user_selected_sample.emit(sample_id)
            self._on_zoom()
            
        else:
            return



    def _highlight_selected_sample(self, sample_id: SampleID):
        '''
        Adds a yellow ring overlay to the selected sample and removes the ring
        from the previously selected sample.
        '''
        
        # Remove yellow ring from previously selected sample (and, as a safeguard, from all other possible samples, too)
        for key in list(self._overlays.keys()):
            if isinstance(key, str) and key.startswith("ring_"):
                ring = self._overlays.pop(key, None)
                if ring is not None:
                    self._canvas.removeItem(ring)

        # Do NOT remove label overlay if the sample is labeled
        if self._current_sample is not None:
            current_state = self._overlay_states.get(self._current_sample)
            if current_state == SampleState.UNLABELED or current_state is None:
                old_overlay = self._overlays.pop(self._current_sample, None)
                if old_overlay is not None:
                    self._canvas.removeItem(old_overlay)
                    self._overlay_states.pop(self._current_sample, None)

        # Add yellow ring to newly selected sample
        x, y = self._points[sample_id]
        ring = pg.ScatterPlotItem(
            x=[x], y=[y],
            brush=self._current_brushes[sample_id],  # Use sample's own color
            pen=pg.mkPen("#ffea00", width=6),
            size=self.base_marker_size + 5,
            data=[sample_id],
            hoverable=False
        )
        ring.setZValue(10)
        self._canvas.addItem(ring)
        self._overlays[f"ring_{sample_id}"] = ring

        # Update current sample tracking
        self._current_sample = sample_id
        
        # Adjust the size of the ring correctly based on zoom level
        self._on_zoom()


    @Slot()
    def _on_overlay_clicked(self, scatter_item, points):
        '''
        Handles clicks on overlay samples.

        '''
        for pt in points:
            sample_id = pt.data()
            self.sign_user_set_sample.emit(sample_id)
            break # We only handle the first clicked point
            
            
    def _on_zoom(self):
        '''
        Adjusts marker size based on zoom level.
        '''
        view_box = self._canvas.getViewBox()
        x_range, _ = view_box.viewRange()
        x_width = x_range[1] - x_range[0]

        # Compute zoom factor (inverse relation)
        zoom_factor = max(1.0, 1.0 / x_width)
        new_size = min(zoom_factor * self.base_marker_size, 20)
        ring_size = new_size + 12
        overlay_size = new_size + 5

        # Update size for all scatter items
        for scatter in self._scatters.values():
            scatter.setSize(new_size)

        # Update overlays with custom logic
        for key, overlay in self._overlays.items():
            if isinstance(key, str) and key.startswith("ring_"):
                # Yellow ring overlay for selected sample
                overlay.setSize(ring_size)
            else:
                # All other overlays
                overlay.setSize(overlay_size)


    def _maybe_set_colors(self):
        '''
        Reset the points to base colors if no previous colors are set.
        Otherwise does nothing
        '''

        # The number of pens and brushes should be the same in all situations
        n_pens = len(self._current_pens)
        if n_pens != len(self._current_brushes):
            self._logger.warning((f"Number of pens ({n_pens}) differs from "
                                  "the number of brushes "
                                  f"({len(self._current_brushes)})"))
        # If there are no existing pens & brushes set, set default pens &
        # brushes for all points
        if n_pens == 0:
            base_brush = self._available_brushes[SampleState.UNLABELED]
            self._current_brushes = [
                    base_brush for _ in range(self._points.shape[0])
            ]

            base_pen = self._available_pens[SampleState.UNLABELED]
            self._current_pens = [
                    base_pen for _ in range(self._points.shape[0])
            ]

        self._scatters[SampleState.UNLABELED].setPen(self._current_pens)
        self._scatters[SampleState.UNLABELED].setBrush(self._current_brushes)

    def _scale_point(self, points: npt.ArrayLike) -> npt.NDArray:
        '''
        Scales the given points spaced on the original value range

        Parameters
        ----------
        points: npt.ArrayLike
            The points to scale

        Returns
        -------
        npt.NDArray
            The scaled points
        '''
        points = np.asarray(points)
        return points * (self._scale, 1)

    def _construct_colors(
            self, cmap: Optional_t[str], colors: Optional_t[List[str]]
            ) -> List[str]:
        '''
        Constructs the colors that are used to represent the different classes
        in the scatter-plot. The colors are presented as hex color code strings
        (i.e. '#xxxxxxxx')

        Parameters
        ----------
        cmap: Optional[str]
            The name of the used colormap.
        colors: Optional[List[str]]
            The list of colors to use.

        Returns
        -------
        List[str]
            The colors used in the plot as hex HTML color codes
            (i.e. '#xxxxxxxx')
        '''
        n_classes = len(self._props["labels"]) + 2

        # If both are None, use default colors.
        if cmap is None and colors is None:
            self._logger.debug("Using default colors")
            if len(self._DEFAULT_COLORS) < n_classes:
                warnings.warn((f"NOTE: Only {len(self._DEFAULT_COLORS)} "
                               f"colours available for {n_classes}! Colours "
                               "will be cycled"))
            colorlist = self._DEFAULT_COLORS

        # Use cmap, even if both are specified
        elif cmap is not None:
            self._logger.debug("Using colormap")
            if colors is not None:
                warnings.warn(("Both 'colors' and 'cmap' were provided! "
                               "Disregarding 'colors',and using 'cmap'"))

            # Convert the float values to hex presentations.
            cm = mpl.colormaps[cmap](range(n_classes))
            int_colors = rgba_to_ints(cm)
            colorlist = [
                    rgba_to_str(tuple(int_colors[i])) for i in range(n_classes)
                    ]
            self._logger.debug(f"Generated colors: {colorlist}")
        # Otherwise just use the user provided colors
        elif colors is not None:
            if len(colors) < n_classes:
                warnings.warn((f"NOTE: Only {len(colors)} colors available "
                               f"for {n_classes} classes! Colours will be "
                               "cycled"))
            colorlist = colors
        else:
            raise RuntimeError(("Failed to construct colors! This is likely "
                                "a bug, rather than a user error!"))

        self._logger.debug(f"Returning {len(colorlist)} Colors")
        return colorlist

    def _create_brushes_and_pens(
            self, colors: Iterable[str]
            ) -> Tuple[Dict[str, QBrush], Dict[str, QPen]]:
        '''
        Creates the pens and brushes that are used in this plot

        Parameters
        ----------
        colors: Iterable[str]
            The colors used in this plot. Should contain at least
            len(labels) + 2 values. Values should be in html colors
            (i.e. #xxxxxxxx)
        Returns
        -------
        Tuple[Dict[str, QBrush], Dict[str, QPen]]
            The created brushes and pens. Each label gets assigned their
            own pen and brush.
        '''
        brushes = {self._HOVER: pg.mkBrush("#ffea00")}
        pens = {}

        names = [
                SampleState.UNLABELED, SampleState.SELECTED,
                *self._props["labels"]
        ]
        for key, color in zip(names, colors):
            self._logger.debug(f"Setting color {color} for {key}")
            pens[key] = pg.mkPen({"color": color, "width": 2.5})
            brushes[key] = pg.mkBrush(color)
        return brushes, pens

    def _format_tooltip(
            self, x: float, y: float, data: Optional_t[float]
            ) -> str:
        '''
        Function used to format the message that is displayed in the tooltip.

        Parameters
        ----------
        x: float
            The x coordinate of the point.
        y: float
            The y coordinate of the point.
        data: Optional[float]
            Possible extra information about the point

        Returns
        -------
        str
            The formatted message for the tooltip
        '''
        scatter_item = self._scatters[SampleState.UNLABELED]
        pts = scatter_item.pointsAt(pg.Point(x, y))
        # Display always only one point
        if len(pts) == 0:
            return ""

        sample_id = pts[0].index()
        if sample_id < 0 or sample_id > self._points.shape[0]:
            return "error while finding point"
        return f"id: {sample_id}, ({x:.2f}, {y:.2f})"
