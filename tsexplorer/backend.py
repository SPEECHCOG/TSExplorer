''' This module defines a backend interface for that can be used to
select the clips from given directories, and the ordering for them
'''

from .ibackend import ISelector
from .utils import io, logger
from .metadata import SampleID, Path, SampleState

from typing import Dict, Mapping, List, Any
from typing import Optional as Optional_t  # To avoid name conflicts
import pathlib

# For validating the kwargs given by the user
from schema import Schema, Use, Optional, And

from sklearn.metrics import pairwise_distances

from PySide6.QtCore import QObject, Signal, Slot

import numpy as np
import numpy.typing as npt

_QUEUED_POINTS: str = "queued_points"
_CONST_POINTS: str = "const_points"
_RNG: str = "rng"



class OrderedSelector(QObject):
    '''
    Selects samples in the order they appear in the dataset.
    '''

    sign_sample_selected = Signal(object, object, name="sign_sample_selected")
    sign_sample_updated = Signal(int, object, name="sign_sample_updated")

    _KWARGS_SCHEMA = Schema({
        "source_path": Use(pathlib.Path),
        Optional("cluster_id_path", default=None): And(
            Use(pathlib.Path), lambda fp: fp.suffix in [".csv", ".npy"]
        )
    })

    def __init__(self, parent: Optional_t[QObject] = None, **kwargs: Mapping[str, Any]):
        super().__init__(parent)
        self._logger = logger.get_logger("ordered-selector")
        kwargs = self._KWARGS_SCHEMA.validate(kwargs)

        self._source_path = kwargs["source_path"]
        features = io.load_numpy(self._source_path)
        self._indexes = np.arange(features.shape[0])
        self._ptr = 0

        self._const_points: Dict[int, None] = {}
        self._queued_points: Dict[int, None] = {}

        cluster_id_path = kwargs.get("cluster_id_path")
        if cluster_id_path is None:
            self._cluster_ids = [None for _ in range(features.shape[0])]
        else:
            self._cluster_ids = _load_cluster_ids(cluster_id_path)

    @Slot()
    def select_sample(self):
        while self._ptr < len(self._indexes):
            idx = self._indexes[self._ptr]
            self._ptr += 1
            if idx not in self._const_points and idx not in self._queued_points:
                self._const_points[idx] = None
                cluster_id = self._cluster_ids[idx]
                self._logger.debug(f"Selected sample: {idx}")
                self.sign_sample_selected.emit(idx, cluster_id)
                return
        raise RuntimeError("All samples are already selected!")

    @Slot()
    def on_sample_state_change(self, sid: SampleID, state: str):
        cluster_id = self._cluster_ids[sid]
        if cluster_id is not None:
            self.sign_sample_updated.emit(sid, {"clusterid": int(cluster_id)})

        if state != SampleState.SELECTED and state != SampleState.UNLABELED:
            return
        elif state == SampleState.UNLABELED and sid in self._queued_points:
            self._queued_points.pop(sid)
        elif state == SampleState.UNLABELED and sid not in self._const_points:
            self._const_points[sid] = None
        elif state == SampleState.SELECTED:
            self._queued_points[sid] = None
    def reset(self):
        self._ptr = 0
        self._const_points = {}
        self._queued_points = {}

    def serialize(self, session_dir: Path) -> Dict[str, Any]:
        base_path = pathlib.Path(session_dir)
        io.dump_npy(base_path / "ordered_visited_points.npy", list(self._const_points))
        io.dump_npy(base_path / "ordered_queued_points.npy", list(self._queued_points))
        io.dump_npy(base_path / "cluster_ids.npy", self._cluster_ids)

        return {
            "source_path": str(self._source_path),
            _CONST_POINTS: str(base_path / "ordered_visited_points.npy"),
            _QUEUED_POINTS: str(base_path / "ordered_queued_points.npy"),
            "cluster_ids": str(base_path / "cluster_ids.npy"),
            "ptr": self._ptr
        }

    def deserialize(self, payload: Mapping[str, Any]):
        self._ptr = payload["ptr"]
        self._const_points = {sid: None for sid in payload[_CONST_POINTS]}
        self._queued_points = {sid: None for sid in payload[_QUEUED_POINTS]}
        self._cluster_ids = payload["cluster_ids"].tolist()
        self._source_path = payload["source_path"]

        features = io.load_numpy(self._source_path)
        self._indexes = np.arange(features.shape[0])





