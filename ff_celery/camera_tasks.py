import os
import time
import io
import Queue
import threading

import celery

from fishface_celery import celery_app
from util.fishface_logging import logger

from util.misc_utilities import delay_until, delay_for_seconds

import util.fishface_config as ff_conf

REAL_HARDWARE = not os.path.isfile('FAKE_THE_HARDWARE')

capture_thread = None
capture_thread_lock = threading.RLock()

import util.thread_with_heartbeat as thread_with_heartbeat


@celery_app.task(bind=True, name='camera.debug_task')
def debug_task(self):
    print('Request: {0!r}'.format(self.request))


class Camera(object):
    def __init__(self, resolution=ff_conf.CAMERA_RESOLUTION, rotation=ff_conf.CAMERA_ROTATION):
        self._lock = threading.RLock()

        self.cam = ff_conf.CAMERA_CLASS()
        self.cam.resolution = resolution
        self.cam.rotation = rotation

    def get_image_with_capture_time(self):
        stream = io.BytesIO()
        with self._lock:
            capture_time = float(time.time())
            self.cam.capture(stream, format_='jpeg')

        return (stream, capture_time)


class CaptureThread(thread_with_heartbeat.ThreadWithHeartbeat):
    def __init__(self, *args, **kwargs):
        super(CaptureThread, self).__init__(*args, **kwargs)
        self.name = 'capture_thread'

        self.queue = Queue.PriorityQueue()

        self._wait_for_capture_when_less_than = self._heartbeat_interval * 3

        self.cam = Camera()

        self._next_capture_time = None

    def _heartbeat_run(self):
        if self._next_capture_time is None:
            self._next_capture_time = self.pop_next_request()

        if not self._keep_looping:
            return

        if self._next_capture_time - time.time() < self._wait_for_capture_when_less_than:
            delay_until(self._next_capture_time)
            stream, timestamp = self.cam.get_image_with_capture_time()

            image = stream.read()

            celery_app.send_task('results.post_image', kwargs={
                'image': image,
                'requested_timestamp': self._next_capture_time,
                'actual_timestamp': timestamp,

            })

            self.queue.task_done()

            self._next_capture_time = None

    def _pre_run(self):
        self.set_ready()

    def _post_run(self):
        pass

    def push_capture_request(self, requested_capture_timestamp):
        self.queue.put(requested_capture_timestamp)

    def pop_next_request(self):
        try:
            return self.queue.get_nowait()
        except Queue.Empty:
            self.abort(complete=True)

    def abort(self, complete=False):
        super(CaptureThread, self).abort(complete=complete)
        if not complete:
            while not self.queue.empty():
                try:
                    self.queue.get_nowait()
                except Queue.Empty:
                    continue
                self.queue.task_done()

        self.cam.close()
        self.cam = None


@celery.shared_task(name="camera.push_capture_request")
def queue_capture_request(requested_capture_timestamp):
    global capture_thread, capture_thread_lock
    with capture_thread_lock:
        if capture_thread is None:
            startup_event = threading.Event()
            capture_thread = CaptureThread(startup_event=startup_event)
            if not startup_event.wait(timeout=3):
                logger.error("Couldn't create capture thread.")

    if capture_thread is not None and capture_thread.ready:
        capture_thread.push_capture_request(requested_capture_timestamp)
    else:
        logger.error("Tried to push request, but capture thread not ready.")


class CameraError(Exception):
    pass