import multiprocess as mp
from multiprocess.queues import Queue
from queue import Empty
import kthread

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
    SAVE_LOG_SEC = 1

    # Utility Functions

    @staticmethod
    def _get_datetime_string():

        date_time = datetime.datetime.now()
        return date_time.strftime("%m/%d/%Y %H:%M:%S")

    # Object Methods

    def __init__(self, id, serial_port, log_dir=None):
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
        self.ctx = mp.get_context("fork")
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

            return True

        else:

            return False

    def _calibrate_bpod(self):

        # only if protocol is not running
        if not self._check_running_protocol():

            self._write_to_log("calibrate")

            self.eng.BpodLiquidCalibration(
                "Calibrate", nargout=0, stdout=self.stdout, stderr=self.stdout,
            )

            return True

        else:

            return False

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
                return -1

        else:

            return 0

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
            return (True,) + self.protocol_details
        else:
            return (False,)

    def _stop_protocol(self):

        if self.protocol_thread is not None:

            if self.protocol_thread.is_alive():

                self._write_to_log("manually stopping protocol...")
                self.protocol_thread.raise_exc(KeyboardInterrupt)

                # wait for thread to complete after termination signal
                self.protocol_thread.join(timeout=BpodProcess.WAIT_KILL_PROTOCOL_SEC)

                if self.protocol_thread.is_alive():
                    return -1

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

            return True

        else:

            return False

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

            self.q_to_proc.put(cmd)

            try:
                result = self.q_to_main.get(timeout=timeout)
            except Empty:
                pass

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