class RandomSelector(QObject):
    '''
    Defines a selector that selects the annotated samples randomly, and doesn't
    take into account if some samples are already labeled or not.
    '''

    sign_sample_selected = Signal(object, object, name="sign_sample_selected")
    sign_sample_updated = Signal(int, object, name="sign_sample_updated")

    # For validating the user specified arguments
    _KWARGS_SCHEMA = Schema({
        "source_path": Use(pathlib.Path),
        Optional("seed", default=None): Use(int),
        Optional(
            "cluster_id_path", default=None
        ): And(Use(pathlib.Path), lambda fp: fp.suffix in [".csv", ".npy"])
    })

    def __init__(
            self, parent: Optional_t[QObject] = None,
            **kwargs: Mapping[str, Any]
            ):
        '''
        Creates a RandomSelector.

        Parameters
        ----------
        parent: Optional_t[QObject]
            The parent of this object. Default None.
        kwargs: Mapping[str, Any]
            Any possible user configured parameters. Currently used values:
                source_path: str
                    Path to the .npy file containing the data.
                seed: int
                    The seed used for the pseudorandom number generator.
                cluster_id_path: str
                    Path to the cluster ids
        '''
        super().__init__(parent)
        self._logger = logger.get_logger("random-selector")
        # Validate user specified arguments
        kwargs = self._KWARGS_SCHEMA.validate(kwargs)
        self._source_path = kwargs.get("source_path")
        self._rng = np.random.default_rng(kwargs.get("seed"))

        features = io.load_numpy(self._source_path)
        self._indexes = np.arange(features.shape[0])

        # Store the points that are queued, and points that are already visited
        # separately.
        self._queued_points: Dict[int, None] = {}
        self._const_points: Dict[int, None] = {}

        # Load the cluster ID
        self._logger.debug(f"kwargs: {kwargs}")
        cluster_id_path = kwargs.get("cluster_id_path")
        if cluster_id_path is None:
            self._cluster_ids = [None for _ in range(features.shape[0])]
        else:
            self._cluster_ids = _load_cluster_ids(cluster_id_path)

    @Slot()
    def select_sample(self):
        '''
        Selects a given number of samples randomly. Already selected samples
        are skipped. Emits a 'sign_sample_selected' with the selected samples.

        Parameters
        ----------
        number: int
            The number of ids selected.
        '''
        # Now we must generate samples in such way that the already selected
        # points won't be selected twice
        all_selected_points = list({
                **self._queued_points, **self._const_points
        })

        if len(all_selected_points) + 1 > self._indexes.shape[0]:
            raise RuntimeError("All samples are already selected!")

        candidates = np.setdiff1d(
                self._indexes, all_selected_points, assume_unique=True
        )
        ind = self._rng.choice(candidates, size=1, replace=False).item()
        self._const_points[ind] = None
        self._logger.debug(f"Selected sample: {ind}")
        self._logger.debug((f"Already selected points: "
                           f"{list(self._const_points)}"))

        cluster_id = self._cluster_ids[ind]
        self.sign_sample_selected.emit(ind, cluster_id)

    @Slot()
    def on_sample_state_change(self, sid: SampleID, state: str):
        '''
        Updates the state of the given sample to the local storage used to
        ensure that same point is not selected twice.

        Parameters
        ----------
        sid: SampleID
            The sample which state has changed.
        state: str
            The new state of the sample. Should be one of the SampleStates.
        '''
        # Regardless of the update, emit the (possibly) new cluster-id
        # of the sample to the database.
        cluster_id = self._cluster_ids[sid]
        if cluster_id is not None:
            self.sign_sample_updated.emit(sid, {"clusterid": int(cluster_id)})
        # Possible cases:
        # 1. Sample was annotated -> Return immediately
        # 2. Samples state is UNLABELED and it is in queued points
        # -> User has removed the selection, so we should remove the point
        #    from the list, so that it can be selected by the algorithm.
        # 3. Sample state is UNLABELED, and point is not in const points and
        #    not in queued points.
        # -> User clicked on this point, and it is now visited. -> Add to
        #    the visited points so that it is not selected again.
        # 4. Sample state is UNLABELED, and the point is visited (i.e. const).
        # -> User just skipped over labeling the point, and thus we should
        # keep the point in the list so that it is not selected again by us.
        # 5. Sample was queued by user, and thus must be added to the list

        # Case 1
        if state != SampleState.SELECTED and state != SampleState.UNLABELED:
            return

        # Case 2
        elif state == SampleState.UNLABELED and sid in self._queued_points:
            self._queued_points.pop(sid)
            # return

        # Case 3
        elif (state == SampleState.UNLABELED and
              sid not in self._queued_points and
              sid not in self._const_points):
            self._const_points[sid] = None
            # return

        # Case 4
        elif state == SampleState.UNLABELED and sid in self._const_points:
            return

        # Case 5
        elif state == SampleState.SELECTED:
            self._queued_points[sid] = None

        self._logger.debug("After update, queued samples: "
                           f"{list(self._queued_points)}")
        self._logger.debug("After update, visited samples: "
                           f"{list(self._const_points)}")

    def reset(self):
        ''' Resets the internal state of the application'''
        self._const_points = {}
        self._queued_points = {}

    def serialize(self, session_dir: Path) -> Dict[str, Any]:
        '''
        Serializes the current state of the backend to JSON/YAML format

        Parameters
        ----------
        session_dir: Path
            Currently used session directory

        Returns
        -------
        Dict[str, Any]
            The serialized state
        '''
        base_path = pathlib.Path(session_dir)
        visited_points_path = base_path / "rand_visited_points.npy"
        io.dump_npy(visited_points_path, list(self._const_points))

        queued_points_path = base_path / "rand_queued_points.npy"
        io.dump_npy(queued_points_path, list(self._queued_points))

        cluster_id_path = base_path / "cluster_ids.npy"
        io.dump_npy(cluster_id_path, self._cluster_ids)

        return {
                "source_path": str(self._source_path),
                _CONST_POINTS: str(visited_points_path),
                _QUEUED_POINTS: str(queued_points_path),
                "cluster_ids": str(cluster_id_path),
                _RNG: self._rng.bit_generator.state
        }

    def deserialize(self, payload: Mapping[str, Any]):
        '''
        Restores the previous state from a serialized state

        Parameters
        ----------
        payload: Mapping[str, Any]
            The serialized state of the application

        '''
        self._rng.bit_generator.state = payload[_RNG]
        self._const_points = {
                sid: None for sid in payload[_CONST_POINTS]
        }

        self._queued_points = {
                sid: None for sid in payload[_QUEUED_POINTS]
        }

        self._cluster_ids = payload["cluster_ids"]
        self._source_path = payload["source_path"]
        self._cluster_ids = payload["cluster_ids"].tolist()

        if "features" in payload:
            features = payload["features"]
        else:
            features = io.load_numpy(self._source_path)

        self._indexes = np.arange(features.shape[0])


