# coding=utf-8
import requests
import logging
import threading
import traceback
import warnings
from StringIO import StringIO
from contextlib import closing
from requests_toolbelt import MultipartEncoder
_logger = logging.getLogger('octoprint.plugins.raisecloud')

try:
    from PIL import Image
except ImportError:
    Image = None
    import subprocess
    traceback.print_exc()
    warnings.warn("Pillow is not available. make sure it is installed.")


_instance_camera = None


def webcam_instance(plugin):
    global _instance_camera
    if not _instance_camera:
        _instance_camera = Webcam(plugin)
    return _instance_camera


class Webcam(object):
    def __init__(self, plugin):
        self.sleep_times = 0
        self.plugin = plugin
        self.settings = plugin._settings
        self.cam_status = True
        # self.snapshot_url = self.settings.global_get(["webcam", "snapshot"])
        # self.camera_url = self.settings.global_get(["webcam", "stream"])
        self.image_transpose = (self.settings.global_get(["webcam", "flipH"]) or
                                 self.settings.global_get(["webcam", "flipV"]) or
                                 self.settings.global_get(["webcam", "rotate90"]))

    def check_cam_status(self):
        snapshot_url = self.settings.global_get(["webcam", "snapshot"])
        camera_url = self.settings.global_get(["webcam", "stream"])
        if snapshot_url and camera_url:
            try:
                result = requests.get(snapshot_url)
                if result.status_code == 200:
                    self.cam_status = True
                else:
                    self.cam_status = False
            except Exception as e:
                self.cam_status = False
                _logger.error("Error getting camera status: %s" % e)

    def get_snapshot(self):
            self.check_cam_status()
            if not self.cam_status:
                return None
            else:
                try:
                    snapshot_url = self.settings.global_get(["webcam", "snapshot"])
                    with closing(requests.get(snapshot_url)) as res:
                        pic = res.content
                    # result = requests.get(self.snapshot_url)
                    # pic = result.content
                    if pic is not None:
                        if self.image_transpose:
                            if Image:
                                buf = StringIO()
                                buf.write(pic)
                                image = Image.open(buf)
                                if self.settings.global_get(["webcam", "flipH"]):
                                    image = image.transpose(Image.FLIP_LEFT_RIGHT)
                                if self.settings.global_get(["webcam", "flipV"]):
                                    image = image.transpose(Image.FLIP_TOP_BOTTOM)
                                if self.settings.global_get(["webcam", "rotate90"]):
                                    image = image.transpose(Image.ROTATE_90)
                                transformed_image = StringIO()
                                image.save(transformed_image, format="jpeg")
                                transformed_image.seek(0, 2)
                                transformed_image.seek(0)
                                pic = transformed_image.read()
                            else:
                                args = ["convert", "-"]
                                if self.settings.global_get(["webcam", "flipV"]):
                                    args += ["-flip"]
                                if self.settings.global_get(["webcam", "flipH"]):
                                    args += ["-flop"]
                                if self.settings.global_get(["webcam", "rotate90"]):
                                    args += ["-rotate", "90"]
                                args += "jpeg:-"
                                p = subprocess.Popen(args, stdin=subprocess.PIPE, stdout=subprocess.PIPE)
                                pic, _ = p.communicate(pic)
                    return pic
                except Exception as e:
                    return None

    def _upload_snapshot(self, machine_id, token):
        pic = self.get_snapshot()
        if not pic:
            return False
        url = "https://api.raise3d.com/octoprod-v1.1/machine/uploadImage"
        data = MultipartEncoder({'file': ('snapshot.jpg', pic), 'machine_id': machine_id})
        headers = {"Content-Type": data.content_type, "Authorization": token}
        try:
            result = requests.post(url=url, data=data, headers=headers)
            data = None  # Free the memory
            status = result.status_code
        except requests.exceptions.HTTPError:
            status = 500
        except requests.exceptions.RequestException:
            status = 500
        if status == 200:
            _logger.info("update snapshot to remote.")
        else:
            _logger.info("update snapshot to remote error.")

    def upload_snapshot(self, machine_id, token):
        if self.cam_status or self.sleep_times % 10 == 0:
            upload_thread = threading.Thread(target=self._upload_snapshot, args=(machine_id, token))
            upload_thread.daemon = True
            upload_thread.start()
        self.sleep_times += 1
