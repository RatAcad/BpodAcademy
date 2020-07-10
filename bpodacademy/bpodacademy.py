from tkinter import Tk, Toplevel, \
                    messagebox, filedialog, simpledialog, \
                    Label, Entry, Button, \
                    StringVar
from tkinter.ttk import Combobox
import os
import subprocess
import csv
import serial.tools.list_ports as list_ports
import time


class BpodAcademy(Tk):


    OFF_COLOR = 'light salmon'
    READY_COLOR = 'light goldenrod'
    ON_COLOR = 'pale green'


    def __init__(self):

        Tk.__init__(self)

        ### find possible bpod ports

        self.bpod_ports = BpodAcademy._get_bpod_ports()

        ### load configuration file from bpod directory ###

        self.bpod_dir = os.getenv('BPOD_DIR')
        if self.bpod_dir is None:
            self._set_bpod_directory()
        self.cfg_file = os.path.normpath(f"{self.bpod_dir}/Academy/AcademyConfig.csv")
        self._read_config()

        ### create window ###
        
        self.n_bpods = 0
        self.bpod_status = []
        self._create_window()


    @staticmethod
    def _get_bpod_ports():

        com_ports = list_ports.comports()
        all_ports = []
        for p in com_ports:
            all_ports.append(com_ports)
        bpod_ports = [p[0] for p in all_ports if (('Arduino' in p[1]) or ('Teensy' in p[1]))]
        return bpod_ports


    def _set_bpod_directory(self):

        set_bpod_dir = messagebox.askokcancel("Bpod Directory not found!",
                                                {"The evironmental variable BPOD_DIR has not been set. "
                                                "Please click ok to select the Bpod Directory or cancel to exit the program."},
                                                parent=self)

        if set_bpod_dir:
            self.bpod_dir = filedialog.askdirectory("Please select local Bpod directory.", parent=self)

        if not self.bpod_dir:
            self.quit()


    def _read_config(self):

        ids = []
        ports = []
        
        if os.path.isfile(self.cfg_file):

            cfg_reader = csv.reader(open(self.cfg_file, newline=''))
            for i in cfg_reader:
                ids.append(i[0])
                ports.append(i[1])

        subs = os.listdir(os.path.normpath(f"{self.bpod_dir}/Data"))
        subs = [s for s in subs if s[0] is not '.']

        protocols = os.listdir(os.path.normpath(f"{self.bpod_dir}/Protocols"))
        protocols = [p for p in protocols if p[0] is not '.']

        self.cfg = {'ids' : ids, 'ports' : ports, 'subjects' : subs, 'protocols' : protocols}


    def _save_config(self):

        cfg_writer = csv.writer(open(self.cfg_file, 'w', newline=''))
        for n, p in zip(self.cfg['ids'], self.cfg['ports']):
            cfg_writer.writerow([n, p])

    
    def _change_port(self, event=None):

        for i in range(len(self.selected_ports)):
            self.cfg['ports'][i] = self.selected_ports.get()
        self._save_config()


    def _start_bpod(self, index):

        this_bpod = self.cfg['ids'][index]

        if self.bpod_status[index] != 0:
            
            messagebox.showwarning("Bpod already started!", f"{this_bpod} has already been started. Please close it before restarting.")
        
        else:

            wait_dialog = Toplevel(self)
            wait_dialog.title("Starting Bpod")
            Label(wait_dialog, text="Please wait...").pack()
            wait_dialog.update()

            this_port = self.selected_ports[index].get()

            # open screen for this bpod
            subprocess.call(["screen", "-dmS", this_bpod])

            # start matlab
            subprocess.call(["screen", "-S", this_bpod, "-X", "stuff", "matlab\n"])

            time.sleep(10)

            # start Bpod
            subprocess.call(["screen", "-S", this_bpod, "-X", "stuff", f"Bpod('{this_port}', 0, 0);\n"])

            time.sleep(5)
            
            self.bpod_status[index] = 1
            self.box_labels[index]['bg'] = BpodAcademy.READY_COLOR

            wait_dialog.destroy()


    def _switch_bpod_gui(self, index):

        this_bpod = self.cfg['ids'][index]

        if self.bpod_status[index] == 0:
            
            messagebox.showwarning("Bpod not started!", f"{this_bpod} has not been started. Please start Bpod before showing the GUI.")
        
        else:

            # call switch gui
            subprocess.call(["screen", "-S", this_bpod, "-X", "stuff", "BpodSystem.SwitchGUI();\n"])

            self.switch_gui_buttons[index]['text'] = "Hide GUI" if self.switch_gui_buttons[index]['text'] == "Show GUI" else "Show GUI"


    def _calibrate_bpod(self, index):

        this_bpod = self.cfg['ids'][index]

        if self.bpod_status[index] == 0:

            messagebox.showwarning("Bpod not started!", f"{this_bpod} has not been started. Please start before calibrating.")

        elif self.bpod_status[index] == 2:

            messagebox.showwarning("Protocol in progress!", f"A protocol is currently running on {this_bpod}. You cannot calibrate while a protocol is in session")

        else:

            # call calibration gui
            subprocess.call(["screen", "-S", this_bpod, "-X", "stuff", "BpodLiquidCalibration('Calibrate');\n"])


    def _run_bpod_protocol(self, index):

        this_bpod = self.cfg['ids'][index]

        if self.bpod_status[index] == 0:
            
            messagebox.showwarning("Bpod not started!", f"{this_bpod} has not been started. Please start before running a protocol.")

        elif self.bpod_status[index] == 2:

            messagebox.showwarning("Protocol in progress!", f"A protocol is currently running on {this_bpod}. Please stop this protocol and then restart.")

        else:

            this_protocol = self.selected_protocols[index].get()
            this_subject = self.selected_subjects[index].get()
            this_settings = self.selected_settings[index].get()
            
            command = ["screen", "-S", this_bpod, "-X", "stuff"]
            if this_settings:
                command += [f"RunProtocol('Start', '{this_protocol}', '{this_subject}', '{this_settings}');\n"]
            else:
                command += [f"RunProtocol('Start', '{this_protocol}', '{this_subject}');\n"]

            # send command to start
            subprocess.call(command)

            self.bpod_status[index] = 2
            self.box_labels[index]['bg'] = BpodAcademy.ON_COLOR

    def _stop_bpod_protocol(self, index):

        this_bpod = self.cfg['ids'][index]

        if self.bpod_status[index] != 2:
            
            messagebox.showwarning("Protocol not running!", f"A protocol is not currently running on {this_bpod}.")

        else:

            # send command to stop
            subprocess.call(["screen", "-S", this_bpod, "-X", "stuff", "StopProtocol;\n"])

            self.bpod_status[index] = 1
            self.box_labels[index]['bg'] = BpodAcademy.OFF_COLOR



    def _end_bpod(self, index):

        this_bpod = self.cfg['ids'][index]

        if self.bpod_status[index] == 2:
            
            messagebox.showwarning("Protocol in progress!", f"A protocol is currently running on {this_bpod}. Please stop the protocol if you wish to close this Bpod.")

        elif self.bpod_status[index] == 1:

            wait_dialog = Toplevel(self)
            wait_dialog.title("Starting Bpod")
            Label(wait_dialog, text="Please wait...").pack()
            wait_dialog.update()

            # send command to end bpod
            subprocess.call(["screen", "-S", this_bpod, "-X", "stuff", "EndBpod;\n"])

            time.sleep(5)

            # close matlab
            subprocess.call(["screen", "-S", this_bpod, "-X", "stuff", "exit\n"])

            time.sleep(10)

            # close screen session
            subprocess.call(["screen", "-S", this_bpod, "-X", "quit"])

            self.bpod_status[index] = 0
            self.box_labels[index]['bg'] = BpodAcademy.OFF_COLOR

            wait_dialog.destroy()


    def _add_box(self, id, port, index, new_box_window=None):

        if new_box_window is not None:
            new_box_window.destroy()
            self.cfg['ids'].append(id)
            self.cfg['ports'].append(port)
            self._save_config()

        self.bpod_status.append(0)

        ### row 1 ###

        self.box_labels.append(Label(self, text=id, bg=BpodAcademy.OFF_COLOR))
        self.box_labels[-1].grid(sticky='w', row=self.cur_row, column=self.cur_col)
       
        self.selected_ports.append(StringVar(self, value=port))
        self.port_entries.append(Combobox(self, textvariable=self.selected_ports[-1], values=self.bpod_ports, width=self.combobox_width))
        self.port_entries[-1].bind("<<ComboboxSelected>>", self._change_port)
        self.port_entries[-1].grid(sticky='nsew', row=self.cur_row, column=self.cur_col+1)

        self.start_buttons.append(Button(self, text="Start Bpod", command=lambda: self._start_bpod(index)))
        self.start_buttons[-1].grid(sticky='nsew', row=self.cur_row, column=self.cur_col+2)
        
        self.cur_row += 1

        ### row 2 ###

        self.selected_protocols.append(StringVar(self))
        Label(self, text="Protocol: ").grid(sticky='w', row=self.cur_row, column=self.cur_col)
        self.protocol_entries.append(Combobox(self, textvariable=self.selected_protocols[-1], values=self.cfg['protocols'], width=self.combobox_width))
        self.protocol_entries[-1].grid(sticky='nsew', row=self.cur_row, column=self.cur_col+1)
        
        self.switch_gui_buttons.append(Button(self, text="Show GUI", command=lambda: self._switch_bpod_gui(index)))
        self.switch_gui_buttons[-1].grid(sticky='nsew', row=self.cur_row, column=self.cur_col+2)

        self.run_protocol_buttons.append(Button(self, text="Run Protocol", command=lambda: self._run_bpod_protocol(index)))
        self.run_protocol_buttons[-1].grid(sticky='nsew', row=self.cur_row, column=self.cur_col+3)

        self.cur_row += 1

        ### row 3 ###

        self.selected_subjects.append(StringVar(self))
        Label(self, text="Subject: ").grid(sticky='w', row=self.cur_row, column=self.cur_col)
        self.subject_entries.append(Combobox(self, textvariable=self.selected_subjects[-1], values=self.cfg['subjects'], width=self.combobox_width))
        self.subject_entries[-1].grid(sticky='nsew', row=self.cur_row, column=self.cur_col+1)
        
        self.calib_gui_buttons.append(Button(self, text="Calibrate", command=lambda: self._calibrate_bpod(index)))
        self.calib_gui_buttons[-1].grid(sticky='nsew', row=self.cur_row, column=self.cur_col+2)

        self.stop_protocol_buttons.append(Button(self, text="Stop Protocol", command=lambda: self._stop_bpod_protocol(index)))
        self.stop_protocol_buttons[-1].grid(sticky='nsew', row=self.cur_row, column=self.cur_col+3)

        self.cur_row += 1

        ### row 4 ### 

        self.selected_settings.append(StringVar(self))
        Label(self, text="Settings: ").grid(sticky='w', row=self.cur_row, column=self.cur_col)
        self.settings_entries.append(Combobox(self, textvariable=self.selected_settings[-1]))
        self.settings_entries[-1].grid(sticky='nsew', row=self.cur_row, column=self.cur_col+1)

        self.end_buttons.append(Button(self, text="End Bpod", command=lambda: self._end_bpod(index)))
        self.end_buttons[-1].grid(sticky='nsew', row=self.cur_row, column=self.cur_col+2)

        self.cur_row += 1

        ### empty row ###

        Label(self).grid(row=self.cur_row, column=self.cur_col)
        self.cur_row += 1


    def _add_new_box(self):

        new_box_window = Toplevel(self)
        new_box_window.title("Add New Bpod")

        new_id = StringVar(new_box_window)
        Label(new_box_window, text="Box ID: ").grid(sticky='w', row=0, column=0)
        Entry(new_box_window, textvariable=new_id).grid(sticky='nsew', row=0, column=1)

        new_port = StringVar(new_box_window)
        Label(new_box_window, text="Serial Port: ").grid(sticky='w', row=1, column=0)
        Combobox(new_box_window, textvariable=new_port, values=self.bpod_ports+['EMU']).grid(sticky='nsew', row=1, column=1)

        Button(new_box_window, text="Submit", command=lambda: self._add_box(new_id.get(), new_port.get(), self.n_bpods, new_box_window)).grid(sticky='nsew', row=3, column=1)
        Button(new_box_window, text="Cancel", command=new_box_window.destroy).grid(sticky='nsew', row=4, column=1)

        self.n_bpods += 1


    def _add_new_subject(self):

        new_sub = simpledialog.askstring("Add New Subject", "Please enter Subject ID:")
        if new_sub is not None:
            if new_sub not in self.cfg['subjects']:
                self.cfg['subjects'].append(new_sub)
                for entry in self.subject_entries:
                    entry['values'] = self.cfg['subjects']
                os.makedirs(os.path.normpath(f"{self.bpod_dir}/Data/{new_sub}"), exist_ok=True)


    def _create_window(self):
        
        self.title("Bpod Academy")
        self.cur_row = 0
        self.cur_col = 0
        self.combobox_width = 15

        self.n_bpods = 0
        rows_per_box = 5

        self.add_bpod_button = Button(self, text='Add Bpod', command=self._add_new_box)
        self.add_sub_button = Button(self, text='Add Subject', command=self._add_new_subject)
        self.close_button = Button(self, text='Close', command=self.quit)

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

        for i in range(len(self.cfg['ids'])):

            self._add_box(self.cfg['ids'][i], self.cfg['ports'][i], i)
            self.n_bpods += 1

            if self.n_bpods % 5 == 0:
                Label(self, width=5).grid(row=0, column=self.cur_col+4)
                self.cur_col += 5
                self.cur_row = 0

        self.cur_row += 1
        
        self.add_sub_button.grid(sticky='nsew', row=5*(rows_per_box+1), column=0)
        self.add_bpod_button.grid(sticky='nsew', row=5*(rows_per_box+1)+1, column=0)
        self.close_button.grid(sticky='nsew', row=5*(rows_per_box+1)+1, column=1)


if __name__ == "__main__":
    gui = BpodAcademy()
    gui.mainloop()