class FarthestFirstTraversalSelector(QObject):
    '''
    Implements selector using farthest-first traversal principle.
    '''
    sign_sample_selected = Signal(object, object, name="sign_sample_selected")
    sign_sample_updated = Signal(int, object, name="sign_sample_updated")

    _KWARGS_SCHEMA = Schema({
        "source_path": Use(pathlib.Path),
        Optional("cluster_id_path", default=None): And(
            Use(pathlib.Path), lambda fp: fp.suffix in [".csv", ".npy"]
        ),
        Optional("affinity_matrix_path", default=None): Use(lambda fp: pathlib.Path(fp) if fp is not None else None),
        Optional("seed", default=None): int,
        Optional("precomputed_index_path", default=None): Use(lambda fp: pathlib.Path(fp) if fp is not None else None),
    })


    def __init__(self, parent: Optional_t[QObject] = None, **kwargs: Mapping[str, Any]):
        super().__init__(parent)
        self._logger = logger.get_logger("fft-selector")
        kwargs = self._KWARGS_SCHEMA.validate(kwargs)

        self._source_path = kwargs.get("source_path")
        self._rng = np.random.default_rng(kwargs.get("seed"))

        affinity_matrix_path = kwargs.get("affinity_matrix_path")
        precomputed_index_path = kwargs.get("precomputed_index_path")
        
        self._features = io.load_numpy(self._source_path)
        
        if precomputed_index_path is not None:
            self._medoids = self._load_precomputed_indices(precomputed_index_path, self._features.shape[0])
            self._dist_mat = None
        elif affinity_matrix_path is not None:
            self._dist_mat = io.load_numpy(affinity_matrix_path)
            self._medoids = self._compute_faft_medoids_from_matrix(self._dist_mat)
        else:
            self._dist_mat = None
            self._medoids = self._compute_faft_medoids(self._features, self._features.shape[0])

        self._const_points: Dict[int, None] = {}
        self._queued_points: Dict[int, None] = {}

        cluster_id_path = kwargs.get("cluster_id_path")
        if cluster_id_path is None:
            self._cluster_ids = [None for _ in range(self._medoids.shape[0])]
        else:
            self._cluster_ids = _load_cluster_ids(cluster_id_path)

        self._ptr = 0

    def _compute_faft_medoids(self, X: npt.NDArray, k: int, metric: str = "euclidean") -> npt.NDArray:
        N = X.shape[0]
        rng = self._rng
        selected = [rng.integers(N)]
        distances = np.full(N, np.inf)

        for _ in range(k - 1):
            new_distances = pairwise_distances(X, X[selected[-1]].reshape(1, -1), metric=metric, n_jobs=-1).flatten()
            distances = np.minimum(distances, new_distances)
            next_idx = np.argmax(distances)
            selected.append(next_idx)

        return np.array(selected, dtype=np.int64)
    
    def _compute_faft_medoids_from_matrix(self, dist_mat: npt.NDArray) -> npt.NDArray:
        N = dist_mat.shape[0]
        rng = self._rng
        selected = [rng.integers(N)]
        distances = np.full(N, np.inf)
    
        for _ in range(N - 1):
            distances = np.minimum(distances, dist_mat[:, selected[-1]])
            next_idx = np.argmax(distances)
            selected.append(next_idx)
    
        return np.array(selected, dtype=np.int64)
    
    def _load_precomputed_indices(self, path: pathlib.Path, num_samples: int) -> npt.NDArray:
        indices = io.load_numpy(path).flatten()
        if len(set(indices)) != len(indices):
            raise ValueError("Precomputed index matrix contains duplicate indices.")
        if np.any(indices >= num_samples) or np.any(indices < 0):
            raise ValueError("Precomputed index matrix contains out-of-bound indices.")
        return indices.astype(np.int64)
    
    @Slot()
    def select_sample(self):
        if self._ptr >= self._medoids.shape[0]:
            raise RuntimeError("Reached the end of the precomputed traversal indices. No more samples to select.")
        elif self._ptr == self._medoids.shape[0]:
            raise ValueError("All samples are already selected")

        ind = None
        while ind is None and self._ptr < self._medoids.shape[0]:
            idx = self._medoids[self._ptr]
            if idx in self._queued_points or idx in self._const_points:
                self._ptr += 1
                continue
            ind = idx
            self._ptr += 1
        
        if ind is None:
            raise RuntimeError("All samples are already selected or skipped.")
        
        cluster_id = self._cluster_ids[ind]
        self._const_points[ind] = None
        self._logger.debug(f"Selected index: {ind}, cluster-id: {cluster_id}")
        self.sign_sample_selected.emit(ind, cluster_id)

    @Slot()
    def on_sample_state_change(self, sid: SampleID, state: str):
        cluster_id = self._cluster_ids[sid]
        if cluster_id is not None:
            self.sign_sample_updated.emit(sid, {"clusterid": int(cluster_id)})

        if state != SampleState.SELECTED and state != SampleState.UNLABELED:
            return
        elif state == SampleState.UNLABELED and sid in self._queued_points:
            self._queued_points.pop(sid)
        elif state == SampleState.UNLABELED and sid not in self._const_points:
            self._const_points[sid] = None
        elif state == SampleState.SELECTED:
            self._queued_points[sid] = None

        self._logger.debug(f"After update, visited points: {list(self._const_points)}")
        self._logger.debug(f"After update, queued points: {list(self._queued_points)}")

    def reset(self):
        self._ptr = 0
        if self._dist_mat is not None:
            self._medoids = self._compute_faft_medoids_from_matrix(self._dist_mat)
        else:
            self._medoids = self._compute_faft_medoids(self._features, self._features.shape[0])
        self._const_points = {}
        self._queued_points = {}

    def serialize(self, session_dir: Path) -> Dict[str, Any]:
        payload = {}
        base_path = pathlib.Path(session_dir)

        payload[_RNG] = self._rng.bit_generator.state
        payload["ptr"] = self._ptr

        io.dump_npy(base_path / "fft_visited_points.npy", list(self._const_points))
        payload[_CONST_POINTS] = str(base_path / "fft_visited_points.npy")

        io.dump_npy(base_path / "fft_queued_points.npy", list(self._queued_points))
        payload[_QUEUED_POINTS] = str(base_path / "fft_queued_points.npy")

        io.dump_npy(base_path / "fft_medoids.npy", self._medoids)
        payload["medoids"] = str(base_path / "fft_medoids.npy")

        io.dump_npy(base_path / "cluster_ids.npy", self._cluster_ids)
        payload["cluster_ids"] = str(base_path / "cluster_ids.npy")

        payload["source_path"] = str(self._source_path)
        return payload

    def deserialize(self, payload: Mapping[str, Any]):
        self._rng.bit_generator.state = payload[_RNG]
        self._const_points = {sid: None for sid in payload[_CONST_POINTS]}
        self._queued_points = {sid: None for sid in payload[_QUEUED_POINTS]}
        self._ptr = payload["ptr"]
        self._medoids = payload["medoids"]
        self._cluster_ids = payload["cluster_ids"].tolist()
        self._source_path = payload["source_path"]

        if "features" in payload:
            self._features = payload["features"]
        else:
            self._features = io.load_numpy(self._source_path)

def _load_cluster_ids(fpath: pathlib.Path) -> List[int]:
    if fpath.suffix == ".csv":
        cluster_ids = io.load_csv(fpath, header=None).to_numpy()
    else:
        cluster_ids = io.load_numpy(fpath)

    if cluster_ids.ndim == 2:
        idx = cluster_ids[:, 0]
        cluster_ids = cluster_ids[idx, 1]
    return cluster_ids.tolist()




_SELECTORS: Dict[str, ISelector] = {
        "random": RandomSelector,
        "farthest-first": FarthestFirstTraversalSelector,
        "ordered": OrderedSelector
}


def load_selector(
        name: str, **kwargs: Mapping[str, Any]
        ) -> ISelector:
    if name not in _SELECTORS:
        raise KeyError((f"Unknown selector {name!r} Known selectors are "
                        f"{', '.join(f'{key!r}' for key in _SELECTORS.keys())}"))

    klass = _SELECTORS[name]
    return klass(**kwargs)
