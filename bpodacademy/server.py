from serial.tools import list_ports
import platform
import os
from pathlib import Path
import zmq
import threading
import multiprocess as mp
from multiprocess.pool import ThreadPool
from multiprocess.queues import Queue
import csv
from scipy.io import savemat
import shutil
import traceback
import cv2
import time
import logging

from bpodacademy.exception import BpodAcademyError
from bpodacademy.process import BpodProcess
from bpodacademy.camera import BpodAcademyCamera
from bpodacademy.sync import BpodAcademyCameraSync


class BpodAcademyServer:

    ### Constants ###
    BPOD_DIR = os.getenv("BPOD_DIR")
    ZMQ_REPLY_WAIT_MS = 10

    ### Utility functions ###

    @staticmethod
    def _get_bpod_ports():

        com_ports = list_ports.comports()
        bpod_ports = []
        for p in com_ports:
            if platform.system() == "Windows":
                if (p.description is not None) and (
                    "USB Serial Device" in p.description
                ):
                    bpod_ports.append((p.serial_number, p.device))
            else:
                if (p.manufacturer is not None) and ("duino" in p.manufacturer):
                    bpod_ports.append((p.serial_number, p.device))

        return bpod_ports

    @staticmethod
    def _get_cameras():

        cap = cv2.VideoCapture()
        devs = []
        avail = True
        index = 0
        while avail:
            avail = cap.open(index)
            if avail:
                devs.append(index)
                cap.release()
            elif platform.system() == "Linux":
                avail = Path(f"/dev/video{index + 1}").exists()

            index += 1

        return devs

    def __init__(self, bpod_dir=None, ip="*", port=5555):

        self.bpod_dir = bpod_dir if bpod_dir is not None else os.getenv("BPOD_DIR")
        if self.bpod_dir:
            self.bpod_dir = Path(self.bpod_dir)
        else:
            raise BpodAcademyError(
                "Bpod directory not specified! Please provide your local directory by setting the bpod_dir argument or by setting the environmental variable BPOD_DIR"
            )

        self.cfg_file = Path(f"{self.bpod_dir}/Academy/AcademyConfig.csv")
        self.cfg_file_camera = Path(f"{self.bpod_dir}/Academy/CameraConfig.csv")
        self._read_config()

        # create log dir if it doesn't exist
        self.log_dir = Path(f"{self.bpod_dir}/Academy/logs")
        os.makedirs(self.log_dir, exist_ok=True)

        # start logging to file
        logging.basicConfig(
            filename=self.log_dir / "BpodAcademy.log",
            format="%(asctime)s %(levelname)-8s %(message)s",
            level=logging.DEBUG,
            datefmt="%Y-%m-%d %H:%M:%S",
        )

        # initialize bpod process managers
        self.bpod_process = [None for bpod_id in self.cfg["bpod_ids"]]
        self.camera_process = [None for bpod_id in self.cfg["bpod_ids"]]
        self.bpod_ports = BpodAcademyServer._get_bpod_ports()
        self.camera_devices = BpodAcademyServer._get_cameras()
        self.camera_sync = None

        context = zmq.Context()
        self.reply = context.socket(zmq.REP)
        self.reply.setsockopt(zmq.RCVTIMEO, BpodAcademyServer.ZMQ_REPLY_WAIT_MS)
        self.reply.bind(f"tcp://{ip}:{port}")
        self.publish = context.socket(zmq.PUB)
        self.publish.bind(f"tcp://{ip}:{port+1}")

    def _read_config(self):

        bpod_ids = []
        bpod_serials = []
        bpod_positions = []
        bpod_status = []

        if os.path.isfile(self.cfg_file):

            cfg_reader = csv.reader(open(self.cfg_file, newline=""))
            for i in cfg_reader:
                bpod_ids.append(i[0])
                bpod_serials.append(i[1])
                bpod_positions.append((int(i[2]), int(i[3])))
                bpod_status.append((0, None, None, None))

        self.cfg = {
            "bpod_dir": self.bpod_dir,
            "bpod_ids": bpod_ids,
            "bpod_serials": bpod_serials,
            "bpod_positions": bpod_positions,
            "bpod_status": bpod_status,
        }

        self.cameras = {"CameraSync": None}

        if os.path.isfile(self.cfg_file_camera):

            cfg_reader = csv.reader(open(self.cfg_file_camera, newline=""))
            for i in cfg_reader:

                if i[0] == "CameraSync":
                    self.cameras["CameraSync"] = int(i[1]) if i[1] else None
                else:
                    this_camera = {
                        i[0]: {
                            "device": i[1],
                            "width": int(i[2]) if i[2] else None,
                            "height": int(i[3]) if i[3] else None,
                            "fps": int(i[4]) if i[4] else None,
                            "exposure": int(i[5]) if i[5] else None,
                            "gain": int(i[6]) if i[6] else None,
                            "sync_channel": int(i[7]) if i[7] else None,
                            "record_protocol": i[8] if (len(i) > 8 and i[8]) else None,
                        }
                    }
                    self.cameras.update(this_camera)

    def _save_config(self):

        cfg_writer = csv.writer(open(self.cfg_file, "w", newline=""))
        for n, s, p in zip(
            self.cfg["bpod_ids"], self.cfg["bpod_serials"], self.cfg["bpod_positions"]
        ):
            cfg_writer.writerow([n, s, p[0], p[1]])

        cfg_camera_writer = csv.writer(open(self.cfg_file_camera, "w", newline=""))
        cfg_camera_writer.writerow(["CameraSync", self.cameras["CameraSync"]])
        for i in self.cameras:
            if i != "CameraSync":
                cam = self.cameras[i]
                cfg_camera_writer.writerow(
                    [
                        i,
                        cam["device"],
                        cam["width"],
                        cam["height"],
                        cam["fps"],
                        cam["exposure"],
                        cam["gain"],
                        cam["sync_channel"],
                        cam["record_protocol"],
                    ]
                )

    def start(self):

        self.server_open = True
        self.command_thread = threading.Thread(
            target=self._command_loop_on_thread, daemon=False
        )
        self.command_thread.start()

    def _command_loop_on_thread(self):

        while self.server_open:

            try:
                cmd = self.reply.recv_pyobj()
            except zmq.Again:
                cmd = None

            try:

                if cmd is not None:

                    if cmd[0] == "CONFIG":

                        if cmd[1] == "ACADEMY":

                            self.reply.send_pyobj((self.cfg, self.cameras))

                        elif cmd[1] == "TRAINING":

                            if cmd[2] == "SAVE":

                                config_file_name = cmd[3]
                                bpod_ids = cmd[4]
                                protocols = cmd[5]
                                subjects = cmd[6]
                                settings = cmd[7]
                                res = self._save_training_config(
                                    config_file_name,
                                    bpod_ids,
                                    protocols,
                                    subjects,
                                    settings,
                                )
                                self.reply.send_pyobj(res)

                            elif cmd[2] == "FETCH":

                                if len(cmd) == 3:

                                    self.reply.send_pyobj(self._get_training_configs())

                                else:

                                    training_config_file = cmd[3]
                                    training_config = self._load_training_config(
                                        training_config_file
                                    )
                                    self.reply.send_pyobj(
                                        ("CONFIG", "TRAINING") + training_config
                                    )

                            else:

                                self.reply.send_pyobj(False)

                    elif cmd[0] == "PORTS":

                        self.reply.send_pyobj(BpodAcademyServer._get_bpod_ports())

                    elif cmd[0] == "PROTOCOLS":

                        if len(cmd) == 1:
                            self.reply.send_pyobj(self._load_protocols())

                        elif cmd[1] == "REFRESH":
                            self.reply.send_pyobj(True)
                            self.publish.send_pyobj(
                                ("PROTOCOLS", self._load_protocols())
                            )

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
                            self.reply.send_pyobj(
                                self._load_settings(protocol, subject)
                            )

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

                    elif cmd[0] == "CAMERAS":

                        if (len(cmd) == 1) or (cmd[1] == "FETCH"):
                            self.reply.send_pyobj(self.camera_devices)

                        elif cmd[1] == "REFRESH":
                            self.camera_devices = BpodAcademyServer._get_cameras()
                            self.reply.send_pyobj(True)

                        elif cmd[1] == "EDIT":
                            bpod_id = cmd[2]
                            camera_settings = cmd[3]
                            self._edit_camera_settings(bpod_id, camera_settings)
                            self.reply.send_pyobj(True)

                        elif cmd[1] == "START":
                            bpod_id = cmd[2]
                            camera_settings = cmd[3]
                            res = self._start_camera(bpod_id, camera_settings)
                            self.reply.send_pyobj(res)

                        elif cmd[1] == "IMAGE":
                            bpod_id = cmd[2]
                            res = self._get_camera_image(bpod_id)
                            self.reply.send_pyobj(res)

                        elif cmd[1] == "STOP":
                            bpod_id = cmd[2]
                            res = self._stop_camera(bpod_id)
                            self.reply.send_pyobj(res)

                        elif cmd[1] == "SYNC":

                            connect = cmd[2]
                            if connect:
                                sync_serial = cmd[3]
                                res = self._connect_camera_sync(sync_serial)
                                self.reply.send_pyobj(res)
                            else:
                                res = self._disconnect_camera_sync()
                                self.reply.send_pyobj(res)

                    elif cmd[0] == "LOGS":

                        if cmd[1] == "DELETE":

                            res = self._delete_logs()
                            self.reply.send_pyobj(res)

                    elif cmd[0] == "BPOD":

                        bpod_id = cmd[2]

                        if cmd[1] == "ADD":

                            bpod_serial = cmd[3]
                            bpod_position = cmd[4]
                            res = self._add_box(bpod_id, bpod_serial, bpod_position)
                            self.reply.send_pyobj(res)

                        if cmd[1] == "REMOVE":

                            res = self._remove_box(bpod_id)
                            self.reply.send_pyobj(res)

                        if cmd[1] == "CHANGE_PORT":

                            bpod_serial = cmd[3]
                            res = self._change_port(bpod_id, bpod_serial)
                            self.reply.send_pyobj(res)

                            bpod_cfg_index = self.cfg["bpod_ids"].index(bpod_id)
                            self.cfg["bpod_serials"][bpod_cfg_index] = bpod_serial
                            self._save_config()
                            self.publish.send_pyobj(cmd)

                        elif cmd[1] == "START":

                            res = (
                                self._start_bpod(bpod_id)
                                if bpod_id != "ALL"
                                else self._start_all_bpods()
                            )
                            self.reply.send_pyobj(res)

                        elif cmd[1] == "GUI":

                            res = self._switch_bpod_gui(bpod_id)
                            self.reply.send_pyobj(res)

                        elif cmd[1] == "CALIBRATE":

                            res = self._calibrate_bpod(bpod_id)
                            self.reply.send_pyobj(res)

                        elif cmd[1] == "RUN":

                            protocol = cmd[3]
                            subject = cmd[4]
                            settings = cmd[5]
                            camera = cmd[6]
                            res, camera_res = self._start_bpod_protocol(
                                bpod_id, protocol, subject, settings, camera
                            )
                            self.reply.send_pyobj((res, camera_res))

                        elif cmd[1] == "QUERY":

                            res = self._query_bpod_status(bpod_id)
                            self.reply.send_pyobj(res)

                        elif cmd[1] == "STOP":

                            stop_camera_write_only = cmd[3]
                            res = self._stop_bpod_protocol(
                                bpod_id, stop_camera_write_only
                            )
                            self.reply.send_pyobj(res)

                        elif cmd[1] == "END":

                            res = self._end_bpod(bpod_id)
                            self.reply.send_pyobj(res)

                    elif cmd[0] == "CLOSE":

                        self.publish.send_pyobj(("CLOSE",))
                        self.reply.send_pyobj(True)
                        self.server_open = False

                    else:

                        raise BpodAcademyError(f"Command = {cmd} is not implemented!")

            except Exception:

                self.reply.send_pyobj(None)
                logging.error(
                    f"Server: error responding to the command {cmd}.\n{traceback.format_exc()}"
                )

    def stop(self):

        if self.camera_sync is not None:
            self.camera_sync.stop_sync_device()
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

        protocols.sort()
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

        subs_on_protocol.sort()
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

        settings.sort()
        return settings

    def _copy_settings(
        self, from_protocol, from_subject, from_settings, to_protocol, to_subject
    ):

        if to_subject == "All":
            to_subject = self._load_subjects(to_protocol)
            to_subject.remove(from_subject)
        else:
            to_subject = [to_subject]

        copy_from = Path(
            f"{self.bpod_dir}/Data/{from_subject}/{from_protocol}/Session Settings/{from_settings}.mat"
        )

        ### check that copy_from exists
        if not copy_from.is_file():
            return False

        for ts in to_subject:

            copy_to = Path(
                f"{self.bpod_dir}/Data/{ts}/{to_protocol}/Session Settings/{from_settings}.mat"
            )

            shutil.copy(copy_from, copy_to)

        return True

    def _create_settings_file(self, protocol, subject, settings_file, settings_dict):

        subject = [subject] if subject != "All" else self._load_subjects(protocol)

        for s in subject:
            full_file = Path(
                f"{self.bpod_dir}/Data/{s}/{protocol}/Session Settings/{settings_file}.mat"
            )
            savemat(full_file, {"ProtocolSettings": settings_dict})

        return True

    def _edit_camera_settings(self, bpod_id, camera_settings):

        if camera_settings["device"] is not None:
            self.cameras[bpod_id] = camera_settings
        else:
            self.cameras.pop(bpod_id, None)

        self._save_config()
        self.publish.send_pyobj(("CAMERAS", bpod_id, camera_settings))

    def _start_camera(self, bpod_id, camera_settings, fileparts=None):

        ### return codes
        # 1 = success
        # 0 = no camera or camera already running
        # -1 = camera failed to start
        # -2 = sync failed to start
        # -3 = writer failed to start

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)

        if (camera_settings is None) or (camera_settings["device"] is None):
            return 0

        if self.camera_process[bpod_index] is not None:
            if camera_settings["device"] != str(self.camera_process[bpod_index].device):
                self.camera_process[bpod_index].stop_acquisition()
                self.camera_process[bpod_index] = None

        if self.camera_process[bpod_index] is None:
            self.camera_process[bpod_index] = BpodAcademyCamera(
                camera_settings["device"],
                camera_settings["width"],
                camera_settings["height"],
                camera_settings["fps"],
                camera_settings["exposure"],
                camera_settings["gain"],
                self.camera_sync,
                camera_settings["sync_channel"],
            )

            res = self.camera_process[bpod_index].start_acquisition()
            if res <= 0:
                return -1

        if fileparts is not None:
            if self.camera_sync is not None:
                res = self.camera_sync.start_sync_channel(
                    camera_settings["sync_channel"],
                )
                if not res:
                    return -2

            res = self.camera_process[bpod_index].start_write(fileparts)
            if not res:
                return -3

            return 1

        else:

            return 1

    def _get_camera_image(self, bpod_id):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        if self.camera_process[bpod_index] is not None:
            return self.camera_process[bpod_index].get_image()
        return None

    def _stop_camera(self, bpod_id, write_only=False):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        if write_only:
            res = self.camera_process[bpod_index].stop_write()
        else:
            res = self.camera_process[bpod_index].stop_acquisition()
            if res:
                self.camera_process[bpod_index] = None
        return res

    def _connect_camera_sync(self, sync_serial):

        if sync_serial != self.cameras["CameraSync"]:
            self.cameras["CameraSync"] = sync_serial
            self.publish.send_pyobj(("CAMERAS", "SYNC", sync_serial))
            self._save_config()

            if self.camera_sync is not None:
                self._disconnect_camera_sync()

        if self.camera_sync is None:
            all_ports = BpodAcademyServer._get_bpod_ports()
            sync_serial_port = [p[1] for p in all_ports if int(p[0]) == sync_serial][0]
            self.camera_sync = BpodAcademyCameraSync(sync_serial_port)
            res = self.camera_sync.start_sync_device()
        else:
            res = self.camera_sync.sync_active

        return res

    def _disconnect_camera_sync(self):

        if self.camera_sync is not None:
            res = self.camera_sync.stop_sync_device()
            if res:
                self.camera_sync = None
        else:
            res = True

        return res

    def _delete_logs(self):

        [log_file.unlink() for log_file in self.log_dir.iterdir()]
        return True

    def _add_box(self, bpod_id, bpod_serial, bpod_position):

        if bpod_id not in self.cfg["bpod_ids"]:

            self.cfg["bpod_ids"].append(bpod_id)
            self.cfg["bpod_serials"].append(bpod_serial)
            self.cfg["bpod_status"].append((0, None, None, None))
            self.cfg["bpod_positions"].append(bpod_position)
            self.bpod_process.append(None)
            self._save_config()
            self.publish.send_pyobj(
                ("BPOD", "ADD", bpod_id, bpod_serial, bpod_position)
            )

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

    def _save_training_config(
        self, config_file_name, bpod_ids, protocols, subjects, settings
    ):

        training_config_dir = self.bpod_dir / "Academy" / "training"
        training_config_dir.mkdir(exist_ok=True)

        training_config_file = training_config_dir / f"{config_file_name}.csv"

        cfg_writer = csv.writer(open(training_config_file, "w", newline=""))
        for id, pro, sub, set in zip(bpod_ids, protocols, subjects, settings):
            cfg_writer.writerow([id, pro, sub, set])

        return True

    def _get_training_configs(self):

        training_config_dir = self.bpod_dir / "Academy" / "training"
        training_config_files = (
            [str(tcfg.stem) for tcfg in training_config_dir.iterdir()]
            if training_config_dir.is_dir()
            else False
        )
        return training_config_files

    def _load_training_config(self, training_config_file):

        file_path = (
            self.bpod_dir / "Academy" / "training" / f"{training_config_file}.csv"
        )

        bpod_ids = []
        protocols = []
        subjects = []
        settings = []

        cfg_reader = csv.reader(open(file_path, newline=""))
        for i in cfg_reader:
            bpod_ids.append(i[0])
            protocols.append(i[1])
            subjects.append(i[2])
            settings.append(i[3])

        return (bpod_ids, protocols, subjects, settings)

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
        # -1 if matlab process failed to start
        # 0 if otherwise not successful
        # 1 if successful
        # 2 if successful but no calibration file found for rig

        if res > 0:
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

            code = res

        return code

    def _start_all_bpods(self):

        not_open = [
            self.cfg["bpod_ids"][i]
            for i in range(len(self.bpod_process))
            if self.bpod_process[i] is None
        ]

        try:

            if len(not_open) > 0:

                pool = ThreadPool(len(not_open))
                pool.map(self._start_bpod, not_open)

            return True

        except Exception as e:

            logging.error(f"Server: error starting all bpod = {e}.\n{traceback.format_exc()}")


            return False

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

    def _start_bpod_protocol(
        self, bpod_id, protocol, subject, settings=None, camera=None
    ):

        ### return codes (protocol, camera)
        ## protocol
        # 1 = success
        # 0 = task already running
        # -1 = failure
        ## camera
        # 1 = success
        # 0 = no camera or task already running
        # -1 = acquisition failed to start
        # -2 = sync failed to start
        # -3 = writer failed to start

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)
        settings = settings if settings is not None else "DefaultSettings"

        camera_res = 0
        if (camera is not None) and (camera != ""):
            if protocol == camera["record_protocol"]:
                fileparts = (self.bpod_dir, protocol, subject)
                camera_res = self._start_camera(bpod_id, camera, fileparts)

        res = self.bpod_process[bpod_index].send_command(
            ("RUN", protocol, subject, settings)
        )

        if (res is not None) and (res[0] == "RUN"):

            if res[1] == 1:
                self.publish.send_pyobj(
                    ("RUN", bpod_id, protocol, subject, settings, camera)
                )
                return res, camera_res

            else:

                if (camera is not None) and (camera != ""):
                    if protocol == camera["record_protocol"]:
                        if self.camera_sync.command_process.is_alive():
                            if self.cameras[bpod_id]["sync_channel"] is not None:
                                self.camera_sync.stop_sync_channel(
                                    int(self.cameras[bpod_id]["sync_channel"])
                                )
                        if camera_res > 0:
                            self._stop_camera(bpod_id, True)

                return res, camera_res

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

    def _stop_bpod_protocol(self, bpod_id, stop_camera_write_only=False):

        bpod_index = self.cfg["bpod_ids"].index(bpod_id)

        res = self.bpod_process[bpod_index].send_command(("STOP",))

        time.sleep(0.25)

        if (self.camera_process[bpod_index] is not None) and (
            self.camera_process[bpod_index].writer_on
        ):
            if self.camera_sync is not None:
                sync_res = self.camera_sync.stop_sync_channel(
                    int(self.cameras[bpod_id]["sync_channel"])
                )
            camera_res = self._stop_camera(bpod_id, stop_camera_write_only)
        else:
            camera_res = 0

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


def main():

    import argparse

    parser = argparse.ArgumentParser()
    parser.add_argument("-i", "--ip", type=str, default="*")
    parser.add_argument("-p", "--port", type=int, default=5555)
    args = parser.parse_args()

    server = BpodAcademyServer(ip=args.ip, port=args.port)
    server.start()
