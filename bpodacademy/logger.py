import os
import logging
from queue import Empty
import threading
import time


class BpodAcademyLogger(object):

    WAIT_START_LOG = 3
    WAIT_STOP_LOG = 3

    def __init__(self, log_dir, log_queue):

        # check that log directory exists
        self.log_dir = log_dir
        os.makedirs(self.log_dir, exist_ok=True)

        # initialize logger attributes
        self.log_queue = log_queue
        self.log_thread = None
        self.is_logging = False

        # set up logging to file
        logging.basicConfig(
            filename=self.log_dir / "BpodAcademy.log",
            format="%(asctime)s %(levelname)-8s %(message)s",
            level=logging.DEBUG,
            datefmt="%Y-%m-%d %H:%M:%S",
        )

    def start_logging(self):

        self.log_thread = threading.Thread(target=self._log_on_thread, daemon=True)
        self.log_thread.start()

        res = False
        start_time = time.time()

        while (time.time() - start_time) < BpodAcademyLogger.WAIT_START_LOG:
            
            if self.is_logging:
                res = True
                break

        return res

    def _log_on_thread(self):

        logging.info("Logger started :)")

        self.is_logging = True

        while self.is_logging:

            try:
                log_entry = self.log_queue.get_nowait()
            except Empty:
                log_entry = None

            if log_entry is not None:
                
                level, msg = log_entry

                if level == "error":

                    print(f"ERROR :: {msg}")
                    logging.error(msg)

                elif level == "warning":

                    logging.warning(msg)

                elif level == "debug":

                    logging.debug(msg)

                else:

                    logging.info(msg)


    def stop_logging(self):
        
        if self.log_thread is not None:

            self.is_logging = False
            self.log_thread.join(timeout = BpodAcademyLogger.WAIT_STOP_LOG)
            res = (not self.log_thread.is_alive())

        return res