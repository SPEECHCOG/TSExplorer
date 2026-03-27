'''This module defines the basis for the dimensionality reduction algorithms.
All the used algorithms should have a .fit and .transform method, similarly to
the algorithms defined in scikit-learn
'''
from .utils import io

from abc import ABC, abstractmethod
from typing import Dict, Mapping, Any

from sklearn.manifold import TSNE
from sklearn.decomposition import PCA
from sklearn.preprocessing import StandardScaler
import umap

import numpy.typing as npt


class IDimReduction(ABC):
    '''Defines the interface for the dimensionality reduction algorithms'''

    @abstractmethod
    def fit(self, x):
        raise NotImplementedError()

    @abstractmethod
    def transform(self, x):
        raise NotImplementedError()


class Umap:
    '''
    Wrapper for the excellent umap implementation from 'umap-learn'.
    Provides the possibility to use precomputed knn, and scaling the
    data with z-score normalization.
    '''
    def __init__(self, **kwargs: Mapping[str, Any]):
        '''
        Creates a new Umap class.

        Parameters
        ----------
        kwargs: Mapping[str, Any]
            Any possible keyword arguments to the umap.UMAP class.
            The following two arguments are specialized:
            - 'precomputed_knn': str
                Path to the serialized precomputed knn parameters. NOTE:
                should be used only with large datasets (otherwise umap will
                just discard the parameter)
            - 'normalize': bool
                If set to True, the data will be z-normalized before UMAP is
                applied to the data. This is recommended for the UMAP
            - metric: string
                The used distance metric

        '''
        if "precomputed_knn" in kwargs:
            fp = kwargs.pop("precomputed_knn")
            knn = io.load(fp)
            kwargs["precomputed_knn"] = knn

        # By default the data won't be normalized
        self._normalize = kwargs.pop("normalize", False)
        self._umap = umap.UMAP(**kwargs)

    def fit_transform(self, data: npt.NDArray) -> npt.NDArray:
        '''
        Apply UMAP to the given data.

        Parameters
        ----------
        data: npt.NDArray
            The data which the algorithm is applied to.

        Returns
        -------
        npt.NDArray
            The dimensionality reduced data.
        '''
        if self._normalize:
            data = StandardScaler().fit_transform(data)
        return self._umap.fit_transform(data)


# The currently supported dimensionality reduction algorithms
_SUPPORTED_DIM_REDUCTION_ALGOS: Dict[str, IDimReduction] = {
        "tsne": TSNE,
        "pca": PCA,
        "umap": Umap
}


def get_dim_reduction(name: str) -> IDimReduction:
    '''
    Returns the dimensionality reduction algorithm based on the given name.

    Parameters
    ----------
    name: str
        The name of the algorithm. Note: Is NOT case sensitive

    Returns
    -------
    IDimReduction
        The concrete class of the dimensionality reduction algorithm
    '''
    if name.lower() not in _SUPPORTED_DIM_REDUCTION_ALGOS:
        raise KeyError((f"Unknown algorithm {name.lower()!r}. Supported "
                        "algorithms are "
                        f"{', '.join(_SUPPORTED_DIM_REDUCTION_ALGOS.keys())}"))
    return _SUPPORTED_DIM_REDUCTION_ALGOS[name]
