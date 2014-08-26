#!/usr/bin/env python

"""
This module is a small program intended to run on a Raspberry Pi with
attached camera module.  It sends one full-resolution frame per second
to any client that requests imagery via a Pyro4 interface.
"""

import picamera
import threading
import time
import io
import BaseHTTPServer
import urlparse
import requests
import datetime
# import numpy as np

HOST = ''
PORT = 18765

IMAGE_POST_URL = "http://localhost:8100/fishface/upload_imagery/"

DATE_FORMAT = "%Y-%m-%d-%H:%M:%S"

class ImageryServer(object):
    """
    """

    WINNER = "yay"

    def __init__(self):
        self._keep_capturing = True

        self.camera = picamera.PiCamera()
        self.camera.resolution = (2048, 1536)
        self.camera.rotation = 180

        self._current_frame_capture_time = None

        # self.command_server = BaseHTTPServer.HTTPServer(
        #     ('raspi', 8421),
        #     CommandHandler
        # )

        self._current_frame = None

    def _capture_new_current_frame(self):
        stream = io.BytesIO()

        self._current_frame_capture_time = time.time()
        self.camera.capture(
            stream,
            format='jpeg'
        )

        self._current_frame = stream.getvalue()

    def get_current_frame(self):
        return self._current_frame

    def awb_mode(self, mode=None):
        if mode is None:
            return self.camera.awb_mode

        if mode in ['off', 'auto']:
            self.camera.awb_mode = mode
        else:
            raise Exception("Invalid AWB mode for raspi camera: " +
                            "{}".format(mode))

    def brightness(self, br=None):
        if br is None:
            return self.camera.brightness

        if 0 <= br <= 100:
            self.camera.brightness = br
        else:
            raise Exception("Invalid brightness setting for raspi " +
                            "camera: {}".format(br))

    def run(self):
        def image_capture_loop():
            while self._keep_capturing:
                self._capture_new_current_frame()
                time.sleep(0.2)
            self.camera.close()

        thread = threading.Thread(target=image_capture_loop)
        print "starting thread"
        thread.start()

        print "thread started"

        server_address = (HOST, PORT)
        httpd = BaseHTTPServer.HTTPServer(
            server_address,
            CommandHandler
        )
        httpd.parent = self

        print "about to start http server"

        try:
            httpd.serve_forever()
        except KeyboardInterrupt:
            self._keep_capturing = False
            httpd.server_close()

    def post_current_image_to_server(self, metadata):
        stream = io.BytesIO(self._current_frame)

        image_dtg = datetime.datetime.fromtimestamp(
            self._current_frame_capture_time
        ).strftime(
            DATE_FORMAT
        )

        since_epoch = time.time()

        image_filename = '{}_{}.jpg'.format(
            image_dtg,
            since_epoch
        )

        print 'posting {}'.format(image_filename)

        is_cal_image = (request.POST['is_cal_image'].lower()
                        in ['true','t','yes','y','1'])

        metadata['filename'] = image_filename
        metadata['capture_time'] = self._current_frame_capture_time
        metadata['is_cal_image'] = str(is_cal_image)


        files = {image_filename: stream}
        r = requests.post(
            IMAGE_POST_URL,
            files=files,
            data=metadata
        )
        return r

    def obey_server_command(self, raw_command):
        command = dict([field.split('=') for field in raw_command.split('&')])

        result = "no result"

        if command['command'] == 'post_image':
            result = self.post_current_image_to_server(command)
            if result.status_code == 500:
                result = result.text

        return result


class CommandHandler(BaseHTTPServer.BaseHTTPRequestHandler):

    def do_HEAD(self):
        self.send_response(200)
        self.send_header("Content-type", "text/html")
        self.end_headers()

    def do_GET(self):
        parsed_path = urlparse.urlparse(self.path)

        # self.send_response(200)
        # self.send_header("Contest-type", "type/html")
        # self.end_headers()

        result = self.server.parent.obey_server_command(
            parsed_path.query
        )
        self.wfile.write(str(result))


def main():
    imagery_server = ImageryServer()

    imagery_server.run()

    print "exiting"


if __name__ == '__main__':
    main()