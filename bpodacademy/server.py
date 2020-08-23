from serial.tools import list_ports
import os
from pathlib import Path
import zmq
import threading
import csv
from scipy.io import savemat
import shutil

from bpodacademy.exception import BpodAcademyError
from bpodacademy.process import BpodProcess


class BpodAcademyServer:

    ### Constants ###
    ZMQ_REPLY_WAIT_MS = 10

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

    def __init__(self, bpod_dir=None, ip="*", port=5555):

        self.bpod_dir = bpod_dir if bpod_dir is not None else os.getenv("BPOD_DIR")
        if self.bpod_dir:
            self.bpod_dir = Path(self.bpod_dir)
        else:
            raise BpodAcademyError(
                "Bpod directory not specified! Please provide your local directory by setting the bpod_dir argument or by setting the environmental variable BPOD_DIR"
            )

        self.cfg_file = Path(f"{self.bpod_dir}/Academy/AcademyConfig.csv")
        self._read_config()

        # create log dir if it doesn't exist
        self.log_dir = Path(f"{self.bpod_dir}/Academy/logs")
        os.makedirs(self.log_dir, exist_ok=True)

        # initialize bpod process managers
        self.bpod_process = [None for bpod_id in self.cfg["bpod_ids"]]
        self.bpod_ports = BpodAcademyServer._get_bpod_ports()

        context = zmq.Context()
        self.reply = context.socket(zmq.REP)
        self.reply.setsockopt(zmq.RCVTIMEO, BpodAcademyServer.ZMQ_REPLY_WAIT_MS)
        self.reply.bind(f"tcp://{ip}:{port}")
        self.publish = context.socket(zmq.PUB)
        self.publish.bind(f"tcp://{ip}:{port+1}")

    def _read_config(self):

        bpod_ids = []
        bpod_serials = []
        bpod_status = []

        if os.path.isfile(self.cfg_file):

            cfg_reader = csv.reader(open(self.cfg_file, newline=""))
            for i in cfg_reader:
                bpod_ids.append(i[0])
                bpod_serials.append(i[1])
                bpod_status.append((0, None, None, None))

        self.cfg = {
            "bpod_dir": self.bpod_dir,
            "bpod_ids": bpod_ids,
            "bpod_serials": bpod_serials,
            "bpod_status": bpod_status,
        }

    def _save_config(self):

        cfg_writer = csv.writer(open(self.cfg_file, "w", newline=""))
        for n, s in zip(self.cfg["bpod_ids"], self.cfg["bpod_serials"]):
            cfg_writer.writerow([n, s])

    def start(self):

        self.server_open = True
        self.command_thread = threading.Thread(
            target=self._command_loop_on_thread, daemon=True
        )
        self.command_thread.start()

    def _command_loop_on_thread(self):

        while self.server_open:

            try:
                cmd = self.reply.recv_pyobj()
            except zmq.Again:
                cmd = None

            if cmd is not None:

                if cmd[0] == "CONFIG":

                    self.reply.send_pyobj(self.cfg)

                elif cmd[0] == "PORTS":

                    self.reply.send_pyobj(BpodAcademyServer._get_bpod_ports())

                elif cmd[0] == "PROTOCOLS":

                    if len(cmd) == 1:
                        self.reply.send_pyobj(self._load_protocols())

                    elif cmd[1] == "REFRESH":
                        self.reply.send_pyobj(True)
                        self.publish.send_pyobj(("PROTOCOLS", self._load_protocols()))

                elif cmd[0] == "SUBJECTS":

                    if cmd[1] == "FETCH":
                        protocol = cmd[2]
                        self.reply.send_pyobj(self._load_subjects(protocol))

                    elif cmd[1] == "ADD":
                        protocol = cmd[2]
                        subject = cmd[3]
                        res = self._add_subject(protocol, subject)
                        self.reply.send_pyobj(res)

                elif cmd[0] == "SETTINGS":

                    if cmd[1] == "FETCH":
                        protocol = cmd[2]
                        subject = cmd[3]
                        self.reply.send_pyobj(self._load_settings(protocol, subject))

                    elif cmd[1] == "COPY":
                        from_protocol = cmd[2]
                        from_subject = cmd[3]
                        from_settings = cmd[4]
                        to_protocol = cmd[5]
                        to_subject = cmd[6]
                        res = self._copy_settings(
                            from_protocol,
                            from_subject,
                            from_settings,
                            to_protocol,
                            to_subject,
                        )
                        self.reply.send_pyobj(res)

                    elif cmd[1] == "CREATE":

                        protocol = cmd[2]
                        subject = cmd[3]
                        settings_file = cmd[4]
                        settings_dict = cmd[5]
                        res = self._create_settings_file(
                            protocol, subject, settings_file, settings_dict
                        )
                        self.reply.send_pyobj(res)

                elif cmd[0] == "LOGS":

                    if cmd[1] == "DELETE":

                        res = self._delete_logs()
                        self.reply.send_pyobj(res)

                elif cmd[0] == "BPOD":

                    if cmd[1] == "ADD":

                        bpod_id = cmd[2]
                        bpod_serial = cmd[3]
                        res = self._add_box(bpod_id, bpod_serial)
                        self.reply.send_pyobj(res)

                    if cmd[1] == "REMOVE":

                        bpod_id = cmd[2]
                        res = self._remove_box(bpod_id)
                        self.reply.send_pyobj(res)

                    if cmd[1] == "CHANGE_PORT":

                        bpod_id = cmd[2]
                        bpod_serial = cmd[3]
                        res = self._change_port(bpod_id, bpod_serial)
                        self.reply.send_pyobj(res)

                        bpod_cfg_index = self.cfg["bpod_ids"].index(bpod_id)
                        self.cfg["bpod_serials"][bpod_cfg_index] = bpod_serial
                        self._save_config()
                        self.publish.send_pyobj(cmd)

                elif cmd[0] == "START":

                    bpod_id = cmd[1]
                    res = self._start_bpod(bpod_id)
                    self.reply.send_pyobj(res)

                elif cmd[0] == "GUI":

                    bpod_id = cmd[1]
                    res = self._switch_bpod_gui(bpod_id)
                    self.reply.send_pyobj(res)

                elif cmd[0] == "CALIBRATE":

                    bpod_id = cmd[1]
                    res = self._calibrate_bpod(bpod_id)
                    self.reply.send_pyobj(res)

                elif cmd[0] == "RUN":

                    bpod_id = cmd[1]
                    protocol = cmd[2]
                    subject = cmd[3]
                    settings = cmd[4]
                    res = self._start_bpod_protocol(
                        bpod_id, protocol, subject, settings
                    )
                    self.reply.send_pyobj(res)

                elif cmd[0] == "QUERY":

                    bpod_id = cmd[1]
                    res = self._query_bpod_status(bpod_id)
                    self.reply.send_pyobj(res)

                elif cmd[0] == "STOP":

                    bpod_id = cmd[1]
                    res = self._stop_bpod_protocol(bpod_id)
                    self.reply.send_pyobj(res)

                elif cmd[0] == "END":

                    bpod_id = cmd[1]
                    res = self._end_bpod(bpod_id)
                    self.reply.send_pyobj(res)

                elif cmd[0] == "CLOSE":

                    self.publish.send_pyobj(("CLOSE",))
                    self.reply.send_pyobj(True)

                else:

                    self.reply.send_pyobj(None)

    def stop(self):

        self.server_open = False
        self.command_thread.join()

    def close(self):

        self.reply.close()
        self.publish.close()

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

    def _add_subject(self, protocol, subject):

        sub_dir = Path(f"{self.bpod_dir}/Data/{subject}")
        sub_data_dir = sub_dir / protocol / "Session Data"
        sub_settings_dir = sub_dir / protocol / "Session Settings"
        sub_data_dir.mkdir(parents=True, exist_ok=True)
        sub_settings_dir.mkdir(parents=True, exist_ok=True)

        def_settings_file = sub_settings_dir / "DefaultSettings.mat"
        savemat(def_settings_file, {"ProtocolSettings": {}})

        return True

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

    def _copy_settings(
        self, from_protocol, from_subject, from_settings, to_protocol, to_subject
    ):

        copy_from = Path(
            f"{self.bpod_dir}/Data/{from_subject}/{from_protocol}/Session Settings/{from_settings}.mat"
        )
        copy_to = Path(
            f"{self.bpod_dir}/Data/{to_subject}/{to_protocol}/Session Settings/{from_settings}.mat"
        )

        ### check that copy_from exists
        if not copy_from.is_file():
            return False

        shutil.copy(copy_from, copy_to)

        return True

    def _create_settings_file(self, protocol, subject, settings_file, settings_dict):

        full_file = Path(
            f"{self.bpod_dir}/Data/{subject}/{protocol}/Session Settings/{settings_file}.mat"
        )
        savemat(full_file, {"ProtocolSettings": settings_dict})
        return True

    def _delete_logs(self):

        [log_file.unlink() for log_file in self.log_dir.iterdir()]
        return True

    def _add_box(self, bpod_id, bpod_serial):

        if bpod_id not in self.cfg["bpod_ids"]:

            self.cfg["bpod_ids"].append(bpod_id)
            self.cfg["bpod_serials"].append(bpod_serial)
            self.bpod_process.append(None)
            self._save_config()
            self.publish.send_pyobj(("BPOD", "ADD", bpod_id, bpod_serial))

            return True

        else:

            return False

    def _remove_box(self, bpod_id):

        if bpod_id not in self.cfg["bpod_ids"]:

            return False

        else:

            bpod_index = self.cfg["bpod_ids"].index(bpod_id)
            self.cfg["bpod_ids"].pop(bpod_index)
            self.cfg["bpod_serials"].pop(bpod_index)
            self._save_config()
            if self.bpod_process[bpod_index] is not None:
                self.bpod_process[bpod_index].close()
            self.bpod_process.pop(bpod_index)
            self.publish.send_pyobj(("BPOD", "REMOVE", bpod_id))

            return True

    def _change_port(self, bpod_id, bpod_serial):

        bpod_cfg_index = self.cfg["bpod_ids"].index(bpod_id)
        self.cfg["bpod_serials"][bpod_cfg_index] = bpod_serial
        self._save_config()
        self.publish.send_pyobj(("BPOD", "CHANGE_PORT", bpod_id, bpod_serial))
        return True

    def _start_bpod(self, bpod_id):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        bpod_serial = self.cfg["bpod_serials"][bpod_index]
        bpod_ports = BpodAcademyServer._get_bpod_ports()

        if bpod_serial == "EMU":
            bpod_port = "EMU"
        else:
            serial_index = [s[0] == bpod_serial for s in bpod_ports]
            serial_index = serial_index.index(True)
            bpod_port = bpod_ports[serial_index][1]

        self.bpod_process[bpod_index] = BpodProcess(
            bpod_id, bpod_port, log_dir=self.log_dir
        )
        res = self.bpod_process[bpod_index].start()

        # return result
        # 0 if not successful
        # 1 if successful
        # 2 if successful but no calibration file found for rig
        if res:
            cal_file = Path(
                f"{self.bpod_dir}/Calibration Files/LiquidCalibration_{bpod_id}.mat"
            )
            if cal_file.is_file():
                code = 1
            else:
                code = 2

            self.publish.send_pyobj(("START", bpod_id, code))
            self.cfg["bpod_status"][bpod_index] = (1, None, None, None)

        else:
            code = 0

        return code

    def _switch_bpod_gui(self, bpod_id):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)

        res = self.bpod_process[bpod_index].send_command(("GUI",))
        if (res is not None) and (res[0] == "GUI"):
            return res[1]
        else:
            return None

    def _calibrate_bpod(self, bpod_id):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)

        res = self.bpod_process[bpod_index].send_command(("CALIBRATE",))
        if (res is not None) and (res[0] == "CALIBRATE"):
            return res[1]
        else:
            return None

    def _start_bpod_protocol(self, bpod_id, protocol, subject, settings=None):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        settings = settings if settings is not None else "DefaultSettings"

        res = self.bpod_process[bpod_index].send_command(
            ("RUN", protocol, subject, settings)
        )

        if (res is not None) and (res[0] == "RUN"):
            if res[1] == 1:
                self.publish.send_pyobj(("RUN", bpod_id, protocol, subject, settings))
            return res[1]
        else:
            return None

    def _query_bpod_status(self, bpod_id):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)

        if self.bpod_process[bpod_index] is not None:
            res = self.bpod_process[bpod_index].send_command(("QUERY",))
            if (res is not None) and (res[0] == "QUERY"):
                if res[1]:
                    return (2, res[2], res[3], res[4])
                else:
                    return (1,)
            else:
                return None
        else:
            return (0,)

    def _stop_bpod_protocol(self, bpod_id):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)

        res = self.bpod_process[bpod_index].send_command(("STOP",))

        if (res is not None) and (res[0] == "STOP"):
            if res[1] == 1:
                self.publish.send_pyobj(("STOP", bpod_id))
            return res[1]
        else:
            return None

    def _end_bpod(self, bpod_id):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)

        res = self.bpod_process[bpod_index].send_command(("END",))

        if (res is not None) and (res[0] == "END"):
            self.publish.send_pyobj(("END", bpod_id))
            return res[1]
        else:
            return None
