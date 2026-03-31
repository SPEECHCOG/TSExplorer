# TSExplorer: An interactive data annotation and visualization tool for time-series data

This repository contains a graphical user interface (GUI)-based interactive data annotation and visualization tool for time-series data called **Time-Series Explorer (TSExplorer)**. TSExplorer visualizes the entire dataset as a 2D scatter plot and allows annotators to freely explore complementary 2D representations of the underlying high-dimensional data. The code is partially implemented using the official PySide bindings for Qt6.

TSExplorer has been used in the following publication (**NOTE: arXiv pre-print only, publication venue not yet confirmed**):
[E. Vaaras, M. Airaksinen, and O. Räsänen, "Evaluating Interactive 2D Visualization as a Sample Selection Strategy for Biomedical Time-Series Data Annotation", _(arXiv pre-print, publication venue will be updated here later)_](https://arxiv.org/abs/2603.26592).

If you use the present code or its derivatives, please cite the [repository URL](https://github.com/SPEECHCOG/TSExplorer) and/or the [aforementioned publication](https://arxiv.org/abs/2603.26592).

<ins>**Please note**</ins> that, while some features will still be added to TSExplorer, the code is not under constant maintenance. If you encounter any issues with the code or would like to request additional features, please contact [Einari Vaaras](https://www.tuni.fi/en/people/einari-vaaras).


| ![An example screenshot of TSExplorer](figures/tsexplorer_maiju_posture_example_image.png) |
|:--:|
| *Figure 1: An example screenshot of TSExplorer (from [Vaaras et al. (2026)](https://arxiv.org/abs/2603.26592)).* |


## Installation
The application should work on Windows, Linux, and MacOS, with Python versions 3.8.X - 3.10.X supported (version 3.9 recommended, as that version has been used for the majority of TSExplorer's development process).

Step-by-step installation instructions (__Anaconda recommended__):
  1. Either clone the repository (https://github.com/SPEECHCOG/TSExplorer.git) or download and extract the ZIP package of the repository (https://github.com/SPEECHCOG/TSExplorer --> _Code_ --> _Download ZIP_)
  2. Go to the TSExplorer directory using the command `cd path_of_tsexplorer`, where _path_of_tsexplorer_ is the directory where TSExplorer is located.
  3. (_Optional for Anaconda users_) Create a Conda environment where you will install TSExplorer by running the command `conda create -n tsexplorer_env python=3.9`, where _tsexplorer_env_ is the name of the Conda environment.
  4. (_Optional for Anaconda users_) Activate the Conda environment by running the command `conda activate tsexplorer_env`, where _tsexplorer_env_ is the name of the Conda environment.
  5. Install TSExplorer using the command `pip install .` (note the period "." **which belongs** to the command).
  6. Verify that the installation succeeded using the command `tsexplorer --version`. After a successful installation, this command should print the current version of TSExplorer to the command line.

For cross-platform compatibility, TSExplorer uses _VLC Media Player_ to play audio and video. With VLC, common media player functions like play, pause, stop, and scrolling function normally. **If you need to use audio or video playback** with TSExplorer, you need to [install VLC](https://www.videolan.org/vlc/) before proceeding to use TSExplorer. Note that all the usage examples below require audio or video playback, i.e. installing VLC is required.


## Examples of how to use TSExplorer

You can either use the command
```
tsexplorer
```
or
```
tsexplorer --config-file <name_of_yml_configuration_file>
```
in order to run TSExplorer. Using the former of these options requires having a configuration file named _user_config.yml_ in the same directory as TSExplorer (this file is already provided together with the package). In the latter option, _<name_of_yml_configuration_file>_ is a _.yml_ configuration file containing the settings you want to use with TSExplorer. By default, the configuration file _user_config.yml_ uses the a simulated dataset of multi-sensor inertial measurement unit (IMU) data.

### Demo of multi-sensor IMU data with video

| ![An example screenshot of TSExplorer during the multi-sensor IMU data demo](figures/tsexplorer_imu_data_demo_example_image.png) |
|:--:|
| *Figure 2: An example screenshot of TSExplorer during the multi-sensor IMU data demo.* |

You can either use the command
```
tsexplorer
```
or
```
tsexplorer --config-file user_config.yml
```
in order to run a demo example of TSExplorer with randomly-generated multi-sensor IMU data (see Figure 2). This demo simulates the case of Figure 1, and it shows:
  * Randomly-generated data of four IMU sensors (one in each limb), each recording both tri-axial gyroscope and accelerometer data.
  * A scatter plot visualizing randomly-generated 160-dimensional data in 2D. Each sample corresponds to approximately 2.3 seconds of IMU data.
  * A video widget (showing a randomly-generated sequence of a circle bouncing around).

This demo contains a 5-minute sequence of simulated IMU data (sampling rate of 52 Hz), split into 120-sample frames (approximately 2.3 seconds each) with an overlap of 50% (60 samples). This leads to a demo dataset of 260 frames (samples) altogether.

When letting TSExplorer select samples for you (i.e. either pressing the "next sample" button or the _Enter_ key), this demo uses the farthest-first traversal (FAFT) algorithm. In the demo, the FAFT indices have been computed from the 2D t-SNE features using the Euclidean distance.

Except for the MP4 video, all the data is stored into _.npy_ data matrices. See the configuration file _user_config.yml_ for further details.


### Demo 1 of audio data (audio data in a single _.npy_ file)

| ![An example screenshot of TSExplorer during the audio data demo 1](figures/tsexplorer_audio_data_demo_single_npy_example_image.png) |
|:--:|
| *Figure 3: An example screenshot of TSExplorer during the first audio data demo (Demo 1).* |

You can use the command
```
tsexplorer --config-file user_config_audio.yml
```
in order to run a demo example of TSExplorer with randomly-generated audio data (Figure 3). This demo simulates annotating audio data, and it shows:
  * A scatter plot visualizing randomly-generated 128-dimensional data in 2D. Each sample corresponds to an audio sample with a duration varying between 0.5 and 1.0 seconds.
  * An audio widget (playing randomly-generated audio samples).

This demo contains a dataset of 200 randomly-generated audio samples with a duration varying between 0.5 and 1.0 seconds. When letting TSExplorer select samples for you (i.e. either pressing the "next sample" button or the _Enter_ key), this demo uses random sampling, i.e. the next sample is selected at random. The audio WAV files are stored into a single _.npy_ object file, and the rest of the data are stored into _.npy_ data matrices. See the configuration file _user_config_audio.yml_ for further details.


### Demo 2 of audio data (audio data as separate _.wav_ files)

| ![An example screenshot of TSExplorer during the audio data demo 2](figures/tsexplorer_audio_data_demo_separate_wav_example_image.png) |
|:--:|
| *Figure 4: An example screenshot of TSExplorer during the second audio data demo (Demo 2).* |

You can use the command
```
tsexplorer --config-file user_config_audio_separate_files.yml
```
in order to run a demo example of TSExplorer with randomly-generated audio data (Figure 4). This demo simulates annotating audio data, and it shows:
  * A scatter plot visualizing randomly-generated 128-dimensional data in 2D. Each sample corresponds to an audio sample with a duration varying between 0.5 and 1.0 seconds.
  * An audio widget (playing randomly-generated audio samples).

This demo contains a small subset (four samples) of the 200-sample audio described above. This time, the audio data are stored as separate _.wav_ files in a separate folder. The demo shows:
  * A scatter plot visualizing randomly-generated 128-dimensional data in 2D, each sample corresponding to an audio file with a duration between 0.5 and 1.0 seconds.
  * A visualization of two-channel audio data. Note that in the demo, the visualization for "Channel A" displays the actual sample, whereas the visualization for "Channel B" contains a random audio sample. These channel-wise samples are stored as separate _.npy_ files in separate folders.
  * A log-mel visualization of audio data. In the demo, this is a visualization for the actual audio sample, i.e. the sample shown in the "Channel A" visualization. The log-mel features are stored as separate _.npy_ files in a separate folder.
  * An audio widget (playing randomly-generated audio sample from "Channel A").

When letting TSExplorer select samples for you (i.e. either pressing the "next sample" button or the _Enter_ key), this demo uses the ordered selector, i.e. the next sample is selected from the ordered list based on the file names/indices. See the configuration file _user_config_audio_separate_files.yml_ for further details.

**Note that** when using TSExplorer with separate files in some given folder, the sample indices created by TSExplorer correspond to the lexicographical order of the file names. This means that e.g. if we have two files named _11_sample.wav_ and _2_sample.wav_, the file _11_sample.wav_ will have index 0 and the other file _2_sample.wav_ will have index 1.

**Also note that**, for demonstration purposes, this demo does not use pre-computed .npy files for the 2D visualizations. Instead, it computes the t-SNE, PCA, and UMAP 2D visualizations "on-the-fly":
  1. When first using a given visualization algorithm (t-SNE/PCA/UMAP), TSExplorer computes the 2D visualization and saves it as a .npy file.
  2. Later on, if TSExplorer needs to use the same visualization algorithm, it loads the pre-computed .npy file.

This approach is fine with smaller datasets, but with larger datasets it is **highly recommended** to pre-compute the t-SNE, PCA, and UMAP 2D visualizations before running TSExplorer to reduce computational overhead (see the _data_ directory regarding file naming conventions).


## TSExplorer user manual

**Note: A list of TSExplorer properties and how to use TSExplorer will be added to this repository soon!**


## Uninstalling TSExplorer

### Anaconda users

Anaconda users can uninstall TSExplorer using the following commands:
  1. `conda deactivate` (if Conda environment is not deactivated yet)
  2. `conda remove --name tsexplorer_env --all` (given that the name of the Conda environment was _tsexplorer_env_)

### Non-Anaconda users

If you installed TSExplorer without Anaconda, you can uninstall it using the following command:
```
pip uninstall tsexplorer
```

