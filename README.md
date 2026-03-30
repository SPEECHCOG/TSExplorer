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



## Examples of how to use TSExplorer

**Note: Simulated datasets and example configuration files to-be-used with these datasets will be soon added this repository!**

You can either use the command
```
tsexplorer
```
or
```
tsexplorer --config-file <name_of_yml_configuration_file>
```
in order to run TSExplorer. Using the former of these options requires having a configuration file named _user_config.yml_ in the same directory as TSExplorer (this file is already provided together with the package). In the latter option, _<name_of_yml_configuration_file>_ is a _.yml_ configuration file containing the settings you want to use with TSExplorer. By default, the configuration file _user_config.yml_ uses the a simulated dataset of audio data.


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

