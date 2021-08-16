import ctypes
import numpy as np
import cv2
import time
import threading
import multiprocess as mp
from multiprocess.queues import Queue
from queue import Empty
from pathlib import Path
import datetime
import logging


class BpodAcademyCamera(object):

    CAMERA_DISPLAY_MAX_WIDTH = 320
    WAIT_CAMERA_SEC = 10
    WAIT_WRITER_SEC = 5

    def __init__(
        self,
        device,
        width=640,
        height=480,
        fps=None,
        exposure=None,
        gain=None,
        sync_channel=None,
    ):

        try:
            self.device = int(device)
        except ValueError:
            self.device = device

        self.resolution = (int(width), int(height))
        self.fps = fps
        self.exposure = exposure
        self.gain = gain

        self.sync_channel = sync_channel

        self.resolution_display = (
            self.resolution
            if self.resolution[0] <= int(BpodAcademyCamera.CAMERA_DISPLAY_MAX_WIDTH)
            else (
                int(BpodAcademyCamera.CAMERA_DISPLAY_MAX_WIDTH),
                int(
                    BpodAcademyCamera.CAMERA_DISPLAY_MAX_WIDTH
                    / (self.resolution[0] / self.resolution[1])
                ),
            )
        )

        self.frame_shared = mp.Array(
            ctypes.c_uint8, self.resolution_display[1] * self.resolution_display[0] * 3
        )
        self.frame = np.frombuffer(self.frame_shared.get_obj(), dtype="uint8").reshape(
            self.resolution_display[1], self.resolution_display[0], 3
        )

        self.ctx = mp.get_context("spawn")
        self.q_cam_to_sync = Queue(ctx=self.ctx)
        self.q_sync_to_cam = Queue(ctx=self.ctx)

        self.acquisition_on = False

    def start_acquisition(self):

        self.acquisition_on = True

        self.q_cam_to_main = Queue(ctx=self.ctx)
        self.q_main_to_cam = Queue(ctx=self.ctx)

        self.cam_proc = self.ctx.Process(
            target=self._run_camera_process,
            args=(self.frame_shared,),
            daemon=True,
        )
        self.cam_proc.start()

        try:
            code = int(
                self.q_cam_to_main.get(timeout=BpodAcademyCamera.WAIT_CAMERA_SEC)
            )
        except Empty:
            code = -1

        return code

    def start_write(self, fileparts):

        self.q_main_to_cam.put(("WRITE", True, fileparts))

        try:
            res = self.q_cam_to_main.get(timeout=BpodAcademyCamera.WAIT_WRITER_SEC)
        except Empty:
            res = False

        return res

    def _run_camera_process(self, frame_shared):

        self.frame = np.frombuffer(frame_shared.get_obj(), dtype="uint8").reshape(
            self.resolution_display[1], self.resolution_display[0], 3
        )

        ret = self._initialize_camera()
        self.q_cam_to_main.put(ret)

        # setup camera acquisition and write threads
        self.frame_queue = Queue(ctx=self.ctx)
        self.camera_acquire = True
        self.camera_write = False

        # start camera acquisition thread and write thread (if fileparts provided)
        self.camera_acquire_thread = threading.Thread(
            target=self._acquire_on_thread, daemon=True
        )

        self.camera_acquire_thread.start()

        # wait for commands from main thread (start/stop write thread, stop acquisition)
        while self.camera_acquire:

            cmd = self.q_main_to_cam.get()

            if cmd[0] == "WRITE":

                if (cmd[1]) and (not self.camera_write):

                    self.camera_write = True
                    fileparts = cmd[2]
                    self.camera_write_thread = threading.Thread(
                        target=self._write_on_thread,
                        args=(fileparts,),
                        daemon=True,
                    )
                    self.camera_write_thread.start()

                    while not self.camera_write:
                        pass

                    self.q_cam_to_main.put(True)

                elif (not cmd[1]) and (self.camera_write):

                    self.camera_write = False
                    self.camera_write_thread.join()
                    self.camera_write_thread = None
                    self.q_cam_to_main.put(True)

                elif not cmd[1]:

                    self.q_cam_to_main.put(True)

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

    def _initialize_camera(self):

        # connect to camera, get first image
        self.cap = cv2.VideoCapture(self.device)

        self.cap.set(cv2.CAP_PROP_FRAME_WIDTH, self.resolution[0])
        self.cap.set(cv2.CAP_PROP_FRAME_HEIGHT, self.resolution[1])

        if self.fps is not None:
            self.cap.set(cv2.CAP_PROP_FPS, self.fps)
        else:
            self.fps = self.cap.get(cv2.CAP_PROP_FPS)

        if self.exposure is not None:
            self.cap.set(cv2.CAP_PROP_EXPOSURE, self.exposure)

        if self.gain is not None:
            self.cap.set(cv2.CAP_PROP_GAIN, self.gain)

        ret, _ = self.cap.read()

        return ret

    def _acquire_on_thread(self):

        while self.camera_acquire:

            ret, frame = self.cap.read()
            frame_time = time.time()

            if ret:

                np.copyto(self.frame, cv2.resize(frame, self.resolution_display))

                if self.camera_write:
                    self.frame_queue.put((frame, frame_time))

            else:

                logging.error(
                    "Camera: OpenCV VideoCapture.read did not return an image! Closing camera..."
                )
                self.camera_acquire = False

                # raise Exception("OpenCV VideoCapture.read did not return an image!")

    def _write_on_thread(self, fileparts):

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
            vw = cv2.VideoWriter(
                str(fn_vid), cv2.VideoWriter_fourcc(*"DIVX"), fps, self.resolution
            )
            frame_times = []

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

            # release video writer (save video)
            vw.release()

            # set up timestamps file
            fn_ts = (
                base_dir
                / "Timestamps"
                / f"{subject}_{protocol}_{start_camera_time_str}.npz"
            )
            fn_ts.parent.mkdir(parents=True, exist_ok=True)

            # (fetch sync times and) save timestamps
            if self.sync_channel is not None:
                self.q_cam_to_sync.put((self.sync_channel, frame_times[-1]))
                sync_times = self.q_sync_to_cam.get()
                np.savez(
                    fn_ts,
                    frame_times=np.array(frame_times),
                    sync_times=np.array(sync_times),
                )
            else:
                np.savez(fn_ts, frame_times=np.array(frame_times))

            # update time for next recording
            start_camera_time = start_camera_time + datetime.timedelta(hours=1)

        # clear frame queue (often there's an extra frame or two)
        time.sleep(0.25)
        try:
            n_frames = 0
            while True:
                self.frame_queue.get_nowait()
                n_frames += 1
        except:
            pass

    def get_image(self):

        if self.acquisition_on:
            return self.frame
        else:
            return None

    def stop_write(self):

        if self.acquisition_on:

            self.q_main_to_cam.put(("WRITE", False))

            try:
                res = self.q_cam_to_main.get(timeout=BpodAcademyCamera.WAIT_WRITER_SEC)
            except Empty:
                res = -1

        else:

            res = 0

        return res

    def stop_acquisition(self):

        if self.acquisition_on:

            self.q_main_to_cam.put(("ACQUIRE", False))

            # wait for camera process to finish
            self.cam_proc.join()

            # close camera process
            self.cam_proc = None
            self.acquisition_on = False

            return 1

        else:

            return 0
