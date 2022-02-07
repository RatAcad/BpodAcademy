import serial
import multiprocess as mp
from multiprocess.queues import Queue
from queue import Empty
import threading
import numpy as np
import struct
import time
import logging
import traceback


class BpodAcademyCameraSync(object):

    MAX_CHANNELS = 13
    WAIT_CONNECT_TO_SYNC_DEVICE_SEC = 10
    WAIT_FETCH_SYNC_TIMES = 10
    CLOSE_DEVICE_TIMEOUT_SEC = 10

    def __init__(self, serial_port, baud_rate=9600, read_timeout=0):

        self.channel_events = {}

        self.ctx = mp.get_context("spawn")
        self.q_to_main = Queue(ctx=self.ctx)
        self.q_to_cmd = Queue(ctx=self.ctx)
        self.q_to_read = Queue(ctx=self.ctx)

        self.command_process = self.ctx.Process(
            target=self._process_sync_messages, daemon=True
        )

        self.read_process = self.ctx.Process(
            target=self._run_sync_process,
            args=(serial_port, baud_rate, read_timeout),
            daemon=True,
        )

        self.sync_active = False

    def _process_sync_messages(self):

        self.sync_channels = [False for i in range(13)]
        self.channel_events = {}

        processing_messages = True

        while processing_messages:

            try:

                msg = self.q_to_cmd.get_nowait()

                if msg[0] == "DEVICE_ON":
                    self.q_to_main.put("DEVICE_ON")

                elif msg[0] == "DEVICE_OFF":
                    self.q_to_main.put("DEVICE_OFF")

                elif msg[0] == "DEVICE_CLOSED":
                    self.q_to_main.put("DEVICE_CLOSED")
                    processing_messages = False

                elif msg[0] == "CHANNEL_ON":
                    channel = msg[1]
                    self.sync_channels[channel] = True
                    this_channel = {channel: np.empty((0, 4))}
                    self.channel_events.update(this_channel)
                    self.q_to_main.put("CHANNEL_ON")

                elif msg[0] == "CHANNEL_OFF":
                    channel = msg[1]
                    self.sync_channels[channel] = False
                    self.q_to_main.put("CHANNEL_OFF")

                elif msg[0] == "CHANNEL_TTL":
                    channel = msg[1]
                    state = msg[2]
                    sync_time = msg[3]
                    python_time = msg[4]
                    this_ttl = np.array([[channel, state, sync_time, python_time]])
                    self.channel_events[channel] = np.append(
                        self.channel_events[channel], this_ttl, axis=0
                    )

                elif msg[0] == "SYNC":
                    channel = msg[1]
                    max_time = msg[2]
                    delete = msg[3]
                    sync_times = self._fetch_channel_sync_times(channel, max_time, delete)
                    self.q_to_main.put(sync_times)

            except Empty:

                pass

    def _run_sync_process(self, serial_port, baud_rate, read_timeout):

        # connect to serial port, give signal to activate sync device
        self.ser = serial.Serial(serial_port, baud_rate, timeout=read_timeout)

        # start read thread
        self.reading = True

        while self.reading:

            ### write block

            try:

                msg = self.q_to_read.get_nowait()

                if msg[0] == "DEVICE_ON":
                    self.ser.write(b"A")

                elif msg[0] == "DEVICE_OFF":
                    self.ser.write(b"Z")

                elif msg[0] == "DEVICE_CLOSED":
                    self.reading = False
                    self.q_to_cmd.put(("DEVICE_CLOSED",))

                elif msg[0] == "CHANNEL_ON":
                    channel = msg[1]
                    serial_cmd = b"S" + struct.pack("h", channel)
                    self.ser.write(serial_cmd)

                elif msg[0] == "CHANNEL_OFF":
                    channel = msg[1]
                    serial_cmd = b"E" + struct.pack("h", channel)
                    res = self.ser.write(serial_cmd)

            except Empty:

                pass

            ### read block

            current_time = time.time()
            cmd = self._read(require=False)

            if cmd == b"A":

                self.q_to_cmd.put(("DEVICE_ON", current_time))

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

                self.q_to_cmd.put((code, channel, state, sync_time, current_time))

            elif cmd == b"Z":
                self.q_to_cmd.put(("DEVICE_OFF", current_time))
        
        self.ser.close()

    def _read(self, nbytes=1, require=True):

        data = self.ser.read(nbytes)
        if (require) and (len(data) < nbytes):
            logging.error(f"Error reading from camera sync device!\n{traceback.format_exc()}")
        return data

    def _fetch_channel_sync_times(self, channel, max_time=np.inf, delete=True):

        channel_data = self.channel_events[channel].copy()
        sub_data = channel_data[channel_data[:, 3] < max_time]

        if delete:
            self.channel_events[channel] = np.delete(
                self.channel_events[channel],
                self.channel_events[channel][:, 3] < max_time,
                axis=0,
            )
            
        return sub_data

    def get_sync_times(self, channel, max_time=np.inf, delete=True):

        self.q_to_cmd.put(("SYNC", channel, max_time, delete))

        try:
            sync_times = self.q_to_main.get(timeout=BpodAcademyCameraSync.WAIT_FETCH_SYNC_TIMES)
        except Empty:
            logging.error(f"Failed to fetch sync times for channel = {channel}!\n{traceback.format_exc()}")
            sync_times = []

        return sync_times

    def start_sync_device(self):

        self.command_process.start()
        self.read_process.start()

        self.q_to_read.put(("DEVICE_ON",))

        try:
            reply = None
            while reply != "DEVICE_ON":
                reply = self.q_to_main.get(
                    timeout=BpodAcademyCameraSync.WAIT_CONNECT_TO_SYNC_DEVICE_SEC
                )
        except Empty:
            logging.error(f"Error activating camera sync device!\n{traceback.format_exc()}")

        self.sync_active = True

        return True

    def stop_sync_device(self):

        self.q_to_read.put(("DEVICE_OFF",))

        try:
            reply = None
            while reply != "DEVICE_OFF":
                reply = self.q_to_main.get(
                    timeout=BpodAcademyCameraSync.WAIT_CONNECT_TO_SYNC_DEVICE_SEC
                )

            self.q_to_read.put(("DEVICE_CLOSED",))

            reply=None
            while reply != "DEVICE_CLOSED":
                reply = self.q_to_main.get(
                    timeout=BpodAcademyCameraSync.WAIT_CONNECT_TO_SYNC_DEVICE_SEC
                )

            self.read_process.join()
            self.command_process.join()

        except Empty:

            logging.error(f"Failed to deactivate camera sync device!\n{traceback.format_exc()}")

            return False

        self.sync_active = False

        return True

    def start_sync_channel(self, channel):

        self.q_to_read.put(("CHANNEL_ON", channel))

        try:
            res = self.q_to_main.get(timeout=BpodAcademyCameraSync.WAIT_CONNECT_TO_SYNC_DEVICE_SEC)
            res = 1 if res == "CHANNEL_ON" else 0
        except Empty:
            res = 0

        return res

    def stop_sync_channel(self, channel):

        self.q_to_read.put(("CHANNEL_OFF", channel))

        try:
            res = self.q_to_main.get(timeout=BpodAcademyCameraSync.WAIT_CONNECT_TO_SYNC_DEVICE_SEC)
            res = 1 if res == "CHANNEL_OFF" else 0
        except Empty:
            logging.error(f"Failed to stop sync channel = {channel}!\n{traceback.format_exc()}")
            return False

        return True
