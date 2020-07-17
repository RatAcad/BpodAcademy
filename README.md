## BpodAcademy: A user-interface to control multiple instances of Bpod

### Requirements

- Linux or MacOS
- Matlab w/ Bpod software ([gkane26/Bpod_Gen2](http://github.com/gkane26/Bpod_Gen2))
- Python 3: Perferably using [Anaconda](https://www.anaconda.com/products/individual) or a virtual environment
- [Screen](https://www.gnu.org/software/screen/)
  - Ubuntu: `sudo apt install screen`
  - MacOS ([Homebrew](https://brew.sh/)): `brew install screen`

### Installation (terminal commands)

1. Recommended: set up a new conda environment or virtual environment:
```
### conda ###
conda create -n bpod python
conda activate bpod

### virtual environment ###
python3 -m venv bpod
source bpod/bin/activate
pip install --upgrade pip
```

2. Install BpodAcademy
```
pip install git+https://github.com/gkane26/BpodAcademy
```

3. Run BpodAcademy:
```
bpodacademy
```

### Instructions

BpodAcademy saves a configuration of box IDs and serial ports into a .csv file located in your local Bpod directory (the directory containing your protocols and data, referred to as BPOD_DIR). This file, located at BPOD_DIR/Academy/AcademyConfig.csv, can be created/edited manually or created using BpodAcademy.
  
To get started using BpodAcademy, select the `Add Box` button in the bottom left corner, and assign a box ID and serial port for each of the Bpod devices connected to this computer. For each Bpod, you must first select 'Start Bpod' to open a new instance of Matlab and start Bpod with the specified serial port.

By default, the Bpod Console GUI will not be shown. To use the Bpod Console for this Bpod, select `Show GUI`. After selecting `Show GUI`, you can select the same button, now labeled `Hide GUI` to hide it.

To calibrate solenoid valves, select `Calibratte`, which will open the Bpod Calibration GUI for that Bpod.

To run a protocol, select the desired protocol, subject, and settings file from the drop down menu, then select `Run Protocol`. Protocols can be manually stopped by selecting `Stop Protocol`.

The protocol, subject, and settings file menus are populated similar to how they are populated using the Bpod Console Launch Manager: Protocols are read from the BPOD_DIR/Protocols directory, only subjects that have been registered with a particular protocol are shown, and only settings files that have been registered with a particular subject and protocol will be shown. New subjects can be registered with protocols by selecting the `Add Subject` button in the bottom left corner. New settings files can be registered with different subject-protocol combinations by selecting the `Add Settings` button in the bottom left corner. Using the `Add Settings` button, an existing settings file can be copied from one subject-protocol combination to another, or you can create an entirely new settings file (new settings files are limited to float variables).

### TODO
- [ ] Refresh protocol list to add new protocols without closing BpodAcademy
- [ ] Check for execution of commands by checking log files
- [ ] Full installation instructions (particularly for Ubuntu)
- [ ] Test BpodAcademy and [gkane26/Bpod_Gen2]((http://github.com/gkane26/Bpod_Gen2) on Ubuntu and other Linux distributions
- [ ] Create executable using pyinstaller?
