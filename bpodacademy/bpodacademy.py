from tkinter import (
    Tk,
    Toplevel,
    Menu,
    messagebox,
    filedialog,
    Label,
    Entry,
    Button,
    StringVar,
)
from tkinter.ttk import Combobox
import os
from pathlib import Path
import shutil
import csv
import serial.tools.list_ports as list_ports
from scipy.io import savemat

from bpodacademy.process import BpodProcess


class BpodAcademy(Tk):

    ### Define constants used in GUI ###

    OFF_COLOR = "light salmon"
    READY_COLOR = "light goldenrod"
    ON_COLOR = "pale green"
    CHECK_PROTOCOL_SEC = 1

    ### Utility functions ###

    @staticmethod
    def _get_bpod_ports():

        com_ports = list_ports.comports()
        bpod_ports = [
            (p.serial_number, p.device)
            for p in com_ports
            if p.manufacturer is not None and "duino" in p.manufacturer
        ]
        return bpod_ports

    ### Object methods ###

    def __init__(self):

        Tk.__init__(self)

        ### find possible bpod ports ###
        self.bpod_ports = BpodAcademy._get_bpod_ports()

        ### load configuration file from bpod directory ###
        self.bpod_dir = os.getenv("BPOD_DIR")
        if self.bpod_dir is None:
            self._set_bpod_directory()
        self.cfg_file = Path(f"{self.bpod_dir}/Academy/AcademyConfig.csv")
        self._read_config()

        ### create log dir if it doesn't exist ###
        self.log_dir = Path(f"{self.bpod_dir}/Academy/logs")
        os.makedirs(self.log_dir, exist_ok=True)

        ### create window ###
        self.bpod_status = []
        self.bpod_process = []
        self.check_protocol = []
        self._create_window()

    def _set_bpod_directory(self):

        set_bpod_dir = messagebox.askokcancel(
            "Bpod Directory not found!",
            {
                "The evironmental variable BPOD_DIR has not been set. "
                "Please click ok to select the Bpod Directory or cancel to exit the program. "
                "Please set BPOD_DIR in ~/.bash_profile to avoid seeing this message in the future."
            },
            parent=self,
        )

        if set_bpod_dir:
            self.bpod_dir = filedialog.askdirectory(
                title="Please select local Bpod directory.", parent=self
            )

        if not self.bpod_dir:
            self.quit()

    def _load_protocols(self):

        # search protocol directory
        # return all protocols directories that contain a .m file of the same name
        protocols = []
        protocol_dir = Path(f"{self.bpod_dir}/Protocols")
        if protocol_dir.exists():
            candidates = [p for p in protocol_dir.iterdir() if p.is_dir()]
            protocols = [c.stem for c in candidates if (c / f"{c.stem}.m").is_file()]
        else:
            os.makedirs(protocol_dir)
        return protocols

    def _refresh_protocols(self):

        # fetch protocols and update protocol dropdown menus
        self.cfg["protocols"] = self._load_protocols()
        for i in range(self.n_bpods):
            self.protocol_entries[i]["values"] = self.cfg["protocols"]

    def _load_subjects(self, protocol):

        # return subject directories from the data directory
        # that contain a subfolder for the selected protocol
        subs_on_protocol = []
        data_dir = Path(f"{self.bpod_dir}/Data")
        if data_dir.exists():
            candidates = [d for d in data_dir.iterdir() if d.is_dir()]
            subs_on_protocol = [c.stem for c in candidates if (c / protocol).exists()]
        else:
            os.makedirs(data_dir)
        return subs_on_protocol

    def _load_settings(self, protocol, subject):

        # return settings files in Data/subject/protocol/Session Settings
        settings = []
        data_dir = Path(f"{self.bpod_dir}/Data")
        if data_dir.exists():
            sub_dir = data_dir / subject
            settings_dir = sub_dir / protocol / "Session Settings"
            settings = [s.stem for s in list(settings_dir.glob("*.mat"))]
        else:
            os.makedirs(data_dir)
        return settings

    def _read_config(self):

        ids = []
        ports = []

        if os.path.isfile(self.cfg_file):

            cfg_reader = csv.reader(open(self.cfg_file, newline=""))
            for i in cfg_reader:
                ids.append(i[0])
                ports.append(i[1])

        protocols = self._load_protocols()

        self.cfg = {"ids": ids, "ports": ports, "protocols": protocols}

    def _save_config(self):

        cfg_writer = csv.writer(open(self.cfg_file, "w", newline=""))
        for n, p in zip(self.cfg["ids"], self.cfg["ports"]):
            cfg_writer.writerow([n, p])

    def _change_port(self, event=None):

        for i in range(len(self.selected_ports)):
            self.cfg["ports"][i] = self.selected_ports[i].get()
        self._save_config()

    def _start_bpod(self, index):

        this_bpod = self.cfg["ids"][index]

        if self.bpod_status[index] != 0:

            messagebox.showwarning(
                "Bpod already started!",
                f"{this_bpod} has already been started. Please close it before restarting.",
                parent=self,
            )

        else:

            wait_dialog = Toplevel(self)
            wait_dialog.title("Starting Bpod")
            Label(wait_dialog, text="Please wait...").pack()
            wait_dialog.update()

            this_port = self.selected_ports[index].get()
            if this_port == "EMU":
                this_serial = "EMU"
            else:
                port_index = [p[0] == this_port for p in self.bpod_ports]
                port_index = port_index.index(True)
                this_serial = self.bpod_ports[port_index][1]

            self.bpod_process[index] = BpodProcess(this_bpod, this_serial, self.log_dir)

            code = self.bpod_process[index].start()

            wait_dialog.destroy()

            if code:
                self.bpod_status[index] = 1
                self.box_labels[index]["bg"] = BpodAcademy.READY_COLOR
            else:
                messagebox.showerror(
                    "Bpod Error!",
                    f"There was an error trying to start {this_bpod}",
                    parent=self,
                )

            ### check for calibration file ###
            this_calibration_file = Path(
                f"{self.bpod_dir}/Calibration Files/LiquidCalibration_{this_bpod}.mat"
            )
            if not this_calibration_file.exists():
                messagebox.showwarning(
                    "No Calibration File",
                    f"Calibration file for Bpod {this_bpod} does not exist! Make sure to calibrate valves before running a protocol.",
                    parent=self,
                )

    def _switch_bpod_gui(self, index):

        this_bpod = self.cfg["ids"][index]

        if self.bpod_status[index] == 0:

            messagebox.showwarning(
                "Bpod not started!",
                f"{this_bpod} has not been started. Please start Bpod before showing the GUI.",
                parent=self,
            )

        elif self.bpod_status[index] == 2:

            messagebox.showwarning(
                "Protocol running",
                f"A protocol is currently running on {this_bpod}. The Bpod Console cannot be displayed/hidden while a protocol is running.",
                parent=self,
            )

        else:

            code = self.bpod_process[index].send_command(("GUI",))

            if code == ("GUI", True):
                self.switch_gui_buttons[index]["text"] = (
                    "Hide GUI"
                    if self.switch_gui_buttons[index]["text"] == "Show GUI"
                    else "Show GUI"
                )
            else:
                messagebox.showerror(
                    "Bpod Console Error!",
                    f"There was an error trying to display/hide the Bpod Console for {this_bpod}.",
                    parent=self,
                )

    def _calibrate_bpod(self, index):

        this_bpod = self.cfg["ids"][index]

        if self.bpod_status[index] == 0:

            messagebox.showwarning(
                "Bpod not started!",
                f"{this_bpod} has not been started. Please start before calibrating.",
                parent=self,
            )

        elif self.bpod_status[index] == 2:

            messagebox.showwarning(
                "Protocol in progress!",
                f"A protocol is currently running on {this_bpod}. You cannot calibrate while a protocol is in session",
                parent=self,
            )

        else:

            code = self.bpod_process[index].send_command(("CALIBRATE",))

            if code != ("CALIBRATE", True):
                messagebox.showerror(
                    "Calibration Error!",
                    f"There was an error trying to display the Calibration window for {this_bpod}",
                    parent=self,
                )

    def _run_bpod_protocol(self, index):

        this_bpod = self.cfg["ids"][index]

        if self.bpod_status[index] == 0:

            messagebox.showwarning(
                "Bpod not started!",
                f"{this_bpod} has not been started. Please start before running a protocol.",
            )

        elif self.bpod_status[index] == 2:

            messagebox.showwarning(
                "Protocol in progress!",
                f"A protocol is currently running on {this_bpod}. Please stop this protocol and then restart.",
                parent=self,
            )

        else:

            this_protocol = self.selected_protocols[index].get()
            this_subject = self.selected_subjects[index].get()
            this_settings = self.selected_settings[index].get()

            if (not this_protocol) or (not this_subject):

                messagebox.showerror(
                    "Protocol Not Started!",
                    f"Protocol on {this_bpod} was not started: make sure to select a protocol and subject!",
                    parent=self,
                )

            else:

                this_settings = this_settings if this_settings else "DefaultSettings"

                code = self.bpod_process[index].send_command(
                    ("RUN", this_protocol, this_subject, this_settings)
                )

                if code[0] == "RUN":
                    if code[1] > 0:
                        self.check_protocol[index] = self.after(
                            BpodAcademy.CHECK_PROTOCOL_SEC * 1000,
                            lambda: self._check_running_protocol(index),
                        )
                        self.bpod_status[index] = 2
                        self.box_labels[index]["bg"] = BpodAcademy.ON_COLOR
                    else:
                        messagebox.showwarning(
                            "Protocol did not start!",
                            f"Protocol failed to start on {this_bpod}! Please check the log for error messages.",
                            parent=self,
                        )

    def _check_running_protocol(self, index):

        code = self.bpod_process[index].send_command(("QUERY",))

        if code == ("QUERY", True):

            self.check_protocol[index] = self.after(
                BpodAcademy.CHECK_PROTOCOL_SEC * 1000,
                lambda: self._check_running_protocol(index),
            )

        else:

            self._stop_bpod_protocol(index)
            messagebox.showwarning(
                "Protocol Ended!",
                f"The protocol running on {self.cfg['ids'][index]} ended!",
                parent=self,
            )

    def _stop_bpod_protocol(self, index):

        this_bpod = self.cfg["ids"][index]

        if self.bpod_status[index] != 2:

            messagebox.showwarning(
                "Protocol not running!",
                f"A protocol is not currently running on {this_bpod}.",
                parent=self,
            )

        else:

            self.after_cancel(self.check_protocol[index])
            code = self.bpod_process[index].send_command(("STOP",))

            if code[0] == "STOP":
                if code[1] >= 0:
                    self.bpod_status[index] = 1
                    self.box_labels[index]["bg"] = BpodAcademy.READY_COLOR
                else:
                    messagebox.showwarning(
                        "Protocol still runnning!",
                        f"Failed to stop protocol on {this_bpod}, please try again in a few seconds.",
                        parent=self,
                    )

    def _end_bpod(self, index):

        this_bpod = self.cfg["ids"][index]

        if self.bpod_status[index] == 2:

            messagebox.showwarning(
                "Protocol in progress!",
                f"A protocol is currently running on {this_bpod}. Please stop the protocol if you wish to close this Bpod.",
                parent=self,
            )

        elif self.bpod_status[index] == 1:

            wait_dialog = Toplevel(self)
            wait_dialog.title("Closing Bpod")
            Label(wait_dialog, text="Please wait...").pack()
            wait_dialog.update()

            # end bpod
            code = self.bpod_process[index].send_command(("END",))

            wait_dialog.destroy()

            if code == ("END", True):
                self.bpod_status[index] = 0
                self.box_labels[index]["bg"] = BpodAcademy.OFF_COLOR
            else:
                messagebox.showwarning(
                    "Bpod Still Open!",
                    f"{this_bpod} was not successfully closed.",
                    parent=self,
                )

    def _add_box(self, id, port, index, new_box_window=None):

        self.n_bpods += 1

        if new_box_window is not None:
            new_box_window.destroy()
            self.cfg["ids"].append(id)
            self.cfg["ports"].append(port)
            self._save_config()

        self.bpod_status.append(0)
        self.bpod_process.append(None)
        self.check_protocol.append(None)

        ### row 1: select port for box, add start button ###

        self.box_labels.append(Label(self, text=id, bg=BpodAcademy.OFF_COLOR))
        self.box_labels[index].grid(sticky="w", row=self.cur_row, column=self.cur_col)

        self.selected_ports.append(StringVar(self, value=port))
        self.port_entries.append(
            Combobox(
                self,
                textvariable=self.selected_ports[index],
                values=[p[0] for p in self.bpod_ports] + ["EMU"],
                width=self.combobox_width,
            )
        )
        self.port_entries[index].bind("<<ComboboxSelected>>", self._change_port)
        self.port_entries[index].grid(
            sticky="nsew", row=self.cur_row, column=self.cur_col + 1
        )

        self.start_buttons.append(
            Button(self, text="Start Bpod", command=lambda: self._start_bpod(index))
        )
        self.start_buttons[index].grid(
            sticky="nsew", row=self.cur_row, column=self.cur_col + 2
        )

        self.cur_row += 1

        ### create protocol, subject and settings labels/entries ###

        self.selected_protocols.append(StringVar(self))
        self.selected_subjects.append(StringVar(self))
        self.selected_settings.append(StringVar(self))

        protocol_label = Label(self, text="Protocol: ")
        self.protocol_entries.append(
            Combobox(
                self,
                textvariable=self.selected_protocols[index],
                values=self.cfg["protocols"],
                state="readonly",
                width=self.combobox_width,
            )
        )

        subject_label = Label(self, text="Subject: ")
        self.subject_entries.append(
            Combobox(
                self,
                textvariable=self.selected_subjects[index],
                state="readonly",
                width=self.combobox_width,
            )
        )

        settings_label = Label(self, text="Settings: ")
        self.settings_entries.append(
            Combobox(
                self,
                textvariable=self.selected_settings[index],
                state="readonly",
                width=self.combobox_width,
            )
        )

        def update_subject_list(event=None):
            self.subject_entries[index]["values"] = self._load_subjects(
                self.protocol_entries[index].get()
            )
            self.selected_subjects[index].set("")

        self.protocol_entries[index].bind("<<ComboboxSelected>>", update_subject_list)

        def update_settings_list(event=None):
            self.settings_entries[index]["values"] = self._load_settings(
                self.protocol_entries[index].get(), self.subject_entries[index].get()
            )
            self.selected_settings[index].set("")

        self.subject_entries[index].bind("<<ComboboxSelected>>", update_settings_list)

        ### row 2: protocol, switch gui button, run protocol button ###

        protocol_label.grid(sticky="w", row=self.cur_row, column=self.cur_col)
        self.protocol_entries[index].grid(
            sticky="nsew", row=self.cur_row, column=self.cur_col + 1
        )

        self.switch_gui_buttons.append(
            Button(self, text="Show GUI", command=lambda: self._switch_bpod_gui(index))
        )
        self.switch_gui_buttons[index].grid(
            sticky="nsew", row=self.cur_row, column=self.cur_col + 2
        )

        self.run_protocol_buttons.append(
            Button(
                self,
                text="Run Protocol",
                command=lambda: self._run_bpod_protocol(index),
            )
        )
        self.run_protocol_buttons[index].grid(
            sticky="nsew", row=self.cur_row, column=self.cur_col + 3
        )

        self.cur_row += 1

        ### row 3: subject, calibrate button, stop protocol button ###

        subject_label.grid(sticky="w", row=self.cur_row, column=self.cur_col)
        self.subject_entries[index].grid(
            sticky="nsew", row=self.cur_row, column=self.cur_col + 1
        )

        self.calib_gui_buttons.append(
            Button(self, text="Calibrate", command=lambda: self._calibrate_bpod(index))
        )
        self.calib_gui_buttons[index].grid(
            sticky="nsew", row=self.cur_row, column=self.cur_col + 2
        )

        self.stop_protocol_buttons.append(
            Button(
                self,
                text="Stop Protocol",
                command=lambda: self._stop_bpod_protocol(index),
            )
        )
        self.stop_protocol_buttons[index].grid(
            sticky="nsew", row=self.cur_row, column=self.cur_col + 3
        )

        self.cur_row += 1

        ### row 4: settings, end button ###

        settings_label.grid(sticky="w", row=self.cur_row, column=self.cur_col)
        self.settings_entries[index].grid(
            sticky="nsew", row=self.cur_row, column=self.cur_col + 1
        )

        self.end_buttons.append(
            Button(self, text="End Bpod", command=lambda: self._end_bpod(index))
        )
        self.end_buttons[index].grid(
            sticky="nsew", row=self.cur_row, column=self.cur_col + 2
        )

        self.cur_row += 1

        ### empty row ###

        Label(self).grid(row=self.cur_row, column=self.cur_col)
        self.cur_row += 1

    def _add_new_box(self):

        new_box_window = Toplevel(self)
        new_box_window.title("Add New Bpod")

        new_id = StringVar(new_box_window)
        Label(new_box_window, text="Box ID: ").grid(sticky="w", row=0, column=0)
        Entry(new_box_window, textvariable=new_id).grid(sticky="nsew", row=0, column=1)

        new_port = StringVar(new_box_window)
        Label(new_box_window, text="Serial Port: ").grid(sticky="w", row=1, column=0)
        Combobox(
            new_box_window,
            textvariable=new_port,
            values=[p[0] for p in self.bpod_ports] + ["EMU"],
        ).grid(sticky="nsew", row=1, column=1)

        Button(
            new_box_window,
            text="Submit",
            command=lambda: self._add_box(
                new_id.get(), new_port.get(), len(self.bpod_status), new_box_window
            ),
        ).grid(sticky="nsew", row=3, column=1)
        Button(new_box_window, text="Cancel", command=new_box_window.destroy).grid(
            sticky="nsew", row=4, column=1
        )

    def _add_new_subject(self, protocol, subject, window=None):

        if window is not None:
            window.destroy()

        sub_dir = Path(f"{self.bpod_dir}/Data/{subject}")
        sub_data_dir = sub_dir / protocol / "Session Data"
        sub_settings_dir = sub_dir / protocol / "Session Settings"
        sub_data_dir.mkdir(parents=True, exist_ok=True)
        sub_settings_dir.mkdir(parents=True, exist_ok=True)

        def_settings_file = sub_settings_dir / "DefaultSettings.mat"
        savemat(def_settings_file, {"ProtocolSettings": {}})

    def _add_new_subject_window(self):

        new_sub_window = Toplevel(self)
        new_sub_window.title("Add New Subject")

        Label(new_sub_window, text="Protocol: ").grid(sticky="w", row=0, column=0)
        new_sub_protocol = StringVar(new_sub_window)
        Combobox(
            new_sub_window,
            textvariable=new_sub_protocol,
            values=self.cfg["protocols"],
            state="readonly",
            width=self.combobox_width,
        ).grid(sticky="nsew", row=0, column=1)

        Label(new_sub_window, text="Subject: ").grid(sticky="w", row=1, column=0)
        new_sub_name = StringVar(new_sub_window)
        Entry(new_sub_window, textvariable=new_sub_name).grid(
            sticky="nsew", row=1, column=1
        )

        Button(
            new_sub_window,
            text="Submit",
            command=lambda: self._add_new_subject(
                new_sub_protocol.get(), new_sub_name.get(), new_sub_window
            ),
        ).grid(sticky="nsew", row=2, column=1)
        Button(new_sub_window, text="Cancel", command=new_sub_window.destroy).grid(
            sticky="nsew", row=3, column=1
        )

        new_sub_window.mainloop()

    def _copy_settings(
        self,
        from_protocol,
        from_subject,
        from_settings,
        to_protocol,
        to_subject,
        window,
    ):

        if window is not None:
            window.destroy()

        copy_from = Path(
            f"{self.bpod_dir}/Data/{from_subject}/{from_protocol}/Session Settings/{from_settings}.mat"
        )
        copy_to = Path(
            f"{self.bpod_dir}/Data/{to_subject}/{to_protocol}/Session Settings/{from_settings}.mat"
        )

        ### check that copy_from exists
        if not copy_from.is_file():
            messagebox.showerror(
                "File Does Not Exist!",
                f"The settings file {copy_from.stem} for subject {from_subject} and protocol {from_protocol} does not exist!",
                parent=self,
            )
            return

        ### if copy_to exists, ask if user wants to overwrite
        if copy_to.is_file():
            if not messagebox.askokcancel(
                "File Exists!",
                f"The settings file {copy_to.stem} for subject {to_subject} and protocol {to_protocol} already exists. Would you like to overwrite it?",
            ):
                return

        shutil.copy(copy_from, copy_to)

    def _copy_settings_window(self, window=None):

        if window is not None:
            window.destroy()

        copy_settings_window = Toplevel(self)
        copy_settings_window.title("Copy Settings File")

        ### Select settings to copy from ###
        Label(copy_settings_window, text="Copy From").grid(sticky="w", row=0, column=0)

        Label(copy_settings_window, text="Protocol: ").grid(sticky="w", row=1, column=0)
        copy_from_protocol = StringVar(copy_settings_window)
        copy_from_protocol_entry = Combobox(
            copy_settings_window,
            textvariable=copy_from_protocol,
            values=self.cfg["protocols"],
            state="readonly",
            width=self.combobox_width,
        )

        def update_copy_from_sub(event=None):
            copy_from_subject_entry["values"] = self._load_subjects(
                copy_from_protocol.get()
            )
            copy_from_subject.set("")

        copy_from_protocol_entry.bind("<<ComboboxSelected>>", update_copy_from_sub)
        copy_from_protocol_entry.grid(sticky="nsew", row=1, column=1)

        Label(copy_settings_window, text="Subject: ").grid(sticky="w", row=2, column=0)
        copy_from_subject = StringVar(copy_settings_window)
        copy_from_subject_entry = Combobox(
            copy_settings_window,
            textvariable=copy_from_subject,
            state="readonly",
            width=self.combobox_width,
        )

        def update_copy_from_settings(event=None):
            copy_from_settings_entry["values"] = self._load_settings(
                copy_from_protocol.get(), copy_from_subject.get()
            )
            copy_from_settings.set("")

        copy_from_subject_entry.bind("<<ComboboxSelected>>", update_copy_from_settings)
        copy_from_subject_entry.grid(sticky="nsew", row=2, column=1)

        Label(copy_settings_window, text="Settings: ").grid(sticky="w", row=3, column=0)
        copy_from_settings = StringVar(copy_settings_window)
        copy_from_settings_entry = Combobox(
            copy_settings_window,
            textvariable=copy_from_settings,
            state="readonly",
            width=self.combobox_width,
        )
        copy_from_settings_entry.grid(sticky="w", row=3, column=1)

        ### Empty row ###
        Label(copy_settings_window).grid(row=4, column=0)

        ### Select location to copy to ###
        Label(copy_settings_window, text="Copy To").grid(sticky="w", row=5, column=0)

        Label(copy_settings_window, text="Protocol: ").grid(sticky="w", row=6, column=0)
        copy_to_protocol = StringVar(copy_settings_window)
        copy_to_protocol_entry = Combobox(
            copy_settings_window,
            textvariable=copy_to_protocol,
            values=self.cfg["protocols"],
            state="readonly",
            width=self.combobox_width,
        )

        def update_copy_to_subject(event=None):
            copy_to_subject_entry["values"] = self._load_subjects(
                copy_to_protocol.get()
            )
            copy_to_subject.set("")

        copy_to_protocol_entry.bind("<<ComboboxSelected>>", update_copy_to_subject)
        copy_to_protocol_entry.grid(sticky="nsew", row=6, column=1)

        Label(copy_settings_window, text="Subject: ").grid(sticky="w", row=7, column=0)
        copy_to_subject = StringVar(copy_settings_window)
        copy_to_subject_entry = Combobox(
            copy_settings_window,
            textvariable=copy_to_subject,
            state="readonly",
            width=self.combobox_width,
        )
        copy_to_subject_entry.grid(sticky="nsew", row=7, column=1)

        ### Emtpy row ###
        Label(copy_settings_window).grid(row=8, column=0)

        ### Submit/Close buttons ###
        Button(
            copy_settings_window,
            text="Submit",
            command=lambda: self._copy_settings(
                copy_from_protocol.get(),
                copy_from_subject.get(),
                copy_from_settings.get(),
                copy_to_protocol.get(),
                copy_to_subject.get(),
                copy_settings_window,
            ),
        ).grid(sticky="nsew", row=9, column=1)
        Button(
            copy_settings_window, text="Cancel", command=copy_settings_window.destroy
        ).grid(sticky="nsew", row=10, column=1)

    def _create_settings_file(
        self, protocol, subject, settings_file, names, values, window=None
    ):

        if window is not None:
            window.destroy()

        ### check if file exists, if so ask to overwrite ###
        full_file = Path(
            f"{self.bpod_dir}/Data/{subject}/{protocol}/Session Settings/{settings_file}.mat"
        )
        if full_file.is_file():
            if not messagebox.showwarning(
                "File Exists!",
                f"The settings file {settings_file} for subject {subject} and protocol {protocol} already exists. Do you want to overwrite it?",
                parent=self,
            ):
                return

        ### create dictionary from user settings ###
        settings_dict = {}
        for n, v in zip(names, values):
            if (n.get()) and (v.get()):
                settings_dict[n.get()] = float(v.get())

        ### write dictionary to mat file ###
        savemat(full_file, {"ProtocolSettings": settings_dict})

    def _create_settings_window(self, window=None):

        if window is not None:
            window.destroy()

        create_settings_window = Toplevel(self)
        create_settings_window.title("Create Settings File")

        Label(create_settings_window, text="Protocol: ").grid(
            sticky="w", row=0, column=0
        )
        settings_protocol = StringVar(create_settings_window)
        settings_protocol_entry = Combobox(
            create_settings_window,
            textvariable=settings_protocol,
            values=self.cfg["protocols"],
            state="readonly",
            width=self.combobox_width,
        )

        def update_settings_subject(event=None):
            settings_subject_entry["values"] = self._load_subjects(
                settings_protocol.get()
            )
            settings_subject.set("")

        settings_protocol_entry.bind("<<ComboboxSelected>>", update_settings_subject)
        settings_protocol_entry.grid(row=0, column=1)

        Label(create_settings_window, text="Subject: ").grid(
            sticky="w", row=1, column=0
        )
        settings_subject = StringVar(create_settings_window)
        settings_subject_entry = Combobox(
            create_settings_window,
            textvariable=settings_subject,
            state="readonly",
            width=self.combobox_width,
        )
        settings_subject_entry.grid(sticky="nsew", row=1, column=1)

        Label(create_settings_window, text="Settings: ").grid(
            sticky="w", row=2, column=0
        )
        settings_file = StringVar(create_settings_window)
        Entry(
            create_settings_window,
            textvariable=settings_file,
            width=self.combobox_width,
        ).grid(sticky="nsew", row=2, column=1)

        Label(create_settings_window).grid(row=3, column=0)

        Label(create_settings_window, text="Names").grid(row=4, column=0)
        Label(create_settings_window, text="Values").grid(row=4, column=1)

        settings_names = []
        settings_values = []

        def add_settings_field():
            settings_names.append(StringVar(create_settings_window))
            Entry(
                create_settings_window,
                textvariable=settings_names[-1],
                width=self.combobox_width,
            ).grid(row=4 + len(settings_names), column=0)
            settings_values.append(StringVar(create_settings_window))
            Entry(
                create_settings_window,
                textvariable=settings_values[-1],
                width=self.combobox_width,
            ).grid(row=4 + len(settings_values), column=1)

        add_settings_field()
        Button(
            create_settings_window, text="Add Parameter", command=add_settings_field
        ).grid(sticky="nsew", row=100, column=0)

        Label(create_settings_window).grid(row=101, column=0)

        Button(
            create_settings_window,
            text="Create File",
            command=lambda: self._create_settings_file(
                settings_protocol.get(),
                settings_subject.get(),
                settings_file.get(),
                settings_names,
                settings_values,
                create_settings_window,
            ),
        ).grid(sticky="nsew", row=102, column=0)
        Button(
            create_settings_window,
            text="Cancel",
            command=create_settings_window.destroy,
        ).grid(sticky="nsew", row=102, column=1)

        create_settings_window.mainloop()

    def _add_new_settings_window(self):

        new_settings_window = Toplevel(self)
        new_settings_window.title("New Settings File")

        Button(
            new_settings_window,
            text="Copy from another subject",
            command=lambda: self._copy_settings_window(new_settings_window),
        ).grid(sticky="nsew", row=0, column=0)
        Button(
            new_settings_window,
            text="Create new settings file",
            command=lambda: self._create_settings_window(new_settings_window),
        ).grid(sticky="nsew", row=1, column=0)
        Button(
            new_settings_window, text="Cancel", command=new_settings_window.destroy
        ).grid(sticky="nsew", row=3, column=0)
        new_settings_window.mainloop()

    def _close_bpod_academy(self):

        ### check for running sessions ###
        if any([status == 2 for status in self.bpod_status]):
            messagebox.showwarning(
                "Bpod protocol(s) are currently running. Please close open protocols before exiting BpodAcademy.",
                parent=self,
            )
        else:

            ### ask user to confirm closing ###
            if messagebox.askokcancel(
                "Close Bpod?",
                "Are you sure you want to close BpodAcademy? Any open Bpod devices will be closed.",
            ):

                closing_window = Toplevel(self)
                closing_window.title("Closing Bpods")
                Label(closing_window, text="Closing open Bpods. Please wait...").pack()
                closing_window.update()

                ### Close open Bpods ###
                for i in range(self.n_bpods):
                    if self.bpod_status[i] > 0:
                        self._end_bpod(i)

                closing_window.destroy()

                ### close BpodAcademy ###
                self.quit()

    def _delete_logs(self):

        [log_file.unlink() for log_file in self.log_dir.iterdir()]
        messagebox.showinfo(
            "Logs Deleted",
            "Log files have been deleted. New logs will be created when you start Bpods.",
            parent=self,
        )

    def _create_window(self):

        self.title("Bpod Academy")
        self.cur_row = 0
        self.cur_col = 0
        self.combobox_width = 15

        self.n_bpods = 0

        self.selected_ports = []
        self.selected_subjects = []
        self.selected_protocols = []
        self.selected_settings = []

        self.box_labels = []
        self.port_entries = []
        self.protocol_entries = []
        self.subject_entries = []
        self.settings_entries = []

        self.start_buttons = []
        self.switch_gui_buttons = []
        self.calib_gui_buttons = []
        self.run_protocol_buttons = []
        self.stop_protocol_buttons = []
        self.end_buttons = []

        ### create menu at top

        menubar = Menu(self)

        bpod_menu = Menu(menubar, tearoff=0)
        bpod_menu.add_command(label="Add Bpod", command=self._add_new_box)
        menubar.add_cascade(label="Bpod", menu=bpod_menu)

        protocol_menu = Menu(menubar, tearoff=0)
        protocol_menu.add_command(
            label="Refresh Protocols", command=self._refresh_protocols
        )
        menubar.add_cascade(label="Protocols", menu=protocol_menu)

        subject_menu = Menu(menubar, tearoff=0)
        subject_menu.add_command(
            label="Add Subject", command=self._add_new_subject_window
        )
        menubar.add_cascade(label="Subjects", menu=subject_menu)

        settings_menu = Menu(menubar, tearoff=0)
        settings_menu.add_command(
            label="Copy Existing", command=self._copy_settings_window
        )
        settings_menu.add_command(
            label="Create New", command=self._create_settings_window
        )
        menubar.add_cascade(label="Settings", menu=settings_menu)

        logs_menu = Menu(menubar, tearoff=0)
        logs_menu.add_command(label="Delete Logs", command=self._delete_logs)
        menubar.add_cascade(label="Logs", menu=logs_menu)

        self.config(menu=menubar)

        for i in range(len(self.cfg["ids"])):

            self._add_box(self.cfg["ids"][i], self.cfg["ports"][i], i)

            if self.n_bpods % 5 == 0:
                Label(self, width=5).grid(row=0, column=self.cur_col + 4)
                self.cur_col += 5
                self.cur_row = 0

        self.cur_row += 1

        self.protocol("WM_DELETE_WINDOW", self._close_bpod_academy)


def main():
    bpodacademy = BpodAcademy()
    bpodacademy.mainloop()


if __name__ == "__main__":
    main()
