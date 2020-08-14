from tkinter import (
    Tk,
    Toplevel,
    Menu,
    messagebox,
    filedialog,
    simpledialog,
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
import ipaddress
import zmq

from bpodacademy.exception import BpodAcademyError
from bpodacademy.server import BpodAcademyServer
from bpodacademy.frame import BpodFrame


class BpodAcademy(Tk):

    ### Define constants used in GUI ###

    OFF_COLOR = "light salmon"
    READY_COLOR = "light goldenrod"
    ON_COLOR = "pale green"
    GRID_WIDTH = 15
    FRAMES_PER_COLUMN = 5
    INTER_COLUMN_WIDTH = 3

    ZMQ_CLIENT_RECV_TIMEO_MS = 10000
    ZMQ_SUBSCRIBE_WAIT_MS = 10
    ZMQ_SUBSCRIBE_FREQUENCY_MS = 100

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

    def __init__(self, remote=False, ip="*", port=5555):

        Tk.__init__(self)
        self.remote = remote
        self.ip = ip if ip is not "*" else "localhost"
        self.port = port

        ### if not remote, start server ###
        if not self.remote:

            # load configuration file from bpod directory
            self.bpod_dir = os.getenv("BPOD_DIR")
            if self.bpod_dir is None:
                self._set_bpod_directory()

            # start server
            self.server = BpodAcademyServer(self.bpod_dir, ip, port)
            self.server.start()

            # start sockets
            self._connect_remote_to_server()

        else:
            self._connect_remote_to_server_window()


        # create window
        self._create_window()

        # start reading server commands
        self.listen_to_server = self.after(
            BpodAcademy.ZMQ_SUBSCRIBE_FREQUENCY_MS, self._listen_to_server
        )

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

    def _connect_remote_to_server(self, ip=None, port=None, window=None):

        self.ip = ip if ip is not None else self.ip
        self.port = port if port is not None else self.port

        # create 2 sockets:
        # request: submits requests to server
        # subscribe: receives commands from server

        context = zmq.Context()

        self.request = context.socket(zmq.REQ)
        self.request.connect(f"tcp://{self.ip}:{self.port}")
        self.subscribe = context.socket(zmq.SUB)
        self.subscribe.setsockopt(zmq.RCVTIMEO, BpodAcademy.ZMQ_SUBSCRIBE_WAIT_MS)
        self.subscribe.subscribe("")
        self.subscribe.connect(f"tcp://{self.ip}:{self.port+1}")

        # look for connection
        reply = self._remote_to_server(("CONFIG",))

        if not reply:
            self._disconnect_remote()
            if window:
                messagebox.showerror(
                    "Remote Not Connected",
                    f"Remote failed to connect to server! Please ensure the ip address and port are correct and that the server is online.",
                    parent=self,
                )
            else:
                self._connect_remote_to_server_window()
        else:
            self.cfg = reply
            if window is not None:
                window.destroy()
                if type(window) is Tk:
                    window.quit()

    def _disconnect_remote(self):

        self.request.close()
        self.request = None
        self.subscribe.close()
        self.subscribe = None

    def _connect_remote_to_server_window(self):

        connect_window = Tk()
        connect_window.title("Connect to BpodAcademy")

        ip_entry = StringVar(connect_window, value=self.ip)
        Label(connect_window, text="IP Address:").grid(sticky="w", row=0, column=0)
        Entry(connect_window, textvariable=ip_entry, width=BpodAcademy.GRID_WIDTH).grid(
            sticky="nsew", row=0, column=1
        )

        port_entry = StringVar(connect_window, value=self.port)
        Label(connect_window, text="Port:").grid(sticky="w", row=1, column=0)
        Entry(
            connect_window, textvariable=port_entry, width=BpodAcademy.GRID_WIDTH
        ).grid(sticky="nsew", row=1, column=1)

        Button(
            connect_window,
            text="Connect",
            command=lambda: self._connect_remote_to_server(
                ip_entry.get(), int(port_entry.get()), connect_window
            ),
        ).grid(sticky="nsew", row=2, column=1)

        Button(connect_window, text="Close", command=connect_window.quit).grid(
            sticky="nsew", row=3, column=1
        )

        connect_window.mainloop()

    def _create_window(self):

        if not self.remote:
            self.title("Bpod Academy")
        else:
            self.title("Bpod Academy (Remote)")

        # create menu at top

        menubar = Menu(self)

        bpod_menu = Menu(menubar, tearoff=0)
        bpod_menu.add_command(label="Add Bpod", command=self._add_box_window)
        bpod_menu.add_command(label="Remove Bpod", command=self._remove_box_window)
        menubar.add_cascade(label="Bpod", menu=bpod_menu)

        protocol_menu = Menu(menubar, tearoff=0)
        protocol_menu.add_command(
            label="Refresh Protocols", command=self._refresh_protocols_command
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
        logs_menu.add_command(label="Delete Logs", command=self._delete_logs_command)
        menubar.add_cascade(label="Logs", menu=logs_menu)

        self.config(menu=menubar)

        # create bpod frames for each box

        self.bpod_frames = []

        Label(self).grid(row=0, column=0)

        for i in range(len(self.cfg["bpod_ids"])):

            self._add_box(self.cfg["bpod_ids"][i], self.cfg["serial_numbers"][i])

        self.protocol("WM_DELETE_WINDOW", self._close_bpod_academy)

    def _add_box(self, bpod_id, bpod_serial):

        status = self._remote_to_server(("QUERY", bpod_id))

        self.bpod_frames.append(
            BpodFrame(
                bpod_id,
                bpod_serial,
                status=status,
                request_socket=self.request,
                subscribe_socket=self.subscribe,
                parent=self,
                remote=self.remote,
            )
        )

        index = len(self.bpod_frames) - 1
        row = 2 * (1 + (index % BpodAcademy.FRAMES_PER_COLUMN)) - 1
        col = 2 * int(index / BpodAcademy.FRAMES_PER_COLUMN)

        if (index > 0) and (index % BpodAcademy.FRAMES_PER_COLUMN == 0):
            Label(self, width=BpodAcademy.INTER_COLUMN_WIDTH).grid(
                row=0, column=(2 * int(index / 5) - 1)
            )
        self.bpod_frames[index].grid(row=row, column=col)
        Label(self).grid(row=row + 1, column=col)

    def _add_box_window(self):

        new_box_window = Toplevel(self)
        new_box_window.title("Add New Bpod")

        new_id = StringVar(new_box_window)
        Label(new_box_window, text="Box ID: ").grid(sticky="w", row=0, column=0)
        Entry(new_box_window, textvariable=new_id).grid(sticky="nsew", row=0, column=1)

        new_port = StringVar(new_box_window)
        all_ports = self._remote_to_server(("PORTS",))
        Label(new_box_window, text="Serial Port: ").grid(sticky="w", row=1, column=0)
        Combobox(
            new_box_window,
            textvariable=new_port,
            values=[p[0] for p in all_ports] + ["EMU"],
        ).grid(sticky="nsew", row=1, column=1)

        Button(
            new_box_window,
            text="Submit",
            command=lambda: self._add_box_command(
                new_id.get(), new_port.get(), new_box_window
            ),
        ).grid(sticky="nsew", row=3, column=1)
        Button(new_box_window, text="Cancel", command=new_box_window.destroy).grid(
            sticky="nsew", row=4, column=1
        )

    def _add_box_command(self, bpod_id, bpod_serial, window=None):

        reply = self._remote_to_server(("BPOD", "ADD", bpod_id, bpod_serial))
        if not reply:
            messagebox.showerror(
                "Add Bpod Failed!",
                f"Failed to add new box {bpod_id} with serial number {bpod_serial}. Please check if {bpod_id} already exists.",
                parent=self,
            )

        if window is not None:
            window.destroy()

    def _remove_box_window(self):

        remove_box_window = Toplevel(self)
        remove_box_window.title("Remove Bpod")

        id_to_remove = StringVar(remove_box_window)
        Label(remove_box_window, text="Box ID: ").grid(sticky="w", row=0, column=0)
        Combobox(
            remove_box_window,
            textvariable=id_to_remove,
            values=self.cfg["bpod_ids"],
            state="readonly",
        ).grid(sticky="nsew", row=0, column=1)

        Button(
            remove_box_window,
            text="Remove",
            command=lambda: self._remove_box_command(
                id_to_remove.get(), remove_box_window
            ),
        ).grid(sticky="nsew", row=1, column=1)
        Button(
            remove_box_window, text="Cancel", command=remove_box_window.destroy
        ).grid(sticky="nsew", row=2, column=1)

    def _remove_box_command(self, bpod_id, window=None):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)

        if self.bpod_frames[bpod_index].status == 2:

            messagebox.showwarning(
                "Protocol Running!",
                f"Cannot remove Bpod while a protocol is running. Please stop the protocol and close {bpod_id}, then remove it.",
                parent=self,
            )

        elif self.bpod_frames[bpod_index].status == 1:

            messagebox.showwarning(
                "Bpod On!",
                f"Cannot remove Bpod while it is active. Please close {bpod_id} before removing it.",
                parent=self,
            )

        else:

            remove = messagebox.askokcancel(
                "Remove Box?", f"Are you sure you want to remove {bpod_id}?"
            )

            if remove:

                reply = self._remote_to_server(("BPOD", "REMOVE", bpod_id))

                if not reply:
                    messagebox.showerror(
                        "Failed to remove bpod!",
                        f"Could not remove {bpod_id}. Please try again or double check server connnections.",
                    )

                # box_index = self.cfg["ids"].index(bpod_id)
                # self.cfg["ids"].pop(box_index)
                # self.cfg["ports"].pop(box_index)
                # self.bpod_status.pop(box_index)
                # self.bpod_process.pop(box_index)
                # self.check_protocol.pop(box_index)

            if window:
                window.destroy()

    def _remove_box(self, bpod_id):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        self.cfg["bpod_ids"].pop(bpod_index)
        self.cfg["serial_numbers"].pop(bpod_index)
        self.bpod_frames[bpod_index].destroy()
        self.bpod_frames.pop(bpod_index)
        self._redraw_grid()

    def _redraw_grid(self):

        for i in range(len(self.bpod_frames)):

            self.bpod_frames[i].grid_forget()

            row = 2 * (1 + (i % BpodAcademy.FRAMES_PER_COLUMN)) - 1
            column = 2 * int(i / BpodAcademy.FRAMES_PER_COLUMN)

            self.bpod_frames[i].grid(row=row, column=column)

    def _refresh_protocols_command(self):

        reply = self._remote_to_server(("PROTOCOLS", "REFRESH"))
        if not reply:
            messagebox.showwarning(
                "Refresh Protocols Failed!",
                "Failed to refresh protocols, please check server connections!",
                parent=self,
            )

    def _refresh_protocols(self, protocols):

        for i in range(len(self.bpod_frames)):
            self.bpod_frames[i].set_protocols(protocols)

    def _add_new_subject_window(self):

        new_sub_window = Toplevel(self)
        new_sub_window.title("Add New Subject")

        protocols = self._remote_to_server(("PROTOCOLS",))

        Label(new_sub_window, text="Protocol: ").grid(sticky="w", row=0, column=0)
        new_sub_protocol = StringVar(new_sub_window)
        Combobox(
            new_sub_window,
            textvariable=new_sub_protocol,
            values=protocols,
            state="readonly",
            width=BpodAcademy.GRID_WIDTH,
        ).grid(sticky="nsew", row=0, column=1)

        Label(new_sub_window, text="Subject: ").grid(sticky="w", row=1, column=0)
        new_sub_name = StringVar(new_sub_window)
        Entry(new_sub_window, textvariable=new_sub_name).grid(
            sticky="nsew", row=1, column=1
        )

        Button(
            new_sub_window,
            text="Submit",
            command=lambda: self._add_new_subject_command(
                new_sub_protocol.get(), new_sub_name.get(), new_sub_window
            ),
        ).grid(sticky="nsew", row=2, column=1)
        Button(new_sub_window, text="Cancel", command=new_sub_window.destroy).grid(
            sticky="nsew", row=3, column=1
        )

    def _add_new_subject_command(self, protocol, subject, window=None):

        reply = self._remote_to_server(("SUBJECTS", "ADD", protocol, subject))
        if not reply:
            messagebox.showwarning(
                "Add Subject Failed",
                f"Failed to add subject {subject} on protocol {protocol}. Please check server connection!",
                parent=self,
            )
        else:
            messagebox.showinfo(
                "Subject Added",
                f"Subject {subject} added to protocol {protocol}. Please (re)select the protocol from the dropdown menu to update the subject list.",
                parent=self,
            )

        if window is not None:
            window.destroy()

    def _copy_settings_window(self):

        copy_settings_window = Toplevel(self)
        copy_settings_window.title("Copy Settings File")

        ### Select settings to copy from ###
        Label(copy_settings_window, text="Copy From").grid(sticky="w", row=0, column=0)

        protocols = self._remote_to_server(("PROTOCOLS",))
        Label(copy_settings_window, text="Protocol: ").grid(sticky="w", row=1, column=0)
        copy_from_protocol = StringVar(copy_settings_window)
        copy_from_protocol_entry = Combobox(
            copy_settings_window,
            textvariable=copy_from_protocol,
            values=protocols,
            state="readonly",
            width=BpodAcademy.GRID_WIDTH,
        )

        def update_copy_from_sub(event=None):
            copy_from_subject_entry["values"] = self._remote_to_server(
                ("SUBJECTS", "FETCH", copy_from_protocol.get())
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
            width=BpodAcademy.GRID_WIDTH,
        )

        def update_copy_from_settings(event=None):
            copy_from_settings_entry["values"] = self._remote_to_server(
                ("SETTINGS", "FETCH", copy_from_protocol.get(), copy_from_subject.get())
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
            width=BpodAcademy.GRID_WIDTH,
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
            values=protocols,
            state="readonly",
            width=BpodAcademy.GRID_WIDTH,
        )

        def update_copy_to_subject(event=None):
            copy_to_subject_entry["values"] = self._remote_to_server(
                ("SUBJECTS", "FETCH", copy_to_protocol.get())
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
            width=BpodAcademy.GRID_WIDTH,
        )
        copy_to_subject_entry.grid(sticky="nsew", row=7, column=1)

        ### Emtpy row ###
        Label(copy_settings_window).grid(row=8, column=0)

        ### Submit/Close buttons ###
        Button(
            copy_settings_window,
            text="Submit",
            command=lambda: self._copy_settings_command(
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

    def _copy_settings_command(
        self,
        copy_from_protocol,
        copy_from_subject,
        copy_from_settings,
        copy_to_protocol,
        copy_to_subject,
        window=None,
    ):

        reply = self._remote_to_server(
            (
                "SETTINGS",
                "COPY",
                copy_from_protocol,
                copy_from_subject,
                copy_from_settings,
                copy_to_protocol,
                copy_to_subject,
            )
        )
        if not reply:
            messagebox.showwarning(
                "Failed to copy settings",
                f"Failed to copy settings {copy_from_settings} from protocol {copy_from_protocol} and subject {copy_from_subject} to protocol {copy_to_protocol} and subject {copy_to_subject}",
                parent=self,
            )

        if window is not None:
            window.destroy()

    def _create_settings_window(self, window=None):

        if window is not None:
            window.destroy()

        create_settings_window = Toplevel(self)
        create_settings_window.title("Create Settings File")

        protocols = self._remote_to_server(("PROTOCOLS",))
        Label(create_settings_window, text="Protocol: ").grid(
            sticky="w", row=0, column=0
        )
        settings_protocol = StringVar(create_settings_window)
        settings_protocol_entry = Combobox(
            create_settings_window,
            textvariable=settings_protocol,
            values=protocols,
            state="readonly",
            width=BpodAcademy.GRID_WIDTH,
        )

        def update_settings_subject(event=None):
            settings_subject_entry["values"] = self._remote_to_server(
                ("SUBJECTS", "FETCH", settings_protocol.get())
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
            width=BpodAcademy.GRID_WIDTH,
        )
        settings_subject_entry.grid(sticky="nsew", row=1, column=1)

        Label(create_settings_window, text="Settings: ").grid(
            sticky="w", row=2, column=0
        )
        settings_file = StringVar(create_settings_window)
        Entry(
            create_settings_window,
            textvariable=settings_file,
            width=BpodAcademy.GRID_WIDTH,
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
                width=BpodAcademy.GRID_WIDTH,
            ).grid(row=4 + len(settings_names), column=0)
            settings_values.append(StringVar(create_settings_window))
            Entry(
                create_settings_window,
                textvariable=settings_values[-1],
                width=BpodAcademy.GRID_WIDTH,
            ).grid(row=4 + len(settings_values), column=1)

        add_settings_field()
        Button(
            create_settings_window, text="Add Parameter", command=add_settings_field
        ).grid(sticky="nsew", row=100, column=0)

        Label(create_settings_window).grid(row=101, column=0)

        Button(
            create_settings_window,
            text="Create File",
            command=lambda: self._create_settings_command(
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

    def _create_settings_command(
        self, protocol, subject, settings_file, names, values, window=None
    ):

        # create dictionary from user settings
        settings_dict = {}
        for n, v in zip(names, values):
            if (n.get()) and (v.get()):
                settings_dict[n.get()] = float(v.get())

        reply = self._remote_to_server(
            ("SETTINGS", "CREATE", protocol, subject, settings_file, settings_dict)
        )
        if not reply:
            messagebox.showwarning(
                "Failed to create settings file",
                f"Could not create settings file {settings_file} for subject {subject} on protocol {protocol}. Please check server connections.",
                parent=self,
            )

        if window is not None:
            window.destroy()

    def _delete_logs_command(self):

        delete_logs = messagebox.askokcancel(
            "Delete Logs?",
            "Are you sure you want to delete all of the logs?",
            parent=self,
        )
        if delete_logs:
            reply = self._remote_to_server(("LOGS", "DELETE"))
            if not reply:
                messagebox.showwarning(
                    "Failed to delete logs",
                    "Failed to delete the logs. Please check server connections!",
                )
            else:
                messagebox.showinfo(
                    "Logs Deleted",
                    "Log files have been deleted. New logs will be created when you start Bpods.",
                    parent=self,
                )

    def _change_port(self, bpod_id, bpod_serial):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        self.cfg["serial_numbers"][bpod_index] = bpod_serial
        self.bpod_frames[bpod_index].serial_number.set(bpod_serial)

    def _start_bpod(self, bpod_id, code):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        self.bpod_frames[bpod_index].start_bpod(code)

    def _end_bpod(self, bpod_id):
        
        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        self.bpod_frames[bpod_index].end_bpod()

    def _start_bpod_protocol(self, bpod_id, protocol, subject, settings):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        self.bpod_frames[bpod_index].start_bpod_protocol(protocol, subject, settings)

    def _stop_bpod_protocol(self, bpod_id):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        self.bpod_frames[bpod_index].stop_bpod_protocol()

    def _listen_to_server(self):

        try:
            cmd = self.subscribe.recv_pyobj()
        except zmq.Again:
            cmd = None

        if cmd is not None:

            if cmd[0] == "BPOD":
                
                if cmd[1] == "ADD":

                    bpod_id = cmd[2]
                    bpod_serial = cmd[3]
                    self.cfg["bpod_ids"].append(bpod_id)
                    self.cfg["serial_numbers"].append(bpod_serial)
                    self._add_box(bpod_id, bpod_serial)

                elif cmd[1] == "REMOVE":

                    bpod_id = cmd[2]
                    self._remove_box(bpod_id)

                elif cmd[1] == "CHANGE_PORT":

                    bpod_id = cmd[2]
                    bpod_serial = cmd[3]
                    self._change_port(bpod_id, bpod_serial)

            elif cmd[0] == "PROTOCOLS":

                protocols = cmd[1]
                self._refresh_protocols(protocols)

            elif cmd[0] == "START":

                bpod_id = cmd[1]
                code = cmd[2]
                self._start_bpod(bpod_id, code)

            elif cmd[0] == "RUN":

                bpod_id = cmd[1]
                protocol = cmd[2]
                subject = cmd[3]
                settings = cmd[4]
                self._start_bpod_protocol(bpod_id, protocol, subject, settings)

            elif cmd[0] == "STOP":

                bpod_id = cmd[1]
                self._stop_bpod_protocol(bpod_id)

            elif cmd[0] == "END":

                bpod_id = cmd[1]
                self._end_bpod(bpod_id)

        self.listen_to_server = self.after(
            BpodAcademy.ZMQ_SUBSCRIBE_FREQUENCY_MS, self._listen_to_server
        )

    def _remote_to_server(self, msg):

        if self.request is not None:

            self.request.send_pyobj(msg)

            try:
                reply = self.request.recv_pyobj()
            except zmq.Again:
                reply = None

            return reply

    def _close_bpod_academy(self):

        self.after_cancel(self.listen_to_server)

        if self.remote:

            self.request.close()
            self.subscribe.close()

            self.quit()

        else:

            ### check for running sessions ###
            if any([fr.status == 2 for fr in self.bpod_frames]):
                messagebox.showwarning(
                    "Bpod protocol(s) are currently running. Please close open protocols before exiting BpodAcademy.",
                    parent=self,
                )
            else:

                ### ask user to confirm closing ###
                if messagebox.askokcancel(
                    "Close Bpod?",
                    "Are you sure you want to close BpodAcademy? Any open Bpod devices will be closed.",
                    parent=self,
                ):

                    closing_window = Toplevel(self)
                    closing_window.title("Closing Bpods")
                    Label(closing_window, text="Closing open Bpods. Please wait...").pack()
                    closing_window.update()

                    ### Close open Bpods ###
                    for i in range(len(self.bpod_frames)):
                        if self.bpod_frames[i].status > 0:
                            self.bpod_frames[i]._end_bpod()

                    closing_window.destroy()

                    ### close BpodAcademy ###
                    self.quit()

def main():

    import argparse
    parser = argparse.ArgumentParser()
    parser.add_argument('-r', '--remote', action="store_true")
    parser.add_argument('-i', '--ip', type=str, default='*')
    parser.add_argument('-p', '--port', type=int, default=5555)
    args = parser.parse_args()

    bpodacademy = BpodAcademy(remote=args.remote, ip=args.ip, port=args.port)
    bpodacademy.mainloop()


if __name__ == "__main__":
    main()
