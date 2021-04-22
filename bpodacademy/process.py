import multiprocess as mp
from multiprocess.queues import Queue
from queue import Empty
import kthread
import cv2
import ctypes
import numpy as np

from pathlib import Path
import datetime
import time

import matlab.engine
import io


class BpodProcess:
    """BpodProcess Class

        Controls individual instances of matlab.engine in background processes,
        using the multiprocess package.
    """

    # Define Constants

    WAIT_START_PROCESS_SEC = 30
    WAIT_EXEC_COMMAND_SEC = 10
    WAIT_START_PROTOCOL_SEC = 1
    WAIT_KILL_PROTOCOL_SEC = 10
    WAIT_KILL_PROCESS_SEC = 10
    WAIT_START_CAMERA_SEC = 10
    CAMERA_DISPLAY_MAX_WIDTH = 320
    SAVE_LOG_SEC = 1

    # Utility Functions

    @staticmethod
    def _get_datetime_string():

        date_time = datetime.datetime.now()
        return date_time.strftime("%m/%d/%Y %H:%M:%S")

    # Object Methods

    def __init__(self, id, serial_port, camera=None, log_dir=None):
        """Constructor method

        Parameters
        ----------
        id : str
            Arbitrary name for Bpod
        serial_number : str
            The serial number for the FTDI chip on the Bpod device
        log_dir : str or Path-like object
            Path to the directory to save log files
        """

        self.id = id
        self.serial_port = serial_port
        self.camera = None
        self.ctx = mp.get_context("spawn")
        self.log_dir = (
            Path(log_dir) if log_dir is not None else Path("~/logs").expanduser()
        )
        self.protocol_details = None

    def _write_to_log(self, note=""):

        self.stdout.write(
            f"{BpodProcess._get_datetime_string()}\n{self.id}: {note}\n\n"
        )

    def _log_to_file(self):

        # get log content
        new_content_stdout = self.stdout.getvalue()

        # flush contents from log
        self.stdout.truncate(0)
        self.stdout.seek(0)

        # write contents to file
        self.log_file.write(new_content_stdout)
        self.log_file.flush()

    def _write_log_on_thread(self):

        while self.write_log:
            time.sleep(BpodProcess.SAVE_LOG_SEC)
            self._log_to_file()

    def _open_log_thread(self):

        self.write_log = True
        self.log_thread = kthread.KThread(target=self._write_log_on_thread, daemon=True)
        self.log_thread.start()

    def _close_log_thread(self):

        self.write_log = False
        self.log_thread.join()

    def _start_bpod(self):

        # start matlab engine

        self._write_to_log("starting matlab engine")
        self.eng = matlab.engine.start_matlab()

        # start Bpod

        self._write_to_log("starting bpod")
        self.eng.Bpod(
            self.serial_port,
            0,
            0,
            self.id,
            nargout=0,
            stdout=self.stdout,
            stderr=self.stdout,
        )

        self.q_to_main.put(True)

    def _check_running_protocol(self):

        is_running = False
        if self.protocol_thread is not None:
            if self.protocol_thread.is_alive():
                is_running = True

        return is_running

    def _switch_gui(self):

        # only if protocol is not running
        if not self._check_running_protocol():

            self._write_to_log("switch gui")

            self.eng.eval(
                "BpodSystem.SwitchGUI();",
                nargout=0,
                stdout=self.stdout,
                stderr=self.stdout,
            )

            return 1

        else:

            return 0

    def _calibrate_bpod(self):

        # only if protocol is not running
        if not self._check_running_protocol():

            self._write_to_log("calibrate")

            self.eng.BpodLiquidCalibration(
                "Calibrate", nargout=0, stdout=self.stdout, stderr=self.stdout,
            )

            return 1

        else:

            return 0

    def _start_protocol(self, protocol, subject, settings):

        if (self.protocol_thread is None) or not (self.protocol_thread.is_alive()):

            self._write_to_log(
                f"starting protocol = {protocol}, subject = {subject}, settings = {settings}",
            )

            self.protocol_details = (protocol, subject, settings)

            self.protocol_thread = kthread.KThread(
                target=self._run_protocol_on_thread,
                args=(protocol, subject, settings),
                daemon=True,
            )

            self.protocol_thread.start()

            # wait to see if protocol starts successfully
            time.sleep(BpodProcess.WAIT_START_PROTOCOL_SEC)

            if self.protocol_thread.is_alive():
                return 1
            else:
                return 0

        else:

            return 2

    def _run_protocol_on_thread(self, protocol, subject, settings):

        self.eng.RunProtocol(
            "StartSafe",
            protocol,
            subject,
            settings,
            nargout=0,
            stdout=self.stdout,
            stderr=self.stdout,
        )

    def _query_status(self):

        if (self.protocol_thread is not None) and (self.protocol_thread.is_alive()):
            return (1,) + self.protocol_details
        else:
            return (0,)

    def _stop_protocol(self):

        if self.protocol_thread is not None:

            if self.protocol_thread.is_alive():

                self._write_to_log("manually stopping protocol...")
                self.protocol_thread.raise_exc(KeyboardInterrupt)

                # wait for thread to complete after termination signal
                self.protocol_thread.join(timeout=BpodProcess.WAIT_KILL_PROTOCOL_SEC)

                if self.protocol_thread.is_alive():
                    return 2

            self.protocol_details = None
            self.protocol_thread = None
            self._write_to_log("protocol ended")
            return 1

        else:

            return 0

    def _end_bpod(self):

        if (self.protocol_thread is None) or (not self.protocol_thread.is_alive()):

            # close Bpod program in Matlab
            self._write_to_log("ending Bpod")
            self.eng.EndBpod(nargout=0, stdout=self.stdout, stderr=self.stdout)

            # close matlab engine
            self._write_to_log("exit matlab")
            self.eng.exit()

            return 1

        else:

            return 0

    def _process_academy_commands(self):

        self.protocol_thread = None
        cmd = None

        while True:

            # read incoming command
            full_cmd = self.q_to_proc.get()
            cmd = full_cmd[0]

            # switch gui
            if cmd == "GUI":

                code = self._switch_gui()
                self.q_to_main.put(("GUI", code))

            # calibrate
            elif cmd == "CALIBRATE":

                code = self._calibrate_bpod()
                self.q_to_main.put(("CALIBRATE", code))

            # start protocol
            elif cmd == "RUN":

                protocol = full_cmd[1]
                subject = full_cmd[2]
                settings = full_cmd[3]

                code = self._start_protocol(protocol, subject, settings)
                self.q_to_main.put(("RUN", code))

            # stop protocol manually
            elif cmd == "STOP":

                code = self._stop_protocol()
                self.q_to_main.put(("STOP", code))

            # end bpod
            elif cmd == "END":

                code = self._end_bpod()
                self.q_to_main.put(("END", code))

                if code:
                    break

            # check if protocol is running
            elif cmd == "QUERY":

                code = self._query_status()
                self.q_to_main.put(("QUERY",) + code)

    def _run_process(self):

        # open thread for writing log files

        self._open_log_thread()

        # open Bpod Matlab instance

        self._start_bpod()

        # process commands from BpodAcademy

        self._process_academy_commands()

        # close logging thread

        self._close_log_thread()

    def _camera_acquire_on_thread(self):

        while self.camera_acquire:

            ret, frame = self.cap.read()
            frame_time = time.time()

            if ret:

                np.copyto(self.frame, cv2.resize(frame, self.res_display))

                if self.camera_write:
                    self.frame_queue.put((frame, frame_time))

            else:

                raise Exception("OpenCV VideoCapture.read did not return an image!")

    def _camera_write_on_thread(self, fileparts):

        bpod_dir, protocol, subject = fileparts
        base_dir = Path(f"{bpod_dir}/Data/{subject}/{protocol}/Video Data")

        start_camera_time = datetime.datetime.now()

        while self.camera_write:

            # get file name
            start_camera_time_str = start_camera_time.strftime("%Y%m%d_%H%M%S")
            fn_vid = (
                base_dir / "Video" / f"{subject}_{protocol}_{start_camera_time_str}.avi"
            )
            fn_vid.parent.mkdir(parents=True, exist_ok=True)

            # create video writer and timestamp list
            fps = int(self.cap.get(cv2.CAP_PROP_FPS))
            vw = cv2.VideoWriter(str(fn_vid), cv2.VideoWriter_fourcc(*"DIVX"), fps, self.res)
            frame_times = []
            sync_times = []

            while (self.camera_write) and (
                (datetime.datetime.now() - start_camera_time)
                < datetime.timedelta(hours=1)
            ):

                try:
                    frame, frame_time = self.frame_queue.get_nowait()
                    vw.write(frame)
                    frame_times.append(frame_time)

                except Empty:
                    pass

            vw.release()

            fn_ts = (
                base_dir
                / "Timestamps"
                / f"{subject}_{protocol}_{start_camera_time_str}.npz"
            )
            fn_ts.parent.mkdir(parents=True, exist_ok=True)
            np.savez(fn_ts, np.array(frame_times), np.array(sync_times))

            # update time for next recording
            start_camera_time = start_camera_time + datetime.timedelta(hours=1)

        # clear frame queue (often there's an extra frame or two)
        time.sleep(0.1)
        try:
            n_frames = 0
            while True:
                self.frame_queue.get_nowait()
                n_frames += 1
        except:
            pass

    def _run_camera_process(self, frame_shared, fileparts=None):

        # connect to camera, get first image
        self.cap = cv2.VideoCapture(self.camera)
        self.cap.set(cv2.CAP_PROP_FPS, 30)
        ret, frame = self.cap.read()

        self.frame = np.frombuffer(frame_shared.get_obj(), dtype="uint8").reshape(
            self.res_display[1], self.res_display[0], 3
        )

        self.q_cam_to_main.put(ret)

        # setup camera acquisition and write threads
        self.frame_queue = Queue(ctx=self.ctx)
        self.camera_acquire = True
        self.camera_write = fileparts is not None

        # start camera acquisition thread and write thread (if fileparts provided)
        self.camera_acquire_thread = kthread.KThread(
            target=self._camera_acquire_on_thread, daemon=True
        )

        if fileparts is not None:
            self.camera_write_thread = kthread.KThread(
                target=self._camera_write_on_thread, args=(fileparts,), daemon=True
            )
            self.camera_write_thread.start()
        else:
            self.camera_write_thread = None

        self.camera_acquire_thread.start()

        # wait for commands from main thread (start/stop write thread, stop acquisition)
        while self.camera_acquire:

            cmd = self.q_main_to_cam.get()

            if cmd[0] == "WRITE":

                if (cmd[1]) and (not self.camera_write):

                    self.camera_write = True
                    fileparts = cmd[2]
                    self.camera_write_thread = kthread.KThread(
                        target=self._camera_write_on_thread, args=(fileparts,), daemon=True
                    )
                    self.camera_write_thread.start()

                elif (not cmd[1]) and (self.camera_write):

                    self.camera_write = False
                    self.camera_write_thread.join()
                    self.camera_write_thread = None

            elif cmd[0] == "ACQUIRE":

                self.camera_acquire = cmd[1]

        # wait for threads to finish
        self.camera_acquire_thread.join()

        if self.camera_write:
            self.camera_write = False
            self.camera_write_thread.join()
            self.camera_write_thread = None

        # close connection to camera
        self.cap.release()

    def set_camera(self, device):

        if (device is not None) and (device != ""):

            self.camera = device
            cap = cv2.VideoCapture(self.camera)
            self.res = (
                int(cap.get(cv2.CAP_PROP_FRAME_WIDTH)),
                int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT)),
            )
            cap.release()

            self.res_display = (
                self.res
                if self.res[0] <= int(BpodProcess.CAMERA_DISPLAY_MAX_WIDTH)
                else (
                    int(BpodProcess.CAMERA_DISPLAY_MAX_WIDTH),
                    int(
                        BpodProcess.CAMERA_DISPLAY_MAX_WIDTH
                        / (self.res[0] / self.res[1])
                    ),
                )
            )
            self.frame_shared = mp.Array(
                ctypes.c_uint8, self.res_display[1] * self.res_display[0] * 3
            )
            self.frame = np.frombuffer(
                self.frame_shared.get_obj(), dtype="uint8"
            ).reshape(self.res_display[1], self.res_display[0], 3)

            return True

        else:

            return False

    def start_camera(self, device, fileparts=None):

        # check if camera is already initialized
        if self.camera is not None:

            # if initialized camera same as requested device,
            #   check if video writer should be turned on
            if self.camera == device:
                if fileparts is not None:
                    self.q_main_to_cam.put(("WRITE", True, fileparts))
                return 1

            # otherwise turn off current camera
            else:
                self.stop_camera()

        has_camera = self.set_camera(device)

        if has_camera:

            self.q_cam_to_main = Queue(ctx=self.ctx)
            self.q_main_to_cam = Queue(ctx=self.ctx)

            self.cam_proc = self.ctx.Process(
                target=self._run_camera_process,
                args=(self.frame_shared, fileparts),
                daemon=True,
            )
            self.cam_proc.start()

            try:
                code = int(
                    self.q_cam_to_main.get(timeout=BpodProcess.WAIT_START_CAMERA_SEC)
                )
            except Empty:
                code = -1

        else:

            code = 0

        return code

    def get_camera_image(self):

        if self.camera is not None:
            return self.frame
        else:
            return None

    def stop_camera(self, write_only=False):

        # send signal to stop camera
        if self.camera is not None:

            if write_only:

                self.q_main_to_cam.put(("WRITE", False))

                return 2

            else:

                self.q_main_to_cam.put(("ACQUIRE", False))

                # wait for camera process to finish
                self.cam_proc.join()

                # close camera process
                self.cam_proc = None
                self.camera = None

                return 1

        else:

            return 0

    def start(self, timeout=WAIT_START_PROCESS_SEC):

        self.q_to_main = Queue(ctx=self.ctx)
        self.q_to_proc = Queue(ctx=self.ctx)

        self.stdout = io.StringIO()
        self.log_dir.mkdir(parents=True, exist_ok=True)
        log_file_name = self.log_dir / f"{self.id}.log"
        self.log_file = open(log_file_name, "a")

        self.proc = self.ctx.Process(target=self._run_process, daemon=True)
        self.proc.start()

        try:
            success = self.q_to_main.get(timeout=timeout)
        except Empty:
            success = False

        return success

    def send_command(self, cmd=None, timeout=WAIT_EXEC_COMMAND_SEC):

        result = None

        if cmd is not None:

            if self.proc.is_alive():

                self.q_to_proc.put(cmd)

                try:
                    result = self.q_to_main.get(timeout=timeout)
                except Empty:
                    pass

            else:

                result = cmd + (-1,)

        return result

    def check_messages(self):

        try:
            msg = self.q_to_main.get_nowait()
        except Empty:
            msg = None

        return msg

    def close(self, timeout=WAIT_KILL_PROCESS_SEC):

        success = False

        # if process is still running, send signal to close Bpod
        if self.proc.is_alive():

            # send signal to close Bpod
            reply = self.send_command(("END",))

            # if successful, wait for process to finish
            if reply[1]:
                self.proc.join(timeout=timeout)
                if not self.proc.is_alive():
                    success = True

        # if process is already finished, do nothing
        else:

            success = True

        if success:
            self.log_file.close()

        return success
