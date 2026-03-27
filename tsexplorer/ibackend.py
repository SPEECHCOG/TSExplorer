''' Defines the interface for the selectors that can be used as backends'''

from .metadata import SampleID

from abc import ABC
from typing import Dict, Any, Mapping


class ISelector(ABC):
    '''Defines a common interface for selectors

    Supported signal signatures

    sign_sample_selected: (npt.NDArray, List[Optional[int]])
        Emitted when new samples are selected. Contains a list of samples,
        and the corresponding cluster IDs. If no cluster ID can be given
        to the sample, the ID can be None
    sign_sample_updated: (int, Mapping[str, Any])
        Emitted when the sample's properties are (possibly) updated. Contains
        the sample id, and the (possibly) updated values for the properties.
    '''

    def select_sample(self):
        '''
        Selects the next id to annotate.

        Emits
        -----
        sign_sample_selected: int, Optional[int]
            Emits the id of the sample to annotate next, and the possible
            cluster id. If clustering is not supported, or the cluster id
            cannot be inferred at this time, it will be None.
        '''
        raise NotImplementedError("")

    def on_sample_state_change(self, sid: SampleID, state: str):
        '''
        Update the state of a given sample if it is required (i.e. when
        keeping count of selected samples)

        Parameters
        ----------
        sid: SampleID
            The sample whose state changed

        state: str
            The new state of the sample. Should be one of the SampleStates.
        '''

    def reset(self):
        '''Resets the internal state of the backend'''
        raise NotImplementedError("")

    def serialize(self) -> Dict[str, Any]:
        '''
        Serializes the state of the backend to a JSON/YAML supported format.

        Returns
        -------
        Dict[str, Any]
            The serialized state of the application
        '''
        raise NotImplementedError("")

    def deserialize(self, payload: Mapping[str, Any]):
        '''
        Restores the previously saved state of the selector from the given
        payload

        Parameters
        ----------
        payload: Mapping[str, Any]
            The payload containing the previously saved version of the
            selector.
        '''
        raise NotImplementedError("")
