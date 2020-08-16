import tkinter as tk
from tkinter import ttk
import os
import zmq

import serial.tools.list_ports as list_ports

from bpodacademy import BpodAcademyError


class BpodFrame(tk.Frame):

    ### Define constants used in GUI ###

    OFF_COLOR = "light salmon"
    READY_COLOR = "light goldenrod"
    ON_COLOR = "pale green"
    GRID_WIDTH = 15
    CHECK_PROTOCOL_MS = 1000
    CHECK_SERVER_COMMANDS_MS = 1000
    ZMQ_REQUEST_RCVTIMEO_MS = 30000

    def __init__(
        self,
        bpod_id,
        serial_number,
        status=(0,),
        request_socket=None,
        subscribe_socket=None,
        ip=None,
        port=None,
        parent=None,
        remote=False,
    ):

        tk.Frame.__init__(self, parent)

        self.bpod_id = bpod_id
        self.serial_number = tk.StringVar(self, value=serial_number)
        self.status = status[0]
        if self.status == 2:
            self.protocol_details = (status[1], status[2], status[3])
            self.check_protocol = self.after(
                BpodFrame.CHECK_PROTOCOL_MS, self._check_running_protocol
            )
        else:
            self.protocol_details = (None, None, None)

        self.remote = remote

        if (request_socket is None) or (subscribe_socket is None):

            if (ip is None) or (port is None):
                raise BpodAcademyError(
                    "No server communication! Must specify either request and subscribe socket OR ip and port to create sockets."
                )
            else:
                context = zmq.Context()
                self.request = context.socket(zmq.REQ)
                self.request.connect(f"tcp://{ip}:{port}")
                self.subscribe = context.socket(zmq.SUB)
                self.subscribe.connect(f"tcp://{ip}:{port+1}")
        else:
            self.request = request_socket
            self.subscribe = subscribe_socket

        self.bpod_ports = self._get_bpod_ports()

        self.create_frame()

    def _get_bpod_ports(self):

        reply = self._remote_to_server(("PORTS",))
        if reply is None:
            self._no_server_message("PORTS")

        return reply

    def _remote_to_server(self, msg, timeout=ZMQ_REQUEST_RCVTIMEO_MS):

        if self.request is not None:

            self.request.setsockopt(zmq.RCVTIMEO, timeout)
            self.request.send_pyobj(msg)

            try:
                reply = self.request.recv_pyobj()
            except zmq.Again:
                reply = None

            return reply

    def _no_server_message(self, cmd):

        tk.messagebox.showerror(
            "Failed Communication!",
            f"The server failed to respond to the cmd {cmd}.",
            parent=self,
        )

    def _get_protocols(self):

        protocols = self._remote_to_server(("PROTOCOLS",))
        if not protocols:
            self._no_server_message("PROTOCOLS")

        return protocols

    def set_protocols(self, protocols):

        self.protocol_entry["values"] = protocols

    def _update_subject_list(self, event=None):

        these_subs = self._remote_to_server(("SUBJECTS", "FETCH", self.protocol.get()))
        if these_subs:
            self.subject_entry["values"] = these_subs
            self.subject.set("")
        else:
            self._no_server_message(("SUBJECTS", "FETCH"))

    def _update_settings_list(self, event=None):

        these_settings = self._remote_to_server(
            ("SETTINGS", "FETCH", self.protocol.get(), self.subject.get())
        )
        if these_settings:
            if "DefaultSettings" not in these_settings:
                these_settings.append("DefaultSettings")
            self.settings_entry["values"] = these_settings
            self.settings.set("")
        else:
            self._no_server_message("SETTINGS")

    def create_frame(self):

        ### row 0: select port for box, add start button ###

        if self.status == 0:
            label_color = BpodFrame.OFF_COLOR
            serial_selection_state = "readonly"
            protocol_selection_state = "readonly"
        elif self.status == 1:
            label_color = BpodFrame.READY_COLOR
            serial_selection_state = "disabled"
            protocol_selection_state = "readonly"
        elif self.status == 2:
            label_color = BpodFrame.ON_COLOR
            serial_selection_state = "disabled"
            protocol_selection_state = "disabled"

        self.box_label = tk.Label(self, text=self.bpod_id, bg=label_color)
        self.box_label.grid(sticky="w", row=0, column=0)

        self.serial_entry = ttk.Combobox(
            self,
            textvariable=self.serial_number,
            values=[p[0] for p in self.bpod_ports] + ["EMU"],
            state=serial_selection_state,
            width=BpodFrame.GRID_WIDTH,
        )

        self.serial_entry.bind("<<ComboboxSelected>>", self._change_port)
        self.serial_entry.grid(sticky="nsew", row=0, column=1)

        self.start_button = tk.Button(self, text="Start Bpod", command=self._start_bpod)
        self.start_button.grid(sticky="nsew", row=0, column=2)

        ### row 1: select protocol, switch gui, and start protocol

        self.protocol = tk.StringVar(self, value=self.protocol_details[0])
        protocol_label = tk.Label(self, text="Protocol: ")
        protocol_label.grid(sticky="w", row=1, column=0)

        self.protocol_entry = ttk.Combobox(
            self,
            textvariable=self.protocol,
            values=self._get_protocols(),
            state=protocol_selection_state,
            width=BpodFrame.GRID_WIDTH,
        )
        self.protocol_entry.bind("<<ComboboxSelected>>", self._update_subject_list)
        self.protocol_entry.grid(sticky="nsew", row=1, column=1)

        if not self.remote:
            self.switch_gui_button = tk.Button(
                self, text="Show GUI", command=self._switch_bpod_gui
            )
            self.switch_gui_button.grid(sticky="nsew", row=1, column=2)

        self.start_protocol_button = tk.Button(
            self, text="Run Protocol", command=self._start_bpod_protocol,
        )
        self.start_protocol_button.grid(
            sticky="nsew", row=1, column=2 + (not self.remote)
        )

        ### row 2: select subject, calibrate, stop protocol

        self.subject = tk.StringVar(self, value=self.protocol_details[1])
        subject_label = tk.Label(self, text="Subject: ")
        subject_label.grid(sticky="w", row=2, column=0)
        self.subject_entry = ttk.Combobox(
            self,
            textvariable=self.subject,
            state=protocol_selection_state,
            width=BpodFrame.GRID_WIDTH,
        )
        self.subject_entry.bind("<<ComboboxSelected>>", self._update_settings_list)
        self.subject_entry.grid(sticky="nsew", row=2, column=1)

        if not self.remote:
            self.calib_gui_button = tk.Button(
                self, text="Calibrate", command=self._calibrate_bpod
            )
            self.calib_gui_button.grid(sticky="nsew", row=2, column=2)

        self.stop_protocol_button = tk.Button(
            self, text="Stop Protocol", command=self._stop_bpod_protocol,
        )
        self.stop_protocol_button.grid(
            sticky="nsew", row=2, column=2 + (not self.remote)
        )

        ### row 3: select settings, end bpod

        self.settings = tk.StringVar(self, value=self.protocol_details[2])
        settings_label = tk.Label(self, text="Settings: ")
        settings_label.grid(sticky="w", row=3, column=0)
        self.settings_entry = ttk.Combobox(
            self,
            textvariable=self.settings,
            state=protocol_selection_state,
            width=BpodFrame.GRID_WIDTH,
        )
        self.settings_entry.grid(sticky="nsew", row=3, column=1)

        self.end_button = tk.Button(self, text="End Bpod", command=self._end_bpod)
        self.end_button.grid(sticky="nsew", row=3, column=2)

    def _change_port(self, event=None):

        if self.status == 0:

            reply = self._remote_to_server(
                ("BPOD", "CHANGE_PORT", self.bpod_id, self.serial_number.get())
            )
            if not reply:
                self._no_server_message("BPOD CHANGE_PORT")

        # else:

        #     cfg = self._remote_to_server(("CONFIG",))
        #     port_index = cfg["bpod_ids"].index(self.bpod_id)
        #     self.serial_number.set(cfg["bpod_serials"][port_index])

        #     tk.messagebox.showwarning("Bpod Active!", f"{self.bpod_id} is currently active. Please close the Bpod before changing the serial port.")

    def _start_bpod(self):

        if self.status != 0:

            tk.messagebox.showwarning(
                "Bpod already started!",
                f"{self.bpod_id} has already been started. Please close it before restarting.",
                parent=self,
            )

        else:

            wait_dialog = tk.Toplevel(self)
            wait_dialog.title("Starting Bpod")
            tk.Label(wait_dialog, text="Please wait...").pack()
            wait_dialog.update()

            reply = self._remote_to_server(("START", self.bpod_id))
            if reply is None:
                self._no_server_message("START")

            wait_dialog.destroy()

    def start_bpod(self, code):

        self.status = 1
        self.box_label["bg"] = BpodFrame.READY_COLOR
        self.serial_entry["state"] = "disabled"

        if code == 2:
            tk.messagebox.showwarning(
                "No Calibration File",
                f"{self.bpod_id} has been started, but its calibration file does not exist! Make sure to calibrate valves before running a protocol.",
                parent=self,
            )

    def _switch_bpod_gui(self):

        if self.status == 0:

            tk.messagebox.showwarning(
                "Bpod not started!",
                f"{self.bpod_id} has not been started. Please start Bpod before showing the GUI.",
                parent=self,
            )

        elif self.status == 2:

            tk.messagebox.showwarning(
                "Protocol running",
                f"A protocol is currently running on {self.bpod_id}. The Bpod Console cannot be displayed/hidden while a protocol is running.",
                parent=self,
            )

        else:

            reply = self._remote_to_server(("GUI", self.bpod_id))

            if reply is None:
                self._no_server_message("GUI")
            elif reply:
                self.switch_gui_button["text"] = (
                    "Hide GUI"
                    if self.switch_gui_button["text"] == "Show GUI"
                    else "Show GUI"
                )
            else:
                tk.messagebox.showerror(
                    "Bpod Console Error!",
                    f"There was an error trying to display/hide the Bpod Console for {self.bpod_id}.",
                    parent=self,
                )

    def _calibrate_bpod(self):

        if self.status == 0:

            tk.messagebox.showwarning(
                "Bpod not started!",
                f"{self.bpod_id} has not been started. Please start before calibrating.",
                parent=self,
            )

        elif self.status == 2:

            tk.messagebox.showwarning(
                "Protocol running",
                f"A protocol is currently running on {self.bpod_id}. The Calibration GUI cannot be used while a protocol is running.",
                parent=self,
            )

        else:

            reply = self._remote_to_server(("CALIBRATE", self.bpod_id))
            if reply is None:
                self._no_server_message("CALIBRATE")
            elif not reply:
                tk.messagebox.showerror(
                    "Calibration Error!",
                    f"There was an error trying to display the Calibration window for {self.bpod_id}",
                    parent=self,
                )

    def _start_bpod_protocol(self):

        if self.status == 0:

            tk.messagebox.showwarning(
                "Bpod not started!",
                f"{self.bpod_id} has not been started. Please start before running a protocol.",
            )

        elif self.status == 2:

            tk.messagebox.showwarning(
                "Protocol in progress!",
                f"A protocol is currently running on {self.bpod_id}. Please stop this protocol and then restart.",
                parent=self,
            )

        else:

            if (not self.protocol.get()) or (not self.subject.get()):

                tk.messagebox.showerror(
                    "Protocol Not Started!",
                    f"Protocol on {self.bpod_id} was not started: make sure to select a protocol and subject!",
                    parent=self,
                )

            else:

                reply = self._remote_to_server(
                    (
                        "RUN",
                        self.bpod_id,
                        self.protocol.get(),
                        self.subject.get(),
                        self.settings.get(),
                    )
                )

                if reply is None:
                    self._no_server_message("RUN")
                elif reply <= 0:
                    tk.messagebox.showwarning(
                        "Protocol did not start!",
                        f"Protocol failed to start on {self.bpod_id}! Please check the log for error messages.",
                        parent=self,
                    )

    def start_bpod_protocol(self, protocol, subject, settings):

        self.check_protocol = self.after(
            BpodFrame.CHECK_PROTOCOL_MS, self._check_running_protocol
        )
        self.status = 2
        self.box_label["bg"] = BpodFrame.ON_COLOR
        self.protocol.set(protocol)
        self.subject.set(subject)
        self.settings.set(settings)
        self.protocol_entry["state"] = "disabled"
        self.subject_entry["state"] = "disabled"
        self.settings_entry["state"] = "disabled"

    def _check_running_protocol(self):

        if self.status == 2:

            reply = self._remote_to_server(("QUERY", self.bpod_id))

            if reply is None:
                self._no_server_message("QUERY")
            else:
                status = reply[0]
                if status == 2:
                    self.check_protocol = self.after(
                        BpodFrame.CHECK_PROTOCOL_MS, self._check_running_protocol
                    )
                else:
                    self._stop_bpod_protocol()
                    tk.messagebox.showwarning(
                        "Protocol Ended!",
                        f"The protocol running on {self.bpod_id} ended!",
                        parent=self,
                    )

    def _stop_bpod_protocol(self):

        if self.status != 2:

            tk.messagebox.showwarning(
                "Protocol not running!",
                f"A protocol is not currently running on {self.bpod_id}.",
                parent=self,
            )

        else:

            reply = self._remote_to_server(("STOP", self.bpod_id))

            if reply is None:
                self._no_server_message("STOP")
            elif reply < 0:
                tk.messagebox.showwarning(
                    "Protocol still runnning!",
                    f"Failed to stop protocol on {self.bpod_id}, please try again in a few seconds.",
                    parent=self,
                )

    def stop_bpod_protocol(self):

        self.after_cancel(self.check_protocol)
        self.status = 1
        self.box_label["bg"] = BpodFrame.READY_COLOR
        self.protocol_entry["state"] = "readonly"
        self.subject_entry["state"] = "readonly"
        self.settings_entry["state"] = "readonly"

    def _end_bpod(self):

        if self.status == 2:

            tk.messagebox.showwarning(
                "Protocol in progress!",
                f"A protocol is currently running on {self.bpod_id}. Please stop the protocol if you wish to close this Bpod.",
                parent=self,
            )

        elif self.status == 1:

            reply = self._remote_to_server(("END", self.bpod_id))

            if reply is None:
                self._no_server_message("END")

    def end_bpod(self):

        self.status = 0
        self.box_label["bg"] = BpodFrame.OFF_COLOR
        self.serial_entry["state"] = "readonly"

