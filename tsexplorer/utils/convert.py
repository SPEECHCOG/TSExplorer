'''This module defines unit type conversions'''
from typing import Union, Any

import numpy as np
import numpy.typing as npt

_F_SP = 200.0 / 3
_F_MIN = 0.0
_MEL_MIN_LOG_HZ = 1000.0
_MEL_LOG_STEP = np.log(6.4) / 27.0


def samples_to_seconds(samples: npt.NDArray, sr: int) -> npt.NDArray:
    '''
    Converts the given samples to seconds

    Parameters
    ----------
    samples: npt.NDArray
        The samples to convert
    sr: int
        The sampling rate used to collect the samples

    Returns
    -------
    npt.NDArray
        The corresponding timesteps
    '''
    return samples.astype(float)/sr


def frames_to_seconds(frames: npt.NDArray, hop_ms: int) -> npt.NDArray:
    '''
    Converts frames to seconds.

    Parameters
    ----------
    frames: npt.NDArray
        The frames to convert
    hop_ms: int
        The hop length as milliseconds.

    Returns
    -------
    npt.NDArray
        The corresponding timesteps.
    '''
    return frames * hop_ms * 1e-3


def to_mel_freqs(
        n_mels: int, fmin: float = 0.0, fmax: float = 11025.0
        ) -> npt.NDArray:
    '''
    Calculate the mel frequency bins. NOTE: Tries to match the behaviour
    of librosa implementation, which itself matches the MATLAB audio toolbox
    behaviour. See
    https://github.com/librosa/librosa/blob/aa9f53357b4ddd8e4c8500ea88d3493a4c73cf20/librosa/core/convert.py#L1670
    for more details
    '''
    min_mel = hz_to_mel(fmin)
    max_mel = hz_to_mel(fmax)
    mels = np.linspace(min_mel, max_mel, n_mels)
    hz = mel_to_hz(mels)
    return hz


def mel_to_hz(
        mels: Union[float, npt.ArrayLike]
        ) -> Union[np.floating[Any], npt.NDArray[float]]:
    '''
    Converts mel frequency bins to frequencies (Hz). Matches the librosa
    implementation.

    Parameters
    ----------
    mels: float | np.NDArrayLike[np.floating]
        The mel bins to convert.

    Returns
    -------
    np.floating[Any] | np.NDArray[np.floating]
        The frequency bins
    '''
    mels = np.asanyarray(mels)

    # Linear part
    freqs = _F_MIN + _F_SP * mels

    # Non-linear scaling part
    min_log_mel = (_MEL_MIN_LOG_HZ - _F_MIN) / _F_SP

    if mels.ndim:
        # If the value is an array
        log_idx = mels >= min_log_mel
        freqs[log_idx] = _MEL_MIN_LOG_HZ * \
            np.exp(_MEL_LOG_STEP * (mels[log_idx] - min_log_mel))
    elif mels >= min_log_mel:
        # Only a scalar value
        freqs = _MEL_MIN_LOG_HZ * np.exp(_MEL_LOG_STEP * (mels - min_log_mel))

    return freqs


def hz_to_mel(
        freqs: Union[float, npt.ArrayLike]
        ) -> Union[np.floating[Any], npt.NDArray[float]]:
    '''
    Converts frequencies (Hz) to mel-spectrum. Matches the librosa
    implementation.

    Parameters
    ----------
    freqs: float | npt.ArrayLike[np.floating]
        The frequencies to convert. Can be either a single frequency, or
        a list of frequencies.

    Returns
    -------
    np.floating[Any] | npt.NDArray[np.floating]
        The mel-frequency bin(s)

    '''
    freqs = np.asarray(freqs, dtype=np.float64)

    # Linear part
    mels = (freqs - _F_MIN) / _F_SP

    # Log-scale part
    min_log_mel = (_MEL_MIN_LOG_HZ - _F_MIN) / _F_SP

    if freqs.ndim:
        log_idx = freqs >= _MEL_MIN_LOG_HZ
        mels[log_idx] = min_log_mel + \
            np.log(freqs[log_idx] / _MEL_MIN_LOG_HZ) / _MEL_LOG_STEP
    elif freqs >= _MEL_MIN_LOG_HZ:
        mels = min_log_mel + np.log(freqs / _MEL_MIN_LOG_HZ) / _MEL_LOG_STEP

    return mels
