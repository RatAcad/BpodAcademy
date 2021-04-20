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
import platform
import shutil
import csv
from distutils.util import strtobool

# from typing import Protocol
from scipy.io import savemat
from multiprocess.pool import ThreadPool
import zmq

from bpodacademy.exception import BpodAcademyError

try:
    from bpodacademy.server import BpodAcademyServer
except ModuleNotFoundError:
    pass
from bpodacademy.frame import BpodFrame


class BpodAcademy(Tk):

    ### Define constants used in GUI ###

    GRID_WIDTH = 15
    FRAMES_PER_ROW = 3
    INTER_COLUMN_WIDTH = 3

    ZMQ_REQUEST_RCVTIMEO_MS = 30000
    ZMQ_CONNECT_TIMEO_MS = 1000
    ZMQ_SUBSCRIBE_RCVTIMEO_MS = 1
    ZMQ_SUBSCRIBE_FREQUENCY_MS = 100

    ### Object methods ###

    def __init__(self, remote=False, ip="*", port=5555):

        Tk.__init__(self)
        self.withdraw()

        self.remote = remote
        self.ip = ip if ip is not "*" else "localhost"
        self.port = port
        self.zmq_context = zmq.Context()

        ### if not remote, start server ###
        if not self.remote:

            # load configuration file from bpod directory
            self.bpod_dir = os.getenv("BPOD_DIR")
            if self.bpod_dir is None:
                self._set_bpod_directory()

            # check for server connection
            cfg = self._connect_remote_to_server(test=True)

            if not cfg:

                # start server
                self.server = BpodAcademyServer(self.bpod_dir, ip, port)
                self.server.start()

            # set window title
            self.title("Bpod Academy")
            self._connect_remote_to_server()

            cfg_file = Path(f"{self.bpod_dir}/Academy/AcademyConfig.csv")
            has_cfg = True
            if not cfg_file.is_file():
                has_cfg = False
            elif cfg_file.stat().st_size == 0:
                has_cfg = False
            if not has_cfg:
                begin_config = messagebox.askokcancel(
                    "No Config File!",
                    "Did not find a configuration file! Please click ok to begin configuring BpodAcademy or cancel to exit.",
                    parent=self,
                )
                if begin_config:
                    self._add_box_window()
                else:
                    self.quit()
                    self.destroy()
                    self.server.stop()
                    self.server.close()
                    return

        else:

            self.title("Bpod Academy (Remote)")
            self._connect_remote_to_server_window()

        if platform.system() == "Darwin":
            self.resizable(False, False)

        # create window
        if hasattr(self, "cfg"):
            self._create_window()

            # start reading server commands
            self.listen_to_server = self.after(
                BpodAcademy.ZMQ_SUBSCRIBE_FREQUENCY_MS, self._listen_to_server
            )

            self.deiconify()
            self.mainloop()

    def _set_bpod_directory(self):

        set_bpod_dir = messagebox.askokcancel(
            "Bpod Directory not found!",
            "The evironmental variable BPOD_DIR has not been set. "
            "Please click ok to select the Bpod Directory or cancel to exit the program. "
            "Please set BPOD_DIR in ~/.bash_profile to avoid seeing this message in the future.",
            parent=self,
        )

        if set_bpod_dir:
            self.bpod_dir = filedialog.askdirectory(
                title="Please select local Bpod directory.", parent=self
            )

        if not self.bpod_dir:
            self.quit()

    def _connect_remote_to_server(self, ip=None, port=None, window=None, test=False):

        self.ip = ip if ip is not None else self.ip
        self.port = port if port is not None else self.port

        # create 2 sockets:
        # request: submits requests to server
        # subscribe: receives commands from server

        self.request = self.zmq_context.socket(zmq.REQ)
        self.request.connect(f"tcp://{self.ip}:{self.port}")

        self.subscribe = self.zmq_context.socket(zmq.SUB)
        self.subscribe.setsockopt(zmq.RCVTIMEO, BpodAcademy.ZMQ_SUBSCRIBE_RCVTIMEO_MS)
        self.subscribe.subscribe("")
        self.subscribe.connect(f"tcp://{self.ip}:{self.port+1}")

        # look for connection
        reply = self._remote_to_server(("CONFIG", "ACADEMY"), timeout=1000)

        if test:
            return reply
        else:
            if not reply:
                # self._disconnect_remote()
                messagebox.showerror(
                    "Remote Not Connected",
                    f"Remote failed to connect to server! Please ensure the IP address and port are correct and that the server is online.",
                    parent=self,
                )
            else:
                self.cfg = reply
                if window is not None:
                    window.destroy()
                    window.quit()

    def _disconnect_remote(self):

        self.request.close()
        self.subscribe.close()

    def _connect_remote_to_server_window(self):

        connect_window = Toplevel(self)
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

        connect_window.protocol("WM_DELETE_WINDOW", connect_window.quit)

        connect_window.mainloop()

    def _create_window(self):

        # create menu at top

        menubar = Menu(self)

        bpod_menu = Menu(menubar, tearoff=0)
        bpod_menu.add_command(label="Add Bpod", command=self._add_box_window)
        bpod_menu.add_command(label="Remove Bpod", command=self._remove_box_window)
        bpod_menu.add_command(label="Start All Bpods", command=self._start_all_bpods)
        bpod_menu.add_command(label="Close All Bpods", command=self._close_all_bpods)
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

        camera_menu = Menu(menubar, tearoff=0)
        camera_menu.add_command(label="Refresh Cameras", command=self._refresh_cameras_command)
        menubar.add_cascade(label="Cameras", menu=camera_menu)

        logs_menu = Menu(menubar, tearoff=0)
        logs_menu.add_command(label="Delete Logs", command=self._delete_logs_command)
        menubar.add_cascade(label="Logs", menu=logs_menu)

        server_menu = Menu(menubar, tearoff=0)
        server_menu.add_command(label="Stop Server", command=self._close_server)
        menubar.add_cascade(label="Server", menu=server_menu)

        training_menu = Menu(menubar, tearoff=0)
        training_menu.add_command(
            label="Save Training Configuration", command=self._save_training_config
        )
        training_menu.add_command(
            label="Load Training Configuration", command=self._load_training_config
        )
        menubar.add_cascade(label="Training", menu=training_menu)

        self.config(menu=menubar)

        # create bpod frames for each box

        self.bpod_frames = []

        Label(self).grid(row=0, column=0)

        for i in range(len(self.cfg["bpod_ids"])):

            self._add_box(
                self.cfg["bpod_ids"][i],
                self.cfg["bpod_serials"][i],
                self.cfg["bpod_positions"][i],
            )

        self.protocol("WM_DELETE_WINDOW", self._close_bpod_academy)

    def _add_box(self, bpod_id, bpod_serial, position):

        status = self._remote_to_server(("BPOD", "QUERY", bpod_id))

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
        row = int(2 * position[0])
        col = int(2 * position[1])

        if col > 0:
            Label(self, width=BpodAcademy.INTER_COLUMN_WIDTH).grid(
                row=0, column=col - 1
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

        new_box_row = StringVar(new_box_window)
        Label(new_box_window, text="Row: ").grid(sticky="w", row=2, column=0)
        Combobox(
            new_box_window, textvariable=new_box_row, values=[0, 1, 2, 3, 4, 5]
        ).grid(sticky="nsew", row=2, column=1)

        new_box_col = StringVar(new_box_window)
        Label(new_box_window, text="Column: ").grid(sticky="w", row=3, column=0)
        Combobox(
            new_box_window, textvariable=new_box_col, values=[0, 1, 2, 3, 4, 5]
        ).grid(sticky="nsew", row=3, column=1)

        Button(
            new_box_window,
            text="Submit",
            command=lambda: self._add_box_command(
                new_id.get(),
                new_port.get(),
                (int(new_box_row.get()), int(new_box_col.get())),
                new_box_window,
            ),
        ).grid(sticky="nsew", row=4, column=1)
        Button(new_box_window, text="Cancel", command=new_box_window.destroy).grid(
            sticky="nsew", row=5, column=1
        )

    def _add_box_command(self, bpod_id, bpod_serial, bpod_position, window=None):

        reply = self._remote_to_server(
            ("BPOD", "ADD", bpod_id, bpod_serial, bpod_position)
        )
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

        if not bpod_id:
            return

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

            if window:
                window.destroy()

    def _remove_box(self, bpod_id):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        self.cfg["bpod_ids"].pop(bpod_index)
        self.cfg["bpod_serials"].pop(bpod_index)
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
            copy_to_subject_entry["values"] = ["All"] + self._remote_to_server(
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
        Label(create_settings_window, text="Data Types").grid(row=4, column=2)

        settings_names = []
        settings_values = []
        settings_dtypes = []

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
            settings_dtypes.append(StringVar(create_settings_window))
            Combobox(
                create_settings_window,
                textvariable=settings_dtypes[-1],
                values=["int", "float", "bool", "string"],
                width=BpodAcademy.GRID_WIDTH,
            ).grid(row=4 + len(settings_dtypes), column=2)

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
                settings_dtypes,
                create_settings_window,
            ),
        ).grid(sticky="nsew", row=102, column=0)
        Button(
            create_settings_window,
            text="Cancel",
            command=create_settings_window.destroy,
        ).grid(sticky="nsew", row=102, column=1)

        # create_settings_window.mainloop()

    def _create_settings_command(
        self, protocol, subject, settings_file, names, values, dtypes, window=None
    ):

        # create dictionary from user settings
        settings_dict = {}
        for n, v, dt in zip(names, values, dtypes):
            v_strip = v.get().replace(" ", "")
            if (n.get()) and (v_strip):
                if dt == "int":
                    val = int(v_strip)
                elif dt == "float":
                    val = float(v_strip)
                elif dt == "bool":
                    val = bool(strtobool(v_strip))
                elif dt == "string":
                    val = v_strip
                else:
                    try:
                        val = int(v_strip)
                    except ValueError:
                        try:
                            val = float(v_strip)
                        except ValueError:
                            try:
                                val = bool(strtobool(v_strip))
                            except ValueError:
                                val = v_strip

                settings_dict[n.get()] = val

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

    def _refresh_cameras_command(self):

        reply = self._remote_to_server(("CAMERAS", "REFRESH"))
        if not reply:
            messagebox.showwarning(
                "Refresh Cameras Failed!",
                "Failed to refresh cameras, please check server connections!",
                parent=self,
            )

    def _refresh_cameras(self, cameras):

        for i in range(len(self.bpod_frames)):
            self.bpod_frames[i].set_cameras(cameras)

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
        self.cfg["bpod_serials"][bpod_index] = bpod_serial
        self.bpod_frames[bpod_index].serial_number.set(bpod_serial)

    def _start_bpod(self, bpod_id, code):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        self.bpod_frames[bpod_index].start_bpod(code)

    def _end_bpod(self, bpod_id):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        self.bpod_frames[bpod_index].end_bpod()

    def _start_bpod_protocol(self, bpod_id, protocol, subject, settings, camera):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        self.bpod_frames[bpod_index].start_bpod_protocol(protocol, subject, settings, camera)

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
                    bpod_position = cmd[4]
                    self.cfg["bpod_ids"].append(bpod_id)
                    self.cfg["bpod_serials"].append(bpod_serial)
                    self._add_box(bpod_id, bpod_serial, bpod_position)

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

            elif cmd[0] == "CAMERAS":

                cameras = cmd[1]
                self._refresh_cameras(cameras)

            elif cmd[0] == "START":

                bpod_id = cmd[1]
                code = cmd[2]
                self._start_bpod(bpod_id, code)

            elif cmd[0] == "RUN":

                bpod_id = cmd[1]
                protocol = cmd[2]
                subject = cmd[3]
                settings = cmd[4]
                camera = cmd[5]
                self._start_bpod_protocol(bpod_id, protocol, subject, settings, camera)

            elif cmd[0] == "STOP":

                bpod_id = cmd[1]
                self._stop_bpod_protocol(bpod_id)

            elif cmd[0] == "END":

                bpod_id = cmd[1]
                self._end_bpod(bpod_id)

            elif cmd[0] == "CLOSE":

                messagebox.showwarning(
                    "Server Closed!",
                    "The BpodAcademy server has shut down. Please restart the server if you wish to run BpodAcademy.",
                )

        self.listen_to_server = self.after(
            BpodAcademy.ZMQ_SUBSCRIBE_FREQUENCY_MS, self._listen_to_server
        )

    def _remote_to_server(self, msg, timeout=ZMQ_REQUEST_RCVTIMEO_MS):

        if self.request is not None:

            self.request.setsockopt(zmq.RCVTIMEO, timeout)
            self.request.send_pyobj(msg)

            try:
                reply = self.request.recv_pyobj()
            except zmq.Again:
                reply = None

            return reply

    def _close_bpod_academy(self):

        self.after_cancel(self.listen_to_server)

        if not self.remote:
            closed = self._close_server(ask=True)
            if closed == -1:
                return
            elif closed == 0:
                self._disconnect_remote()
        else:
            self._disconnect_remote()

        self.quit()
        self.destroy()

    def _start_all_bpods(self):

        not_open = [
            i for i in range(len(self.bpod_frames)) if self.bpod_frames[i].status == 0
        ]

        if len(not_open) > 0:

            opening_window = Toplevel(self)
            opening_window.title("Starting Bpods")
            Label(opening_window, text="Starting all Bpods. Please wait...").pack()
            opening_window.update()

            res = self._remote_to_server(("BPOD", "START", "ALL"))

            opening_window.destroy()

            if not res:
                messagebox.showerror("Failure", "Failed to open all Bpods!")

    def _close_all_bpods(self):

        if any([fr.status == 1 for fr in self.bpod_frames]):

            closing_window = Toplevel(self)
            closing_window.title("Closing Bpods")
            Label(closing_window, text="Closing open Bpods. Please wait...").pack()
            closing_window.update()

            ### Close open Bpods ###
            for i in range(len(self.bpod_frames)):
                if self.bpod_frames[i].status > 0:
                    self.bpod_frames[i]._end_bpod()

            closing_window.destroy()

    def _close_server(self, ask=True):

        if ask:

            if messagebox.askyesno(
                "Close BpodAcademy Server?",
                "Do you want to close the BpodAcademy Server?\nAny open Bpod devices will be closed.",
                parent=self,
            ):

                ### check for running sessions ###
                if any([fr.status == 2 for fr in self.bpod_frames]):
                    messagebox.showwarning(
                        "Bpod protocol(s) are currently running. Please close open protocols before closing the BpodAcademy. Server",
                        parent=self,
                    )

                    return -1

                else:

                    self._close_all_bpods()

                    ### Close BpodAcademy server ###
                    self._remote_to_server(("CLOSE",))
                    if hasattr(self, "server"):
                        self.server.stop()
                        self.server.close()

                    return 1

            else:

                return 0

    def _save_training_config(self):

        config_file_name = simpledialog.askstring(
            "Training Config File",
            "Please enter a name for the new training config file:",
            parent=self,
        )

        if config_file_name is not None:

            bpod_ids = []
            protocols = []
            subjects = []
            settings = []
            for fr in self.bpod_frames:
                bpod_ids.append(fr.bpod_id)
                protocols.append(fr.protocol.get())
                subjects.append(fr.subject.get())
                settings.append(fr.settings.get())

            self._remote_to_server(
                (
                    "CONFIG",
                    "TRAINING",
                    "SAVE",
                    config_file_name,
                    bpod_ids,
                    protocols,
                    subjects,
                    settings,
                )
            )

    def _load_training_config(self):

        training_configs = self._remote_to_server(("CONFIG", "TRAINING", "FETCH"))

        if training_configs:
            choose_training_config_window = Toplevel(self)
            choose_training_config_window.title("Select Training Configuration")

            Label(choose_training_config_window, text="Configuration: ").grid(
                sticky="w", row=0, column=0
            )
            selected_file = StringVar(choose_training_config_window, value="")
            Combobox(
                choose_training_config_window,
                textvariable=selected_file,
                values=training_configs,
                state="readonly",
            ).grid(sticky="nsew", row=0, column=1)
            Button(
                choose_training_config_window,
                text="Submit",
                command=lambda: self._set_training_config(
                    selected_file.get(), choose_training_config_window
                ),
            ).grid(sticky="nsew", row=1, column=1)
            Button(
                choose_training_config_window,
                text="Cancel",
                command=choose_training_config_window.destroy,
            ).grid(sticky="nsew", row=2, column=1)

    def _set_training_config(self, training_config_file, window):

        window.destroy()

        if training_config_file:
            training_config = self._remote_to_server(
                ("CONFIG", "TRAINING", "FETCH", training_config_file)
            )

            if training_config[:2] == ("CONFIG", "TRAINING"):
                bpod_ids, protocols, subjects, settings = training_config[2:]

                for i in range(len(bpod_ids)):
                    this_bpod_ind = self.cfg["bpod_ids"].index(bpod_ids[i])
                    self.bpod_frames[this_bpod_ind].protocol.set(protocols[i])
                    self.bpod_frames[this_bpod_ind].subject.set(subjects[i])
                    self.bpod_frames[this_bpod_ind].settings.set(settings[i])

            else:

                messagebox.showerror("Server did not return training config.")


def main():

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--remote", action="store_true")
    parser.add_argument("-i", "--ip", type=str, default="*")
    parser.add_argument("-p", "--port", type=int, default=5555)
    args = parser.parse_args()

    BpodAcademy(remote=args.remote, ip=args.ip, port=args.port)


if __name__ == "__main__":
    main()
