## BpodAcademy: A user-interface to control multiple instances of Bpod

BpodAcademy is a python package that provides a Tkinter based GUI to control multiple instances of the Bpod control software (Matlab-based, see [https://github.com/sanworks/Bpod_Gen2](https://github.com/sanworks/Bpod_Gen2)). BpodAcademy can also be run *remotely* -- users can run Bpod protocols on multiple Bpod devices from home!

### Design

Each instance of the Matlab-based Bpod software is controlled from python using [Mathwork's Matlab Engine for Python](https://www.mathworks.com/help/matlab/matlab-engine-for-python.html). For each Bpod device, BpodAcademy opens a *Bpod Process Manager* that organizes the Matlab engine associated with the Bpod device and directly calls the Matlab Bpod control software.

When BpodAcademy is first opened, a *Bpod Academy Server* is started, which waits for commands (e.g. add/remove Bpod devices, start Bpod device, run a protocol, etc.) from client or remote BpodAcademy instances. BpodAcademy communicates with the *Bpod Academy Server* via [zeromq](https://zeromq.org/), allowing control of your Bpod devices from anywhere on your network -- all you need is the IP address of your BpodAcademy computer and the port used for communication (by default, port = 5555). Communication with the *Bpod Academy Server* is bidirectional, so all remote instances of BpodAcademy will stay in sync.

BpodAcademy saves your system configuration (device names and serial numbers) in a .csv file located in your local Bpod directory. Additionally, BpodAcademy saves logs of the commands from BpodAcademy and Matlab output from Bpod control software for each Bpod device.

### Requirements

- Matlab w/ Bpod software ([gkane26/Bpod_Gen2](http://github.com/gkane26/Bpod_Gen2))
  - Only tested Matlab R2020a, but should work with Matlab > R2014b
- Python 3: Perferably using [Anaconda](https://www.anaconda.com/products/individual) or a virtual environment

### Installation (terminal commands)

#### 1. Recommended: set up a new conda environment or virtual environment:

```
### conda ###
conda create -n bpod python
conda activate bpod

### virtual environment ###
python3 -m venv bpod
source bpod/bin/activate
pip install --upgrade pip
```

#### 2. (Server Only) Install the MATLAB Engine for Python. Instructions from Mathworks [here](https://www.mathworks.com/help/matlab/matlab_external/install-the-matlab-engine-for-python.html).

- Find the path to your Matlab directory (or _<MATLAB_PATH>_). It's most likely:
  - Windows: C:/Program Files/MATLAB/_<MATLAB_VERSION>_
  - Mac: /Applications/MATLAB\__<MATLAB_VERSION>_.app
  - Linux: /usr/local/MATLAB/_<MATLAB_VESION>_
- Navigate to the MATLAB Engine for Python API package, within your _<MATLAB_PATH>_:

```
cd *<MATLAB_PATH>*/extern/engines/python
```

- Install the MATLAB Engine for Python API package:

```
python setup.py install
```

NOTE :: on Linux, you will have to use the `sudo` command. This means you have specify the full path to python. For example, if installing in a conda environment:

```
sudo <path_to_anaconda>/envs/<environment_name>/python setup.py install
```

Specifically for the example above:

```
sudo ~/anaconda3/envs/bpod/bin/python setup.py install
```

#### 3. Install BpodAcademy

```
pip install git+https://github.com/gkane26/BpodAcademy
```

#### 4. Run BpodAcademy

To start BpodAcademy on your local control computer (to start the server):"
```
bpodacademy
```

To start BpodAcademy remotely:
```
bpodacademy --remote
```

### Instructions

BpodAcademy saves a configuration of box IDs (given by the user) and serial number for the Teensy/Arduino in the Bpod device into a .csv file located in your local Bpod directory (the directory containing your protocols and data, referred to as BPOD_DIR). This file, located at BPOD_DIR/Academy/AcademyConfig.csv, can be created/edited manually or created using BpodAcademy.

To get started using BpodAcademy, select `Bpod` --> `Add Bpod` from the menu at the top of the window, and assign a box ID and serial number for each of the Bpod devices connected to this computer. For each Bpod, you must first select 'Start Bpod' to open a new instance of Matlab and start Bpod with the serial port that matches the specified serial number.

By default, the Bpod Console GUI will not be shown. To use the Bpod Console for this Bpod, select `Show GUI`. After selecting `Show GUI`, you can select the same button, now labeled `Hide GUI` to hide it.

To calibrate solenoid valves, select `Calibrate`, which will open the Bpod Calibration GUI for that Bpod. The options to Show/Hide the Bpod Console and to run the Bpod Calibration GUI only exist when running BpodAcademy on the server computer -- these features cannot be used remotely.

To run a protocol, select the desired protocol, subject, and settings file from the drop down menu, then select `Run Protocol`. Protocols can be manually stopped by selecting `Stop Protocol`.

The protocol, subject, and settings file menus are populated similar to how they are populated using the Bpod Console Launch Manager: Protocols are read from the BPOD_DIR/Protocols directory, only subjects that have been registered with a particular protocol are shown, and only settings files that have been registered with a particular subject and protocol will be shown.

- If the protocols have changed since you opened BpodAcademy, select `Protocols` --> `Refresh Protocols` from the menu.
- New subjects can be registered with protocols by selecting `Subject` --> `Add Subject` from the menu.
- New settings files can be registered with different subject-protocol combinations. There are two options:
  - Copy an existing settings file to a new subject: `Settings` --> `Copy Existing`
  - Create an entirely new settings file (currently only supports scalar float variables): `Settings` --> `Create New`

### TODO

- [ ] Test BpodAcademy and [gkane26/Bpod_Gen2](http://github.com/gkane26/Bpod_Gen2) on Windows and Linux
- [ ] Support vectors and matrices when creating new settings files
- [ ] Log output from MATLAB Bpod protocols
