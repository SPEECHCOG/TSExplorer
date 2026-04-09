'''This file defines the central widget of the application. This widget acts
mostly as a wrapper that holds the layout of the widget'''

from .scatterwidget import ScatterWidget
from .spectrogramwidget import SpectrogramWidget
from .waveformwidget import WaveFormWidget
from .audiowidget import AudioWidget
from .videowidget import VideoWidget
from ..metadata import SampleID, Path, WidgetType, SampleState
from ..utils import logger
from ..utils.asset_manager import AssetManager
from ..utils.qt_utils import SignalBlocker

import os
import pathlib
import math
from collections import defaultdict

from typing import Mapping, Optional, Dict, Any, Tuple, Callable, Union
import numpy.typing as npt

from PySide6.QtWidgets import (
        QWidget, QGridLayout, QHBoxLayout, QVBoxLayout, QLabel, QPushButton,
        QComboBox
)
from PySide6.QtCore import QObject, Signal, Slot, Qt
from PySide6.QtGui import QKeyEvent

LoaderFn = Callable[[Union[str, os.PathLike]], Any]

_FILE_ID_TEMPLATE: str = "file-id: {0}"
_INDEX_TEMPLATE: str = "number of labeled samples: {0} (total: {1})"


# Currently supported widgets
_WIDGETS: Dict[str, QWidget] = {
        WidgetType.SCATTER:    ScatterWidget,
        WidgetType.SPECTROGRAM: SpectrogramWidget,
        WidgetType.WAVEFORM:   WaveFormWidget,
        WidgetType.AUDIO:      AudioWidget,
        WidgetType.VIDEO:      VideoWidget
}


