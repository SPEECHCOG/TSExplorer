from .. import defaults
from ..utils import convert
from ..utils import colorbase
from ..utils import logger
from ..utils.misc import fontsize_to_int
from ..utils.qt_utils import SignalBlocker
from ..metadata import WidgetType

import itertools as it
from typing import Dict, Tuple, Mapping, Any, List
from typing import Optional as Optional_t  # To avoid name conflicts

import numpy as np
import numpy.typing as npt
import resampy

# For validating kwargs
from schema import Schema, Optional, And, Regex, Use, Or

from PySide6.QtWidgets import QWidget, QVBoxLayout, QLabel
from PySide6.QtCore import QObject, Signal, Slot
from PySide6.QtGui import QPen, QFont
import pyqtgraph as pg

_MAX_SAMPLING_RATE: int = 1500


class WaveFormWidget(QWidget):
    '''
    Defines a widget displaying 1 to n waveform plots. Plots are stacked
    vertically, with no consideration of the total height of the layout.

    Signals
    -------
    sign_cursor_moved: float, float, str
        Emitted when the position of the infiniteLine is updated.
        Contains the updated x and y position (x in seconds), and the name of
        the widget which emitted the signal.
    sign_cursor_move_ended: float, float, str
        Emitted when the user stops moving the infinite line.
        Contains the updated x and y positions (x in seconds), and the name of
        the widget which emitted the signal.
    sign_ready:
        Emitted when the component is ready to display data.
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
    sign_data = Signal(int, object)

    _KWARGS_SCHEMA: Schema = Schema({
        "name": Schema(
            str, error=("Missing 'name'! This is likely an internal bug, "
                        "and not an user error")
        ),
        Optional("source_dirs", default=None): [str],
        Optional("source_path", default=None): str,
        Optional("sr", default=None): And(Use(float), lambda n: n > 0),
        Optional("group_waveform_channels_into_groups_of", default=1): And(int, lambda n: n > 0),
        Optional("show_xaxis_label", default=True): bool,
        Optional("show_legend", default=True): bool,
        Optional("show_xaxis_ticks", default=True): bool,
        Optional("plot_titles", default=None): Or(None, {int: str}),
        Optional("plot_title_fontsize", default="12pt"): str,
        Optional("plot_spacing", default=0): And(int, lambda n: n >= 0),
        Optional("waveform_thickness", default=2): And(int, lambda n: n > 0),
        Optional("labels", default=None): Schema({str: str}),
        Optional("map_sources", default=None): Schema({str: int}),
        Optional("max_sampling_rate", default=_MAX_SAMPLING_RATE): And(int, lambda n: n >= 0),
        Optional("colors", default=colorbase.get_colors("waveform_default")): Schema([Regex("^#([A-Fa-f0-9]{6}|[A-Fa-f0-9]{3})$")]),
        Optional("set_ylim_automatically", default=True): bool,
        Optional("ylim_min_value", default=-1.0): float,
        Optional("ylim_max_value", default=1.0): float,
        Optional("replace_yticklabels_with_plot_titles", default=False): bool,
        Optional("lock_waveform_plots", default=False): bool,
        Optional("hide_autorange_button", default=False): bool,
        Optional("display_only_label_box", default=False): bool,
        Optional("label_box_labels", default=None): [str],
        Optional("label_box_fontsize", default="12pt"): str
    })

    def __init__(
            self, parent: Optional_t[QObject] = None,
            **kwargs: Mapping[str, Any]
            ):
        '''
        Creates a Waveform widget

        Parameters
        ----------
        n_channels: int
            The amount of plots that the widget will contain
        parent: Optional[QObject]
            The parent object for this widget. Default None.
        kwargs: Mapping[str, Any]
            Any possible keyword arguments. Currently only 'source_dirs' is
            accepted.
        '''
        super().__init__(parent)
        self._logger = logger.get_logger("Waveform")
        self._canvas = pg.GraphicsLayoutWidget()

        layout = QVBoxLayout()
        layout.addWidget(self._canvas)

        kwargs = self._KWARGS_SCHEMA.validate(kwargs)
        
        # Check if only the label box should be displayed
        if kwargs.get("display_only_label_box", False):
            layout = QVBoxLayout()
            
            # Convert fontsize string (e.g., "12pt") to int
            fontsize = fontsize_to_int(kwargs.get("label_box_fontsize", "12pt"))
            font = QFont("Times", fontsize)
            
            # Create a container widget for the label box
            container = QWidget()
            container.setStyleSheet("background-color: white;")
            container_layout = QVBoxLayout(container)
            
            for lbl in kwargs["label_box_labels"]:
                label_widget = QLabel(lbl)
                label_widget.setFont(font)
                label_widget.setStyleSheet("color: black;") # We force the text color to be black since we have a white background
                container_layout.addWidget(label_widget)
            
            layout.addWidget(container)
            self.setLayout(layout)
        
        # Apply plot spacing if specified
        spacing = kwargs.get("plot_spacing", 0)
        self._canvas.ci.setSpacing(spacing)

        # Ensure that only source dir or source path is specified at same time
        spath = kwargs["source_path"]
        sdirs = kwargs["source_dirs"]
        if spath is None and sdirs is None:
            raise RuntimeError((f"{kwargs['name']!r}: Either 'source_path' or "
                                "'source_dirs' should be specified"))
        elif spath is not None and sdirs is not None:
            raise RuntimeError((f"{kwargs['name']!r}: Only one of "
                                "'source_path' and 'source_dirs' should be "
                                "specified"))

        # When using numpy arrays, one must specify sampling rate
        sr = kwargs["sr"]
        if sr is None and spath is not None:
            if not kwargs.get("display_only_label_box", False):
                raise RuntimeError((f"{kwargs['name']!r}: 'sr' must be specified "
                                    "if 'source_path' is used!"))
        # This key will be dismissed if the user uses waveform files

        self._props: Dict[str, Any] = kwargs
        colors = kwargs.get("colors")
        thickness = kwargs.get("waveform_thickness", 2)
        self._pens: List[QPen] = [pg.mkPen(c, width=thickness) for c in colors]

        self._plots = None  # n_channels*[None]
        self._vlines = None  # n_channels*[None]
        self.setLayout(layout)

        # Set to True when the widget can display data
        self._ready: bool = False

        # Some "constant" properties of the widget
        self._wtype: WidgetType = WidgetType.WAVEFORM
        self._requires_update: bool = True

        # Set the font-styles
        self._font_opts: Dict[str, str] = {
                "label": {
                    "fontsize": defaults.RCPARAMS["label-font"]["size"],
                    "color": defaults.RCPARAMS["label-font"]["color"]
                },
                "ticks": {
                    "fontsize": defaults.RCPARAMS["tick-font"]["size"]
                }
        }

    @property
    def wtype(self) -> WidgetType:
        ''' Returns the type of this widget '''
        return self._wtype

    @property
    def requires_update(self) -> bool:
        '''
        Returns True if the widget needs to be updated during every sample
        '''
        return self._requires_update

    def set_data(self, data: Dict[str, Tuple[int, npt.NDArray]]):
        '''
        Sets and displays the given data on the widget. NOTE: signals having
        sampling rate > 1500 will be resampled.

        Parameters
        ----------
        Dict[str, Tuple[int, npt.NDArray]]
            A mapping from label to the data. Each item should contain the
            sampling rate of the data, and the data as a numpy array.

        '''
        
        if self._props.get("display_only_label_box", False):
            if not self._ready:
                self._ready = True
                self.sign_ready.emit()
            return # We don't set any data

        # The data can be two different things:
        # 1) a multiple 1D arrays that need to be plotted
        # 2) Single 2D array that needs to be plotted
        # -> Effectively the same thing
        plot_data = self._split_data(data)

        # If the source map is not created, create it
        if not self._ready:
            self._create_and_validate_source_map(plot_data)
            self._maybe_validate_labels(len(plot_data))
        # Create mapping from plot index -> data
        pane_mapping = self._create_plot_mapping(plot_data)

        self._maybe_init_plots(len(pane_mapping))

        for plot_idx, plot_data in pane_mapping.items():
            if self._plots[plot_idx] is None:
                self._create_plots(plot_idx, plot_data)
            else:
                self._update_plots(plot_idx, plot_data)

        # Ensure that the ready signal is only sent once.
        if not self._ready:
            self._ready = True
            self.sign_ready.emit()

    def shutdown(self):
        '''
        Called when shutting down the application. Currently does nothing.
        '''
        return

    @Slot()
    def on_cursor_move(self, x: float, y: float, *_):
        '''
        Signal handler for the line moving. Syncs up all the position lines in
        this widget. If the moved line was from this widget, emits
        'cursorMoved' signal containing reference to the moved line.

        Parameters
        ----------
        x: float
            The new x position.
        y: float
            The new y position.
        '''
        
        if self._props.get("display_only_label_box", False):
            return # We don't set any data
        
        self._update_lines(x, y)

    @Slot()
    def on_cursor_move_ended(self, x: float, y: float, name: str):
        '''
        Signal handler for the case when the movement of the line has
        stopped. Not operational.

        Parameters
        ----------
        x: float
            The new x position of the 'cursor'.
        y: float
            The new y position of the 'cursor'
        name: str
            The name of the widget that emitted the signal.
        '''
        return

    @Slot()
    def on_startup(self):
        ''' Called just before the annotation is going to start. Not operational.'''
        return

    def _update_lines(
            self, x: float, y: float, lines_to_skip: List[pg.InfiniteLine] = []
            ):
        '''
        Updates the position of each line in the plot, if the line is not
        explicitly mentioned.

        Parameters
        ----------
        x: float
            The new x position.
        y: float
            The new y position.
        lines_to_skip: List[pg.InfiniteLine], Optional
            The lines that won't be updated. Default []
        '''
        for vline in self._vlines:
            if vline in lines_to_skip:
                continue
            with SignalBlocker(vline):
                vline.setValue((x, y))

    @Slot()
    def _update_and_emit(self, x: float, y: float = 0.0):
        '''
        Updates the line positions and emits the 'sign_cursor_moved' signal.

        Parameters
        ----------
        x: float
            The updated x position, in seconds.
        y: float
            The updated y position, in seconds.
        '''
        if self._props.get("display_only_label_box", False):
            return # We don't set any data
        
        self._update_lines(x, y)
        self.sign_cursor_moved.emit(x, y, self._props["name"])

    @Slot()
    def _on_cursor_move_internal(self, line: pg.InfiniteLine):
        '''
        Internal slot for updating the cursor/vline position.

        Parameters
        ----------
        line: pg.InfiniteLine
            The line that was moved.
        '''
        if self._props.get("display_only_label_box", False):
            return # We don't set any data
        
        # Extract the new position
        x, y = tuple(line.pos())
        # Update the position of possible other lines in the widget.
        self._update_lines(x, y, [line])
        # Update other widgets with new info.
        self.sign_cursor_moved.emit(x, y, self._props["name"])

    @Slot()
    def _on_cursor_move_ended_internal(self, line: pg.InfiniteLine):
        '''
        Internal slot for case when the cursor movement ended.

        Parameters
        ----------
        line: pg.InfiniteLine
            The line that was moved
        '''
        # The lines should be already updated, so just convert the signal
        # to contain API-compliant parameters.
        x, y = tuple(line.pos())
        self.sign_cursor_move_ended.emit(x, y, self._props["name"])

    def _create_plot_mapping(
            self, data: List[Tuple[str, int, npt.NDArray]]
            ) -> Dict[int, List[Tuple[str, int, npt.NDArray]]]:
        '''
        Create mapping from the possible waveform panes and the source for
        the data.

        Parameters
        ----------
        data: List[Tuple[str, int, npt.NDArray]]
            The data arranged into channel-id, int and array tuples

        Returns
        -------
        Dict[int, List[Tuple[str, int, npt.NDArray]]]
            The mapping between panes and the data-sources
        '''
        src_map = self._props["map_sources"]

        out = {}
        for i, (channel_id, sr, arr) in enumerate(data):
            plot_idx = src_map[channel_id]
            if plot_idx not in out:
                out[plot_idx] = []
            out[plot_idx].append((channel_id, sr, arr))
        return out

    def _maybe_init_plots(self, n_channels: int):
        '''
        Initializes the plot and vline list to Nones if needed.

        Parameters
        ----------
        n_channels: int
            The amount of channels the plot will contain
        '''
        if self._plots is None:
            self._plots = [None for _ in range(n_channels)]

        if self._vlines is None:
            self._vlines = [None for _ in range(n_channels)]

    def _create_and_validate_source_map(
            self, plot_data: List[Tuple[str, int, npt.NDArray]]
            ):
        '''
        Creates a mapping from sources and channels to the actual plots.

        Parameters
        ----------
        plot_data: List[Tuple[str, int, npt.NDArray]]
             List of label, sampling-rate, data tuples.
        '''
        src_map = self._props.get("map_sources")
        group_size = self._props.get("group_waveform_channels_into_groups_of", 1)

        # No mapping specified -> Plot all channels in separate waveforms
        if src_map is None:
            out = {}
            for i, (channel_id, *_) in enumerate(plot_data):
                group_idx = i // group_size
                out[channel_id] = group_idx
            self._props["map_sources"] = out
        
        # Otherwise, check that the user has actually created a valid mapping
        else:
            for i, (channel_id, *_) in enumerate(plot_data):
                if channel_id not in src_map:
                    raise RuntimeError((f"{self._props['name']}: {channel_id} "
                                        "is not mapped to any output"))
            # Also ensure that the mapping does not contain any extra keys
            channel_ids = set(vals[0] for vals in plot_data)
            extra_keys = set(src_map.keys()).difference(channel_ids)
            if len(extra_keys) != 0:
                raise RuntimeError((f"{self._props['name']}: 'map_sources' "
                                    "contains unknown sources: "
                                    f"{', '.join(extra_keys)}"))

    def _split_data(
            self, data: Dict[str, Any]
            ) -> List[Tuple[str, int, npt.NDArray]]:
        '''
        Split the given data into (id, sampling-rate, 1D array) tuples
        that can then be plotted as waveforms

        Parameters
        ----------
        data: Dict[str, Any]
            The data to plot. Each value can be either:
            - Tuple[int, np.ndarray] (sampling rate + data)
            - np.ndarray (raw data, sampling rate taken from config)

        Returns
        -------
        List[Tuple[str, int, npt.NDArray]]
            List of id, sampling-rate, 1D array tuples that can be easily
            plotted in the waveform.
        '''
        plot_data = []
        sr_config = self._props.get("sr")
        for key, value in data.items():
            # Case 1: value is a tuple (sr, array)
            if isinstance(value, tuple) and len(value) == 2:
                sr, arr = value
            # Case 2: value is a raw array, use config sampling rate
            elif isinstance(value, np.ndarray):
                if sr_config is None:
                    raise RuntimeError(f"{self._props['name']!r}: Sampling rate must be specified in config for raw NumPy arrays.")
                sr, arr = sr_config, value
            else:
                raise TypeError(f"{self._props['name']!r}: Unsupported data format for key {key!r}")

            # Handle 3D array: [n_waveforms, n_channels, n_samples]
            if arr.ndim == 3:
                for i in range(arr.shape[0]):
                    for j in range(arr.shape[1]):
                        label = f"{key}_waveform{i+1}_channel{j+1}"
                        plot_data.append((label, sr, arr[i, j, :]))
            # Handle 2D array: [n_channels, n_samples]
            elif arr.ndim == 2:
                for j in range(arr.shape[0]):
                    label = f"{key}_channel{j+1}"
                    plot_data.append((label, sr, arr[j, :]))
            # Handle 1D array
            elif arr.ndim == 1:
                plot_data.append((key, sr, arr))
            else:
                raise ValueError(f"{self._props['name']!r}: Unsupported array shape {arr.shape} for key {key!r}")

        return plot_data

    def _create_plots(
            self, plot_idx: int,
            plot_data: List[Tuple[str, int, npt.NDArray]]
            ):
        '''
        Creates the plot for the given plot index, and plots the initial
        data to the created plot.

        Parameters
        ----------
        plot_idx: int
           The index at which the plot will be placed.
        plot_data: List[Tuple[str, int, npt.NDArray]]
           The data to plot. Should be tuples of "label", sampling rate
           and the array
        '''
        
        if self._props.get("display_only_label_box", False):
            return # We don't set any data
        
        fig = self._canvas.addPlot(row=plot_idx, col=1)
        fig.showGrid(x=True, y=True)

        # Lock interaction if requested
        if self._props.get("lock_waveform_plots", False):
            fig.setMouseEnabled(x=False, y=False)  # Disable panning and zooming
        
        # Hide PyQtGraph's autorange button if requested
        if self._props.get("hide_autorange_button", False):
            fig.hideButtons()

        fig.setMenuEnabled(False)
        
        show_xaxis_label = self._props.get("show_xaxis_label", True)
        if show_xaxis_label:
            fig.setLabel("bottom", text="Time", units='s', **self._font_opts["label"])
        self._plots[plot_idx] = fig

        # Create legend as the plot might contain multiple data-series
        # Position the legend at upper-left corner
        show_legend = self._props.get("show_legend", True)

        if show_legend:
            legend = fig.addLegend(
                offset=(2, 2),
                labelTextSize=self._font_opts["label"]["fontsize"]
            )
            legend.setBrush(pg.mkBrush(255, 255, 255, 200))  # White with alpha=200 (alpha is from 0 to 255 and it stands for opacity)

        # If the tick-fontsize is specified, use it.
        show_xaxis_ticks = self._props.get("show_xaxis_ticks", True)

        if show_xaxis_ticks:
            if self._font_opts["ticks"]["fontsize"] is not None:
                fontsize = fontsize_to_int(self._font_opts["ticks"]["fontsize"])
                font = QFont("Times", fontsize)
                fig.getAxis("bottom").setTickFont(font)
                fig.getAxis("left").setTickFont(font)
        else:
            fig.getAxis("bottom").setStyle(showValues=False)
        
        set_ylim_automatically = self._props.get("set_ylim_automatically", True)
        if not set_ylim_automatically:
            ylim_min_value = self._props.get("ylim_min_value")
            ylim_max_value = self._props.get("ylim_max_value")
            fig.setYRange(ylim_min_value, ylim_max_value)
            
        
        # If the plot contains multiple data-series, use single "multiplot"
        # call. Otherwise, just plot normally.
        label_mapping = self._props["labels"]
        n_data = len(plot_data)
        ubound = None
        
        plot_titles = self._props.get("plot_titles")
        replace_labels = self._props.get("replace_yticklabels_with_plot_titles", False)
        if plot_titles is not None:
            title = plot_titles.get(plot_idx)
            if title is not None:
                fontsize = self._props.get("plot_title_fontsize", "12pt")
                if replace_labels:
                    # Hide y-axis tick labels and set y-axis label instead of the title
                    fig.getAxis("left").setStyle(showValues=False)
                    fig.setLabel("left", text=title, **self._font_opts["label"])
                else:
                    # Set plot title normally
                    fig.setTitle(title, size=fontsize, color=self._font_opts["label"]["color"])
        
        if n_data > 1:
            channel_ids, sampling_rates, ys = zip(*plot_data)

            if label_mapping is None:
                labels = channel_ids
            else:
                labels = [label_mapping[ch_id] for ch_id in channel_ids]
            # Downsample the data if they contain sampling rate higher than the
            # specified max sampling frequency
            ys, sampling_rates = zip(*map(
                self._maybe_downsample, ys, sampling_rates
            ))

            # Convert the samples to seconds, and create the coloring pens
            # for each item
            xs = [convert.samples_to_seconds(np.arange(y.shape[0]), sr)
                  for y, sr in zip(ys, sampling_rates)]
            pens = [p for (_, p) in zip(range(n_data), it.cycle(self._pens))]
            fig.multiDataPlot(x=xs, y=ys, pen=pens, name=labels)

            # Find the maximum length signal
            ubound = max(map(lambda x: x.max(), xs))
        else:
            ch_id, sr, ys = plot_data[0]
            label = ch_id if label_mapping is None else label_mapping[ch_id]

            ys, sr = self._maybe_downsample(ys, sr)
            pen = self._pens[0]
            xs = convert.samples_to_seconds(np.arange(ys.shape[0]), sr)
            fig.plot(xs, ys, pen=pen, name=label)

            ubound = xs.max()

        # Finally, add the vertical infinite line on top of everything to
        # that it is drawn as the last element.
        vline = fig.addLine(
            x=0, movable=True, pen=pg.mkPen("#F51320"),
            bounds=((0, ubound or 1))
        )
        vline.sigPositionChanged.connect(self._on_cursor_move_internal)
        vline.sigPositionChangeFinished.connect(
                self._on_cursor_move_ended_internal
        )
        self._vlines[plot_idx] = vline

    def _update_plots(
            self, plot_idx: int,
            plot_data: Dict[int, List[Tuple[str, int, npt.NDArray]]]
            ):
        '''
        Update the already existing plots with new data.

        Parameters
        ----------
        plot_idx: int
           The index of the plot to update
        plot_data: List[Tuple[str, int, npt.NDArray]]
           The new data to update to the plot. Should contain the
           id (e.g. channel number or directory name), sampling rate
           and a 1D array of data.
        '''
        
        if self._props.get("display_only_label_box", False):
            return # We don't set any data
        
        fig = self._plots[plot_idx]
        assert fig is not None, f"Missing plot item for index: {plot_idx}!"
        plot_items = fig.listDataItems()

        # Find the longest signal among the plotted signals
        ubound = None
        for plot, (label, sr, ys) in zip(plot_items, plot_data):
            ys,  sr = self._maybe_downsample(ys, sr)
            xs = convert.samples_to_seconds(
                np.arange(ys.shape[0]), sr
            )
            if ubound is None or xs.max() > ubound:
                ubound = xs.max()
            plot.setData(xs, ys)

        # Set new x-range
        fig.setXRange(0, ubound)
        vline = self._vlines[plot_idx]
        with SignalBlocker(vline):
            vline.setBounds((0, xs.max()))
            vline.setValue(0)

    def _maybe_downsample(
            self, y: npt.NDArray, sr: int
            ) -> Tuple[npt.NDArray, int]:
        '''
        Downsamples the given array if the current sampling rate is higher
        than the maximum allowed sampling rate.

        Parameters
        ----------
        y: npt.NDArray
            The data to downsample.
        sr: int
            The current sampling rate.

        Returns
        -------
        Tuple[npt.NDArray, int]
            If the downsampling was applied, returns the downsampled data and
            the new sampling rate, otherwise the original data and sampling
            rate is returned.
        '''
        max_sr = self._props["max_sampling_rate"]
        if sr > max_sr:
            y = resampy.resample(y, sr, max_sr)
            sr = max_sr
        return y, sr

    def _maybe_validate_labels(self, n_channels: int):
        '''
        Validates the user specified labels if they are given.

        Parameters
        ----------
        n_channels: int
            The number of channels the data contains
        '''
        labels = self._props["labels"]
        if labels is None:
            return

        sdirs = self._props["source_dirs"]
        spath = self._props["source_path"]

        if sdirs is not None:
            channel_ids = sdirs
        elif spath is not None:
            # If single numpy file is used, the channel names will always be
            # "channel 1", "channel 2" etc
            channel_ids = [f"channel_{i+1}" for i in range(n_channels)]

        for ch_id in channel_ids:
            if ch_id not in labels:
                raise RuntimeError((f"{self._props['name']!r}: 'labels' "
                                   f"missing name for {ch_id!r}"))
            # Check for extra keys
            extra_keys = set(channel_ids).difference(labels)
            if len(extra_keys) != 0:
                raise RuntimeError((f"{self._props['name']!r}: 'labels' "
                                    f"contains extra keys: {extra_keys}"))