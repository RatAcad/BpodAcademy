import ctypes
import numpy as np
import cv2
import skvideo.io
import time
import multiprocess as mp
from multiprocess.queues import Queue
from queue import Empty
from pathlib import Path
import datetime
import traceback


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
        compression=0,
        sync_device=None,
        sync_channel=None,
        ctx=None,
        log_queue=None,
    ):

        try:
            self.device = int(device)
        except ValueError:
            self.device = device

        self.resolution = (int(width), int(height))
        self.fps = fps
        self.exposure = exposure
        self.gain = gain
        self.compression = compression

        self.sync_device = sync_device
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

        self.ctx = mp.get_context("spawn") if ctx is not None else ctx
        self.log_queue = log_queue

        self.acquisition_on = False
        self.writer_on = False

    def start_acquisition(self):

        self.acquisition_on = True

        self.q_cam_to_main = Queue(ctx=self.ctx)
        self.q_main_to_acquire = Queue(ctx=self.ctx)
        self.frame_queue = Queue(ctx=self.ctx)

        self.cam_acquire = self.ctx.Process(
            target=self._acquire_on_process,
            args=(self.frame_shared,),
            daemon=True,
        )

        self.cam_acquire.start()

        try:
            code, self.fps = self.q_cam_to_main.get(
                timeout=BpodAcademyCamera.WAIT_CAMERA_SEC
            )
            code = int(code)
        except Empty:
            code = -1

        return code

    def start_write(self, fileparts):

        # open writer process

        self.q_main_to_writer = Queue(ctx=self.ctx)

        self.cam_write = self.ctx.Process(
            target=self._write_on_process,
            args=(fileparts,),
            daemon=True,
        )

        self.cam_write.start()

        try:
            res = self.q_cam_to_main.get(timeout=BpodAcademyCamera.WAIT_WRITER_SEC)
            self.writer_on = True

            # tell acquire process to start saving frames
            self.q_main_to_acquire.put(("WRITE", True))

        except Empty:
            res = False

        return res

    def _acquire_on_process(self, frame_shared):

        self.frame = np.frombuffer(frame_shared.get_obj(), dtype="uint8").reshape(
            self.resolution_display[1], self.resolution_display[0], 3
        )

        ret = self._initialize_camera()
        camera_acquire = True
        camera_write = False

        if ret:
            self.q_cam_to_main.put((ret, int(self.cap.get(cv2.CAP_PROP_FPS))))
        else:
            self.q_cam_to_main.put((ret, -1))

        # camera acquire loop

        while camera_acquire:

            ret, frame = self.cap.read()
            frame_time = time.time()

            if ret:

                np.copyto(self.frame, cv2.resize(frame, self.resolution_display))

                if camera_write:
                    self.frame_queue.put((frame, frame_time))

            else:

                if self.log_queue is not None:
                    self.log_queue.put(
                        (
                            "error",
                            f"Camera: OpenCV VideoCapture.read did not return an image! stopping acquisition...\n{traceback.format_exc()}",
                        )
                    )

                print(f"Camera {self.device} crashed, please reconnect!")

                camera_acquire = False

            # wait for commands from main thread (start/stop write thread, stop acquisition)

            try:
                cmd = self.q_main_to_acquire.get_nowait()
            except Empty:
                cmd = None

            if cmd is not None:

                if cmd[0] == "WRITE":
                    camera_write = cmd[1]

                elif cmd[0] == "ACQUIRE":
                    camera_acquire = cmd[1]

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

    def _write_on_process(self, fileparts):

        bpod_dir, protocol, subject = fileparts
        base_dir = Path(f"{bpod_dir}/Data/{subject}/{protocol}/Video Data")

        start_camera_time = datetime.datetime.now()

        camera_write = True
        first_video = True

        while camera_write:

            # get file name
            start_camera_time_str = start_camera_time.strftime("%Y%m%d_%H%M%S")
            # fn_vid = (
            #     base_dir / "Video" / f"{subject}_{protocol}_{start_camera_time_str}.avi"
            # )
            fn_vid = (
                base_dir / "Video" / f"{subject}_{protocol}_{start_camera_time_str}.mp4"
            )
            fn_vid.parent.mkdir(parents=True, exist_ok=True)

            # create video writer and timestamp list
            # vw = cv2.VideoWriter(
            #     fn_vid.as_posix(),
            #     cv2.VideoWriter_fourcc(*"DIVX"),
            #     self.fps,
            #     self.resolution,
            # )
            vw = skvideo.io.FFmpegWriter(
                fn_vid.as_posix(),
                inputdict={"-r": f"{int(self.fps)}"},
                outputdict={
                    "-vcodec": "libx264",
                    "-r": f"{int(self.fps)}",
                    "-crf": f"{self.compression}",
                },
            )
            frame_time = datetime.datetime.timestamp(start_camera_time)
            frame_times = []

            if first_video:
                self.q_cam_to_main.put(True)
                first_video = False

            while (camera_write) and (
                (datetime.datetime.fromtimestamp(frame_time) - start_camera_time)
                < datetime.timedelta(hours=1)
            ):

                try:
                    frame, frame_time = self.frame_queue.get_nowait()
                    # vw.write(frame)
                    vw.writeFrame(cv2.cvtColor(frame, cv2.COLOR_BGR2RGB))
                    frame_times.append(frame_time)

                except Empty:
                    pass

                # check for commands
                try:
                    cmd = self.q_main_to_writer.get_nowait()
                except Empty:
                    cmd = None

                if cmd is not None:
                    if cmd[0] == "WRITE":
                        camera_write = cmd[1]

            # release video writer (save video)
            # vw.release()
            vw.close()

            # set up timestamps file
            fn_ts = (
                base_dir
                / "Timestamps"
                / f"{subject}_{protocol}_{start_camera_time_str}.npz"
            )
            fn_ts.parent.mkdir(parents=True, exist_ok=True)

            # (fetch sync times and) save timestamps
            if (self.sync_device is not None) and (self.sync_channel is not None):
                sync_times = self.sync_device.get_sync_times(
                    self.sync_channel, frame_times[-1]
                )
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

            self.q_main_to_acquire.put(("WRITE", False))
            self.q_main_to_writer.put(("WRITE", False))

            # wait for writer to finish
            try:
                self.cam_write.join()
                res = 1
                self.writer_on = False
            except Exception:
                res = 0

        else:

            res = 0

        return res

    def stop_acquisition(self):

        if self.acquisition_on:

            if self.writer_on:
                self.stop_write()

            self.q_main_to_acquire.put(("ACQUIRE", False))

            # wait for camera process to finish
            self.cam_acquire.join()

            # close camera process
            self.cam_proc = None
            self.acquisition_on = False

            return 1

        else:

            return 0
