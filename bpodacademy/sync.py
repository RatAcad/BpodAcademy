import serial
import multiprocess as mp
from multiprocess.queues import Queue
from queue import Empty
import threading
import numpy as np
import struct
import time

from bpodacademy.exception import BpodAcademyError


class BpodAcademyCameraSync(object):

    MAX_CHANNELS = 13
    WAIT_CONNECT_TO_SYNC_DEVICE_SEC = 10
    CLOSE_DEVICE_TIMEOUT_SEC = 10

    def __init__(self, serial_port, baud_rate=9600, read_timeout=0):

        self.sync_active = False
        self.sync_channels = [False for i in range(13)]
        self.sync_queues = [[None for i in range(13)], [None for i in range(13)]]
        self.channel_events = {}

        self.ctx = mp.get_context("spawn")
        self.q_main_to_read = Queue(ctx=self.ctx)
        self.q_read_to_main = Queue(ctx=self.ctx)

        self.processing_messages = True
        self.command_thread = threading.Thread(
            target=self._process_sync_messages, daemon=True
        )
        self.command_thread.start()

        self.read_process = self.ctx.Process(
            target=self._run_sync_process,
            args=(serial_port, baud_rate, read_timeout),
            daemon=True,
        )
        self.read_process.start()

    def _process_sync_messages(self):

        while self.processing_messages:

            try:
                msg = self.q_read_to_main.get_nowait()

                if msg[0] == "DEVICE_ON":
                    self.sync_active = True

                elif msg[0] == "DEVICE_OFF":
                    self.sync_active = False

                elif msg[0] == "CHANNEL_ON":
                    channel = msg[1]
                    self.sync_channels[channel] = True
                    this_channel = {channel: np.empty((0, 4))}
                    self.channel_events.update(this_channel)

                elif msg[0] == "CHANNEL_OFF":
                    channel = msg[1]
                    self.sync_channels[channel] = False

                elif msg[0] == "CHANNEL_TTL":
                    channel = msg[1]
                    state = msg[2]
                    sync_time = msg[3]
                    python_time = msg[4]
                    this_ttl = np.array([[channel, state, sync_time, python_time]])
                    self.channel_events[channel] = np.append(
                        self.channel_events[channel], this_ttl, axis=0
                    )

            except Empty:

                pass

            for i in range(len(self.sync_queues[0])):

                try:

                    if self.sync_queues[0][i] is not None:
                        msg = self.sync_queues[0][i].get_nowait()
                        channel = msg[0]
                        max_time = msg[1]
                        sync_times = self.get_sync_times(channel, max_time)
                        self.sync_queues[1][i].put(sync_times)

                except Empty:

                    pass

    def _run_sync_process(self, serial_port, baud_rate, read_timeout):

        # connect to serial port, give signal to activate sync device
        self.ser = serial.Serial(serial_port, baud_rate, timeout=read_timeout)

        # start read thread
        self.reading = True
        self.read_thread = threading.Thread(target=self._read_on_thread, daemon=True)
        self.read_thread.start()

        while self.reading:

            try:
                msg = self.q_main_to_read.get_nowait()

                if msg[0] == "DEVICE_ON":
                    self.ser.write(b"A")

                elif msg[0] == "DEVICE_OFF":
                    self.ser.write(b"Z")

                elif msg[0] == "CHANNEL_ON":
                    channel = msg[1]
                    serial_cmd = b"S" + struct.pack("h", channel)
                    self.ser.write(serial_cmd)

                elif msg[0] == "CHANNEL_OFF":
                    channel = msg[1]
                    serial_cmd = b"E" + struct.pack("h", channel)
                    res = self.ser.write(serial_cmd)

                elif msg[0] == "DEVICE_CLOSED":
                    self.reading = False

            except Empty:
                pass

        self.read_thread.join()

    def _read_on_thread(self):

        while self.reading:

            current_time = time.time()

            # wait for command
            cmd = self._read(require=False)

            if cmd == b"A":

                self.q_read_to_main.put(("DEVICE_ON", current_time))

            elif cmd in [b"S", b"E", b"T"]:

                if cmd == b"S":
                    code = "CHANNEL_ON"
                elif cmd == b"E":
                    code = "CHANNEL_OFF"
                elif cmd == b"T":
                    code = "CHANNEL_TTL"

                channel = struct.unpack("h", self._read(2))[0]
                state = self._read()[0]
                sync_time = struct.unpack("I", self._read(4))[0]

                self.q_read_to_main.put((code, channel, state, sync_time, current_time))

            elif cmd == b"Z":

                self.q_read_to_main.put(("DEVICE_OFF", current_time))

    def _read(self, nbytes=1, require=True):

        data = self.ser.read(nbytes)
        if (require) and (len(data) < nbytes):
            raise BpodAcademyError("Error reading from camera sync device!")
        return data

    def get_sync_times(self, channel, max_time=np.inf, delete=True):

        print(f"sync: getting sync times, max_time = {max_time}")

        channel_data = self.channel_events[channel].copy()
        sub_data = channel_data[channel_data[:, 3] < max_time]

        print(f"sync dim = {channel_data.shape}, sub dim = {sub_data.shape}")

        if delete:
            self.channel_events[channel] = np.delete(
                self.channel_events[channel],
                self.channel_events[channel][:, 3] < max_time,
                axis=0,
            )
        return sub_data

    def start_sync_device(self):

        self.q_main_to_read.put(("DEVICE_ON",))

        start_wait = time.time()
        while (not self.sync_active) and (
            time.time()
            < (start_wait + BpodAcademyCameraSync.WAIT_CONNECT_TO_SYNC_DEVICE_SEC)
        ):
            pass

        if not self.sync_active:
            raise BpodAcademyError("Error activating camera sync device!")

        return True

    def stop_sync_device(self):

        self.q_main_to_read.put(("DEVICE_OFF",))

        start_wait = time.time()
        while (self.sync_active) and (
            time.time()
            < (start_wait + BpodAcademyCameraSync.WAIT_CONNECT_TO_SYNC_DEVICE_SEC)
        ):
            pass

        if self.sync_active:
            raise BpodAcademyError("Failed to deactivate camera sync device!")

        return True

    def start_sync_channel(self, channel, q_cam_to_sync, q_sync_to_cam):

        self.sync_queues[0][channel] = q_cam_to_sync
        self.sync_queues[1][channel] = q_sync_to_cam

        self.q_main_to_read.put(("CHANNEL_ON", channel))

        start_wait = time.time()
        while (not self.sync_channels[channel]) and (
            time.time()
            < (start_wait + BpodAcademyCameraSync.WAIT_CONNECT_TO_SYNC_DEVICE_SEC)
        ):
            pass

        if not self.sync_channels[channel]:
            raise BpodAcademyError(f"Failed to start sync channel = {channel}!")

        return True

    def stop_sync_channel(self, channel):

        self.q_main_to_read.put(("CHANNEL_OFF", channel))

        start_wait = time.time()
        while (self.sync_channels[channel]) and (
            time.time()
            < (start_wait + BpodAcademyCameraSync.WAIT_CONNECT_TO_SYNC_DEVICE_SEC)
        ):
            pass

        if self.sync_channels[channel]:
            raise BpodAcademyError(f"Failed to stop sync channel = {channel}!")

        return True

    def close_sync_device(self):

        self.q_main_to_read.put(("DEVICE_CLOSED",))

        self.read_process.join(timeout=BpodAcademyCameraSync.CLOSE_DEVICE_TIMEOUT_SEC)
        if self.read_process.is_alive():
            raise BpodAcademyError("Failed to close camera sync read process!")

        self.processing_messages = False
        self.command_thread.join(timeout=BpodAcademyCameraSync.CLOSE_DEVICE_TIMEOUT_SEC)
        if self.command_thread.is_alive():
            raise BpodAcademyError("Failed to close camera sync command thread!")