class AnnotationWidget(QWidget):
    '''
    Defines the central widget of the main view. Acts mostly as a holder for
    the widgets used in the central view.

    Signals
    --------
    sign_request_sample: int
        Emitted when a sample needs to be loaded to the widget
    sign_sample_state_changed: int, str
        Emitted when the state of a sample is changed from user action
        (i.e. using the spin-box).
    '''
    sign_request_sample = Signal(int, name="sign_request_sample")

    # Emitted when the label of the sample is changed from the annotation widget
    sign_sample_state_changed = Signal(
            int, str, name="sign_sample_state_changed"
    )

    # Emitted when user selects a sample in the scatter widget
    sign_user_selected_sample = Signal(int, name="sign_user_selected_sample")

    # Emitted when dimensionality reduction is required
    sign_request_dim_reduction = Signal(
            str, str, str, object, name="sign_request_dim_reduction"
    )

    # Emitted when all widgets are ready and the annotation will start
    sign_on_startup = Signal(name="sign_on_startup")
    # Emitted when erroneous situation happens
    sign_error = Signal(str, name="sign_error")

    # Not used currently
    sign_progress_update = Signal(int, name="sign_progress_update")
    sign_widget_ready = Signal(name="sign_widget_ready")

    def __init__(
            self, *,
            dp_path: str,
            table_name: str,
            n_samples: Optional[int] = None,
            parent: Optional[QObject] = None,
            ):
        '''
        The constructor of the parent widget. Creates the layout and all the
        child widgets

        Parameters
        ----------
        n_samples: Optional[int]
            The total amount of samples in the used dataset. Default None
        parent: Optional[QObject]
            The parent of this widget. Should be a instance of a Window in most
            cases. Default None.
        '''
        super().__init__(parent)

        self._ptr: int = 0  # Keeps count on what sample is being displayed
        self._len: int = 0  # Keeps count on the number of indices used
        self._current_sample: SampleID = None  # ID of the current sample
        self._n_samples = n_samples

        # User configured display widgets
        self._user_widgets: Dict[str, QWidget] = {}
        # Widgets that are always present
        self._static_widgets: Dict[str, QWidget] = {}

        # This will be set to False if the user cancels the dimensionality
        # reduction
        self._use_dim_reduction: bool = True

        # The amount of widgets in state "ready"
        self._n_ready_widgets: int = 0

        # logger
        self._logger = logger.get_logger("annotation_window")
        self._create_layout()
        self._connect_signals()

        settings = self.parent().settings
        self._asset_mngr = AssetManager(dp_path, table_name, settings.widgets)
        self.installEventFilter(self)

    def get_scatter_widgets(self) -> Dict[str, QWidget]:
        '''
        Returns all scatter widgets in the annotation widget. NOTE: No
        long-form references should be kept to the items, as they can be
        invalidated at any time.

        Parameters
        ----------
        '''
        return {
                key: widget for key, widget in self._user_widgets.items()
                if widget.wtype == "scatter"
        }

    def serialize(self, session_dir: Path) -> Dict[str, Any]:
        '''
        Serializes the annotation widget to a YAML supported format.

        Parameters
        ----------
        session_dir: Path
            The path to the currently used session directory.

        Returns
        -------
        Dict[str, str]
            The stored payload.
        '''
        payload = {}
        payload["ptr"] = self._ptr
        payload["len"] = self._len
        payload["sample_id"] = self._current_sample

        # Store the currently used dimensionality reduction if available
        if "dim_reduction_box" in self._static_widgets:
            dim_reduction_box = self._static_widgets["dim_reduction_box"]
            payload["dim_reduction"] = dim_reduction_box.currentText()
        else:
            payload["dim_reduction"] = None

        payload["asset_mngr"] = self._asset_mngr.serialize()

        # Only scatter widgets are "stateful", so those should be serialized
        for name, widget in self._user_widgets.items():
            if widget.wtype == WidgetType.SCATTER:
                payload[name] = widget.serialize(session_dir)

        return payload

    def deserialize(self, payload: Mapping[str, Any]):
        '''
        Restores the previous state of the application from the given data.

        Parameters
        ----------
        payload: Mapping[str, Any]
            The previously saved state of the application
        '''
        # Clear old buffer, and the deserialize the state
        settings = self.parent().settings
        self._asset_mngr.deserialize(payload["asset_mngr"], settings.widgets)
        self._n_ready_widgets = 0

        # Now the ultimate hack! We relayout the old widgets to a temporary
        # layout that will be destroyed at the end of this function, and thus,
        # we destroy the items related to that layout. Then we just create a
        # new layout.
        self._static_widgets.clear()
        self._user_widgets.clear()
        QWidget().setLayout(self.layout())

        self._create_layout()
        self._logger.debug(f"New widgets: {self._user_widgets.keys()}")
        
        # Because the old widgets were destroyed, we must connect the signals again
        self._connect_signals()

        # Now set the correct sample
        self._ptr = payload["ptr"]
        self._len = payload["len"]
        self._current_sample = payload["sample_id"]

        # Restore dimensionality reduction box if available
        if payload.get("dim_reduction") and "dim_reduction_box" in self._static_widgets:
            dim_reduction_box = self._static_widgets["dim_reduction_box"]
            with SignalBlocker(dim_reduction_box):
                idx = dim_reduction_box.findText(payload["dim_reduction"])
                if idx != -1:
                    dim_reduction_box.setCurrentIndex(idx)
                else:
                    self._logger.warning(f"Dimensionality reduction '{payload['dim_reduction']}' not found.")

        # Restore scatter widget states
        for name, widget in self._user_widgets.items():
            if widget.wtype == WidgetType.SCATTER:
                widget.deserialize(payload[name])

        self.sign_request_sample.emit(self._ptr)

    def reload(self):
        '''
        Reloads the widget's state in case when the configuration file was
        changed. Wipes all previous progress
        '''
        # Invalidate the buffer, and wipe the amount of ready widgets.
        self._asset_mngr.clear_buffer()
        self._n_ready_widgets = 0

        # Get the currently set label for the current sample
        current_label = self._static_widgets["label_box"].currentText()
        # Remove of old layout
        QWidget().setLayout(self.layout())

        self._user_widgets.clear()
        self._static_widgets.clear()

        # Build the new layout and connect the signals
        self._create_layout()
        self._connect_signals()

        # Redraw the state from before the change
        self._redraw(self._current_sample)

        label_box = self._static_widgets["label_box"]

        # It is possible that the user has changed the labels. In this case,
        # we raise error, as this would invalidate the previous annotations
        idx = label_box.findText(current_label)
        if idx == -1:
            self.sign_error.emit("Cannot find previously set label "
                                 f"{current_label!r}. Changing labels will "
                                 "invalidate the previously set labels and "
                                 "thus is not supported"
                                 )
            return
        self._force_label_save(idx)

        self.maybe_require_dim_reduction()

    def shutdown(self):
        '''
        Clean up any possible resources that need to be handled manually before
        application shuts downs
        '''
        for name, widget in self._user_widgets.items():
            self._logger.debug(f"Cleaning up {name!r}")
            widget.shutdown()
        self._asset_mngr.shutdown()

    def maybe_require_dim_reduction(self):
        '''Requires dimensionality reductions for if needed'''
        # Request dimensionality reduction for all scatter widgets
        for name, widget in self._user_widgets.items():
            if widget.wtype == WidgetType.SCATTER:
                algo_name, config = self._get_current_dim_reduction_config()
                self.sign_request_dim_reduction.emit(
                        name, widget.file, algo_name, config
                )

    def _create_layout(self):
        '''
        Creates the layout for the application.

        Parameters
        ----------
        spec: Dict[str, Any]
            The specification for the layout. Should contain the name of the
            widget and its location and possibly some additional data for the
            widget.
        '''
        # Get the current settings
        user_settings = self.parent().settings

        # ------ THE TOP ROW -------
        self._logger.debug("Creating top row")

        top_layout = QHBoxLayout()
        index_label = QLabel(_INDEX_TEMPLATE.format("NA", "NA"))
        self._static_widgets["index_label"] = index_label
        top_layout.addWidget(index_label)

        sample_id_label = QLabel(_FILE_ID_TEMPLATE.format("NA"))
        self._static_widgets["sample_id_label"] = sample_id_label
        top_layout.addWidget(sample_id_label)

        label_box = QComboBox()

        for opt in user_settings.labels:
            label_box.addItem(opt)
        label_box.currentTextChanged.connect(self._save_label)
        self._static_widgets["label_box"] = label_box
        top_layout.addWidget(label_box)

        # Check if there are any scatter widgets that actually use dimensionality reductions
        has_scatters = any(wconfig.get("wtype") == WidgetType.SCATTER.value for wconfig in user_settings.widgets)

        if has_scatters:
            dim_reduction_box = QComboBox()
            default = None
            for i, (algo_name, opts) in enumerate(
                    user_settings.dim_reductions.items()
                    ):

                # Use the first algorithm as default if None are specified
                if default is None or opts.get("default", False):
                    self._logger.debug(f"Setting {algo_name!r} as default")
                    default = i

                dim_reduction_box.addItem(algo_name)

            dim_reduction_box.setCurrentIndex(default)
            dim_reduction_box.currentTextChanged.connect(self._ask_dim_reduction)
            self._static_widgets["dim_reduction_box"] = dim_reduction_box
            top_layout.addWidget(dim_reduction_box)

        # -------- THE BOTTOM ROW ----------
        self._logger.debug("Creating bottom row")
        bottom_layout = QHBoxLayout()

        prev_btn = QPushButton("previous sample")
        prev_btn.setEnabled(False)
        prev_btn.clicked.connect(self._prev_sample)
        self._static_widgets["prev_btn"] = prev_btn
        bottom_layout.addWidget(prev_btn)

        next_btn = QPushButton("next sample (Enter)")
        next_btn.clicked.connect(self._request_next_sample)
        next_btn.setEnabled(False)
        self._static_widgets["next_btn"] = next_btn
        bottom_layout.addWidget(next_btn)

        # --------- THE MIDDLE SECTION ---------
        # This section is configured by the user
        middle_layout = QGridLayout()
        self._logger.debug("Creating middle section")
        
        # This is needed for Qt to respect the grid layout proposed by the user (in the configuration settings)
        column_stretch_map = defaultdict(int)
        row_stretch_map = defaultdict(int)
        
        # Iterate over all the widgets in the settings
        for widget_config in user_settings.widgets:
            wtype = widget_config.get("wtype")
            self._logger.debug(f"Type of widget: {wtype}, {type(wtype)}")
            assert wtype in _WIDGETS, (f"Unknown widget type {wtype}!."
                                       "Supported options are ",
                                       f"{', '.join(_WIDGETS.keys())}")

            name = widget_config.get("name")
            pos = widget_config.get("position")
            klass = _WIDGETS[wtype]
            widget = klass(**widget_config.get("kwargs"))
            self._user_widgets[name] = widget
            
            middle_layout.addWidget(widget, pos["row"], pos["col"], pos["rowspan"], pos["colspan"])
            
            # Accumulate stretch values
            for col in range(pos["col"], pos["col"] + pos["colspan"]):
                column_stretch_map[col] += pos["colspan"]
            for row in range(pos["row"], pos["row"] + pos["rowspan"]):
                row_stretch_map[row] += pos["rowspan"]
        
        # Apply column stretch factors
        max_col = max(column_stretch_map.keys(), default=0)
        for col in range(max_col + 1):
            stretch = column_stretch_map.get(col, 1)
            middle_layout.setColumnStretch(col, stretch)
        
        # Apply row stretch factors
        max_row = max(row_stretch_map.keys(), default=0)
        for row in range(max_row + 1):
            stretch = row_stretch_map.get(row, 1)
            middle_layout.setRowStretch(row, stretch)
        
        # Iterate over scatter widgets
        scatter_widgets = self.get_scatter_widgets().values()
        
        # Select the first scatter widget that has multiple modalities
        scatter_mod_widget = next((w for w in scatter_widgets if w.multiple_modalities), None)
                
        if scatter_mod_widget:
            modality_box = QComboBox()
            for name in scatter_mod_widget._modality_names:
                modality_box.addItem(name)

            modality_box.currentIndexChanged.connect(self._on_modality_changed)
            self._static_widgets["modality_box"] = modality_box
            top_layout.insertWidget(2, modality_box) # Insert on the left side of the other drop-down menus
        
        # Add the components to the main layout
        layout = QVBoxLayout()
        layout.addLayout(top_layout)
        layout.addLayout(middle_layout)
        layout.addLayout(bottom_layout)
        self.setLayout(layout)
        self._logger.debug("Created layout")

    def _connect_signals(self):
        '''
        Connects the signals between the components the annotation widget owns
        '''
        self._logger.debug("Connecting signals")
        # Cross connect each user configured widget with each other
        for key, widget in self._user_widgets.items():
            for other_key, other_widget in self._user_widgets.items():
                # Do NOT connect signal with yourself
                if other_key == key:
                    continue
                self._logger.debug(f"Connecting {key} -> {other_key}")
                widget.sign_cursor_moved.connect(other_widget.on_cursor_move)
                widget.sign_cursor_move_ended.connect(
                        other_widget.on_cursor_move_ended
                )

            # Connect each widgets "ready" signal with the annotation widget.
            widget.sign_ready.connect(self._on_ready)
            # Similarly, connect the error signals to the annotation widgets
            # error signal
            widget.sign_error.connect(self.sign_error)

            self.sign_widget_ready.connect(widget.on_startup)
        self._logger.debug("Connected signals")

    def _redraw(self, sample_id: SampleID) -> None:
        '''
        Draws the central data displaying components using the given data

        Parameters
        ----------
        sample_id: SampleID
            The id of the sample that should be used. NOTE: No checks are done
            to ensure that the sample exists already, and thus the user is
            responsible for ensuring that the given sample already exists.
        '''

        for wname, widget in self._user_widgets.items():
            if not widget.requires_update:
                continue
            try:
                widget.set_data(
                    self._asset_mngr.get_sample(wname, widget.wtype, sample_id)
                )
            except RuntimeError as e:
                self.sign_error.emit(f"{str(e)}")

        # Update the text labels
        n_labeled = self.parent()._controller.get_annotation_count()
        txt = "NA" if self._n_samples is None else self._n_samples
        self._static_widgets["index_label"].setText(
            _INDEX_TEMPLATE.format(n_labeled, txt)
        )
        self._static_widgets["sample_id_label"].setText(
                _FILE_ID_TEMPLATE.format(sample_id)
        )

    def _load_data(
            self, wtype: str, sample_id: SampleID, **kwargs: Mapping[str, Any]
            ) -> Dict[str, Any]:
        '''
        Load data for the given widget type.

        Parameters
        ----------
        wtype: str
            The widget type for which the data is loaded. Defines the used
            data-loader.
        sample_id: SampleID
            The id of the sample to load. Corresponds to the sample_id'th file
            in the given source directory.
        **kwargs: Mapping[str, Any]
            Any possible keyword arguments are passed to the loader?
            (NOT USED CURRENTLY)

        '''
        self._logger.debug("in _load_data")
        loader = self._LOADERS[wtype]
        source_dirs = kwargs.pop("source_dirs", [])
        if len(source_dirs) == 0:
            self.sign_error.emit(f"No source dirs for component {wtype}")
        out = {}
        for sdir in source_dirs:
            self._logger.debug(f"Processing source_dir: {sdir}")
            dirpath = pathlib.Path(sdir)
            files = [f for f in dirpath.iterdir() if f.is_file()]
            self._logger.debug("Counted files")
            files.sort()
            fpath = files[sample_id]
            self._logger.debug(f"Loading file {str(fpath)!r}")
            out[sdir] = loader(fpath)
        return out

    def _is_ready(self) -> bool:
        '''
        Returns True if all user configured widgets are ready, False otherwise.
        '''
        return self._n_ready_widgets == len(self._user_widgets)

    def _force_label_save(self, idx: int):
        '''
        Changes the index of the label and manually invokes the saving of the
        current state. Useful, as the QComboBox doesn't seem to always send
        the "currentTextChanged" signal when the previous state was not set.

        Parameters
        ----------
        idx: int
            The index of the label to set to the widget.
        '''
        label_box = self._static_widgets["label_box"]
        with SignalBlocker(label_box):
            label_box.setCurrentIndex(idx)
            self._save_label(label_box.currentText())
    # ===================== SLOTS ==========================
    # ----> Public ---->

    @Slot()
    def set_sample(
            self, sample_id: SampleID, label: Optional[str], order_num: int
            ):
        '''
        Sets and displays the next sample.

        Parameters
        ----------
        sample_id: SampleID
            The sample to display.
        label: Optional[str]
            The label of this sample. If accessed first time, will be None.
        order_num: int
            The order number of the sample
        '''
        self._logger.debug((f"in 'set_sample' -> SampleID: {sample_id} "
                            f"label: {label}, ptr: {self._ptr}, "
                            f"order num {order_num}"))
        self._current_sample = sample_id

        # If the pointer and order number are mismatched, update the pointer
        # value match the order number.
        if order_num != self._ptr:
            self._ptr = order_num
            if self._ptr >= self._len:
                self._len += 1
        self._redraw(sample_id)

        # NOTE: The label box seems to be little inconsistent on sending the
        # "currentTextChanged" signal if the change is done from here. Thus the
        # send of this signal must be forced. To avoid duplicate signals,
        # remove the connection temporarily

        # Also accept the label of the sample, in case it was already labeled
        # previously. Otherwise set the default to first label
        label_box = self._static_widgets["label_box"]
        if label is None:
            idx = label_box.findText(str(SampleState.UNLABELED))
        else:
            idx = label_box.findText(label)

        if idx == -1:
            self._logger.warning(("Could not find label from label-box, "
                                  "setting the first label as a backup"))
            idx = 0

        self._logger.debug(f"Setting label id {idx}")
        # Ensure that the current state is updated
        self._force_label_save(idx)

        # If we are on the last sample, disable back button, otherwise enable
        # it
        self._static_widgets["prev_btn"].setEnabled(self._ptr != 0)

        # If all the widgets are ready, the next button should be enabled.
        if (self._is_ready() and not self._static_widgets["next_btn"].isEnabled()):
            self._static_widgets["next_btn"].setEnabled(True)
            
        # Highlight the selected sample in all scatter widgets
        for widget in self.get_scatter_widgets().values():
            try:
                widget._highlight_selected_sample(sample_id)
            except Exception as e:
                self._logger.warning(f"Failed to highlight sample {sample_id} in widget {widget}: {e}")

    @Slot(object)
    def after_dim_reduction(self, args: Tuple[str, npt.NDArray]):
        '''
        Applies the results of dimensionality reduction to components that need
        it. Currently only changes the scatter widget if it is in place.

        Parameters
        ----------
        name: str
            The name of the widget for which the dimensionality reduction was
            requested for.
        data: npt.NDArray
            The data from the dimensionality reduction
        '''

        # If the user has cancelled the dimensionality reduction, just
        # reset the flag and return
        if not self._use_dim_reduction:
            self._use_dim_reduction = True
            return

        name, data = args
        if name not in self._user_widgets:
            self.sign_error.emit(f"{name!r} is not a valid widget!")

        w_scatter = self._user_widgets[name]
        # Set the updated data
        w_scatter.set_data(data)

    @Slot()
    def dim_reduction_cancelled(self):
        self._use_dim_reduction = False

    @Slot()
    def on_last_sample(self):
        '''
        Called when last sample is detected. Will set the
        '''
        self._static_widgets["next_btn"].setEnabled(False)

    # ----> Private ---->

    @Slot(str)
    def _ask_dim_reduction(self, algo_name: str):
        '''
        Request dimensionality reduction using the given algorithm.

        Parameters
        ----------
        algo_name: str
            The name of the used algorithm
        '''
        self._logger.debug(f"Asking for a dim reduction with {algo_name}")
        settings = self.parent().settings

        if algo_name not in settings.dim_reductions:
            self.sign_error.emit((f"{algo_name!r} not in the defined "
                                  "dim-reductions"))
            return

        # Remove possible "default" key from the config, as it is not
        # argument for the algorithm. A copy is taken to ensure that the global
        # settings are not changed.
        config = settings.dim_reductions[algo_name]

        for name, widget in self._user_widgets.items():
            if widget.wtype == WidgetType.SCATTER:
                self.sign_request_dim_reduction.emit(
                        name, widget.file, algo_name, config
                )

    @Slot(str)
    def _save_label(self, label: str):
        '''
        Saves the given label to the file id

        Parameters
        ----------
        label: str
            The label to store
        '''

        self._logger.debug(("Emitting 'sign_sample_state_changed' with "
                            f"{self._current_sample}: {label}"))
        self.sign_sample_state_changed.emit(self._current_sample, label)

    @Slot()
    def _request_next_sample(self):
        ''' Save the current label, and emit signal to ask for next sample '''

        # Start by saving the label of the current sample
        assert self._ptr >= 0, f"ptr == {self._ptr}! Should always be >= 0"

        self._save_label(self._static_widgets["label_box"].currentText())

        # If the next sample is completely new, increase the length by one
        if self._ptr == self._len:
            self._len += 1
        self._ptr += 1
        self._logger.debug(f"Requesting sample {self._ptr}")
        self.sign_request_sample.emit(self._ptr)

    @Slot()
    def _prev_sample(self):
        '''Backtrack one sample in time'''

        # Save the current label
        self._save_label(self._static_widgets["label_box"].currentText())

        # Backtrack to the previous sample
        self._ptr -= 1

        # Request the sample with given order number
        self.sign_request_sample.emit(self._ptr)

    @Slot()
    def _parse_selected_sample(self, sid: SampleID):
        '''
        Checks if the sample selected by user is not annotated currently.

        Parameters
        ----------
        sid: SampleID
            The sample that the user clicked on.
        '''
        # If the user clicked the sample that is currently on display, we don't
        # do anything. Otherwise, we propagate the signal forward.
        if sid != self._current_sample:
            self.sign_user_selected_sample.emit(sid)

    @Slot()
    def _get_current_dim_reduction_config(self) -> Tuple[str, Dict[str, Any]]:
        '''
        Returns
        -------
        Tuple[str, Dict[str, Any]]
            The name of the currently selected dimensionality reduction
            algorithm and the configuration for it.
        '''
        name = self._static_widgets["dim_reduction_box"].currentText()
        user_settings = self.parent().settings
        if name not in user_settings.dim_reductions:
            self.sign_error.emit((f"Cannot find {name!r} from possible dim "
                                  "reductions!"))
            return
        return name, user_settings.dim_reductions[name]

    @Slot()
    def _on_ready(self):
        '''
        This signal handler is called when one of the sub-widgets emits "ready"
        signal. When all the required components have emitted "ready" signal,
        activates the required buttons
        '''
        self._n_ready_widgets += 1
        self._logger.debug(f"Ready {self._n_ready_widgets}/{len(self._user_widgets)}")

        if self._n_ready_widgets != len(self._user_widgets):
            progress = math.floor(
                    100*(self._n_ready_widgets/len(self._user_widgets))
            )
            self.sign_progress_update.emit(progress)
            return

        self._static_widgets["next_btn"].setEnabled(True)
        self._static_widgets["prev_btn"].setEnabled(self._ptr != 0)

        self.sign_widget_ready.emit()
    
    @Slot(int)
    def _on_modality_changed(self, idx: int):
        ''' Called when data modality is changed '''
        # Update modality in all scatter widgets
        for name, sc in self.get_scatter_widgets().items():
            if sc.multiple_modalities:
                sc.set_modality(idx)

                # Trigger the dimensionality reduction
                algo_name, config = self._get_current_dim_reduction_config()

                self.sign_request_dim_reduction.emit(
                    name,        # widget name
                    sc.file,     # active modality file
                    algo_name, 
                    config
                )
    
    def eventFilter(self, obj, event):
        '''
        Handles keyboard shortcuts:
         - Numbers 0, 1, 2, ..., 9 for label selection
         - Enter/Return for the "next sample" button
        '''
        if event.type() == event.Type.KeyPress:
            key = event.key()
            label_box = self._static_widgets.get("label_box")
            if not label_box:
                return False
            
            # Handle numeric keys for label selection
            index = None
            if key == Qt.Key_0:
                index = 0
            elif Qt.Key_1 <= key <= Qt.Key_9:
                index = key - Qt.Key_1 + 1

            if index is not None and index < label_box.count():
                label_box.setCurrentIndex(index)
                return True  # event handled
            
            # Handle Enter or Return for "next sample"
            if key in (Qt.Key_Return, Qt.Key_Enter):
                self._request_next_sample()
                return True  # event handled

        return super().eventFilter(obj, event)
