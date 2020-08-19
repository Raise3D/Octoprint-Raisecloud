# coding=utf-8
from __future__ import absolute_import, unicode_literals
import os
import re
import time
import socket
import requests
# Python2/3 compatiabile import
try:
    from urllib.parse import urlparse
except ImportError:
    from urlparse import urlparse
import tarfile
import logging
import psutil
import octoprint.filemanager.util
from octoprint.util import dict_merge
from octoprint.printer.profile import InvalidProfileError, CouldNotOverwriteError, SaveError

_logger = logging.getLogger('octoprint.plugins.raisecloud')


class PrinterInfo(object):
    def __init__(self, plugin):
        self.plugin = plugin
        self._settings = plugin.get_settings()

    @staticmethod
    def hex_2_str(unicde_str):
        hex_str = ""
        for i in range(0, len(unicde_str)):
            hex_str += (hex(ord(unicde_str[i])).replace('0x', '').zfill(4))
        return hex_str.upper()

    @staticmethod
    def get_ip_addr():
        try:
            s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
            s.connect(('8.8.8.8', 80))
            ip = s.getsockname()[0]
        finally:
            s.close()

        return ip

    def printer_state(self):
        """
        :return: {}
        printer match state
        """
        try:
            state = self.plugin._printer.get_state_string()
            trans_state = "busy"  # 在连接中途匹配不到以下状态，故设置无法判断时为busy
            if state == "Printing" or "Printing from SD":
                trans_state = "running"
            if state == "Paused":
                trans_state = "paused"
            if state == "Operational":
                trans_state = "idle"
            if state in ["Cancelling", "Pausing", "Resuming"]:
                trans_state = "busy"
            if state == "Ready":
                trans_state = "ready"
            if state in ["Error", "CLOSED_WITH_ERROR", "UNKNOWN", "NONE"]:
                trans_state = "error"
            if state == "Offline":
                trans_state = "offline"
            return {"cur_print_state": trans_state}
        except Exception as e:
            _logger.error(e)
            _logger.error("Get printer state error ...")
            return {"cur_print_state": "error"}

    def job_file(self):
        """
        :return: {}
        print_file
        print_progress
        print_time_count
        left_time
        """
        job_info = {
            "print_file": "",
            "print_progress": "",
            "print_time_count": "",
            "left_time": ""
        }
        try:
            data = self.plugin._printer.get_current_data()
            if data:
                if "display" in data["job"]["file"]:  # display在打印机断开或没有加载时不存在
                    if data["job"]["file"]["display"]:
                        job_info["print_file"] = self.hex_2_str(data["job"]["file"]["display"])
                if data["progress"]["completion"]:
                    job_info["print_progress"] = ('%.2f' % (int(data["progress"]["completion"])))
                if data["progress"]["printTimeLeft"]:  # 如果存在printTimeLeft，则有printTime
                    job_info["left_time"] = data["progress"]["printTimeLeft"]
                    job_info["print_time_count"] = data["progress"]["printTimeLeft"] + data["progress"]["printTime"]
            return job_info
        except Exception as e:
            _logger.error(e)
            _logger.error("Get printer job error ...")
            return job_info

    def printer_temperature(self):
        """
        :return: {}
        nozzle_num nozzle_temp_1 bed_temp
        nozzle_temp_1_goal  bed_temp_goal
        """
        nozzle_num = self._profile()["extruder"]["count"]
        temperature_info = {
            "nozzle_num": nozzle_num,
            "nozzle_temp_1": "",
            "nozzle_temp_1_goal": "",
            "bed_temp": "",
            "bed_temp_goal": ""
        }
        try:
            data = self.plugin._printer.get_current_temperatures()
            if data:
                temperature_info["nozzle_temp_1"] = int(round(data["tool0"]["actual"]))
                temperature_info["nozzle_temp_1_goal"] = int(round(data["tool0"]["target"]))
                temperature_info["bed_temp"] = int(round(data["bed"]["actual"]))
                temperature_info["bed_temp_goal"] = int(round(data["bed"]["target"]))

                if nozzle_num == 2:
                    if "tool1" in data:
                        temperature_info["nozzle_temp_2"] = int(round(data["tool1"]["actual"]))
                        temperature_info["nozzle_temp_2_goal"] = int(round(data["tool1"]["target"]))
                    else:
                        temperature_info["nozzle_temp_2"] = ""
                        temperature_info["nozzle_temp_2_goal"] = ""
            return temperature_info
        except Exception as e:
            _logger.error(e)
            _logger.error("Get temperature error ...")
            return temperature_info

    def _profile(self):
        return self.plugin._printer_profile_manager.get_current_or_default()

    def printer_profile(self):
        """
        :return: {}
        machine_dim_x machine_dim_y machine_dim_z
        nozzle_size_1 nozzle_size_2
        """
        volume_and_nozzle_info = {
            "machine_dim_x": "",
            "machine_dim_y": "",
            "machine_dim_z": "",
            "nozzle_size_1": "",
        }
        try:
            data = self._profile()
            if data:
                volume_and_nozzle_info["machine_dim_x"] = int(data["volume"]["width"])
                volume_and_nozzle_info["machine_dim_y"] = int(data["volume"]["depth"])
                volume_and_nozzle_info["machine_dim_z"] = int(data["volume"]["height"])
                volume_and_nozzle_info["nozzle_size_1"] = data["extruder"]["nozzleDiameter"]
                if self._profile()["extruder"]["count"] == 2:
                    volume_and_nozzle_info["nozzle_size_2"] = data["extruder"]["nozzleDiameter"]
            return volume_and_nozzle_info
        except Exception as e:
            _logger.error(e)
            _logger.error("Get profile error ...")
            return volume_and_nozzle_info

    def printer_webcam(self):
        """
        :return: {}
        cur_camera_state
        video_url
        """
        webcam = {
            "cur_camera_state": "disconnected",
            "video_url": ""
        }
        # snapshot_url = self._settings.global_get(["webcam", "snapshot"])
        # camera_url = self._settings.global_get(["webcam", "stream"])
        # cur_camera_state = get_cam_status(camera_url, snapshot_url)
        # if cur_camera_state:
        #     webcam["cur_camera_state"] = "connected"

        try:
            webcam_url = self._settings.global_get(["webcam", "stream"])
            if webcam_url:  # 判断webcam url 是否为Octopi 默认配置
                tmp = urlparse(webcam_url)
                webcam["video_url"] = "http://" + self.get_ip_addr() + webcam_url if not tmp.scheme else webcam_url
                webcam["cur_camera_state"] = "connected"
            return webcam
        except Exception as e:
            _logger.error(e)
            _logger.error("Get webcam error ...")
            return webcam

    def printer_storage(self):
        """
        :return: {}
        storage_avl_kb
        storage_total_kb
        """
        storage = {
            "storage_avl_kb": "",
            "storage_total_kb": ""
        }
        try:
            storage_address = self._settings.getBaseFolder("uploads", check_writable=False)
            usage = psutil.disk_usage(storage_address)
            free = usage.free
            total = usage.total
            storage["storage_avl_kb"] = int(int(free) / 1024)
            storage["storage_total_kb"] = int(int(total) / 1024)
            return storage
        except Exception as e:
            _logger.error(e)
            _logger.error("Get storage error ...")
            return storage

    def printer_name(self):
        """
        :return: {}
        {"machine_name": "name-model"}
        """
        try:
            printer_name = self._settings.get(["printer_name"])
            return {"machine_name": printer_name}
        except Exception as e:
            _logger.error(e)
            _logger.error("Get printer name error ...")
            return {"machine_name": ""}

    def machine_type(self):
        """
        :return: {}
        {"printer_type": "name-model"}
        """
        try:
            machine_type = self._settings.get(["machine_type"])
            return {"machine_type": machine_type}
        except Exception as e:
            _logger.error(e)
            _logger.error("Get printer type error ...")
            return {"printer_type": ""}

    @staticmethod
    def merge_dicts(*dict_args):
        result = {}
        for dictionary in dict_args:
            result.update(dictionary)
        return result

    def get_printer_info(self):
        return self.merge_dicts(self.printer_state(), self.job_file(), self.printer_temperature(),
                                self.printer_profile(), self.printer_webcam(),
                                self.printer_storage(), self.printer_name(), self.machine_type())


def get_cam_status(camera_url, snapshot_url):
    if snapshot_url and camera_url:
        try:
            result = requests.get(snapshot_url)
            if result.status_code == 200:
                return True
        except:
            return False


# singleton
_instance = None


def printer_manager_instance(plugin):
    global _instance
    if _instance is None:
        _instance = PrinterManager(plugin)
    return _instance


class PrinterManager(object):
    def __init__(self, plugin):
        self.plugin = plugin
        self.zip_url = os.path.join(self.plugin.get_plugin_data_folder(), "compress")
        self.unzip_url = os.path.join(self.plugin.get_plugin_data_folder(), "uncompress")
        self.downloading = False
        self.task_id = "not_remote_tasks"
        self.cancel = False
        self.manual = False
        self.folder = "RaiseCloud-File"

    def change_printer_profile(self, new_profile):
        """
        new_profile = {
                          "volume": {depth": 300},
                          "extruder": {'count': 1, 'nozzleDiameter': 0.66, 'offsets': [(0.0, 0.0)], 'sharedNozzle': False}
                      }
        """
        profile = self.plugin._printer_profile_manager.get_current_or_default()
        merged_profile = dict_merge(profile, new_profile)
        try:
            self.plugin._printer_profile_manager.save(merged_profile, allow_overwrite=True, make_default=False)
        except InvalidProfileError:
            _logger.error("Profile is invalid")
            return False
        except CouldNotOverwriteError:
            _logger.error("Profile already exists and overwriting was not allowed")
            return False
        except Exception as e:
            _logger.error("Could not save profile")
            _logger.error(e)
            return False
        return True

    def get_files(self, path, keyword=None, start=0, length=5):
        # 之前传的是以/local开头的绝对路径
        if path == "/local":
            path = ""
        else:
            path = path.replace("/local/", "")

        data = self.plugin._file_manager.list_files(path=path, filter=None, recursive=False)
        # 获取dir_path下所有文件列表
        if not data:
            return {
                "file_list_count": 0,
                "start": start,
                "file_list": []
            }

        # 所有文件排序， 先文件夹，后文件，按字母顺序排
        final_list = []
        dir_sort_list = []
        file_sort_list = []
        for content_data in data["local"].values():
            detail = {
                "file_type": "dir" if content_data["typePath"][0] == "folder" else "file",
                "file_name": content_data["display"],
                "real_name": content_data["name"],
                "last_modified_time": timestamp_2_str(content_data["date"]) if "date" in content_data else "",
                "file_size": content_data["size"] if "size" in content_data else ""
            }
            if detail["file_type"] == "dir":
                dir_sort_list.append(detail)  # 文件夹
            else:
                file_sort_list.append(detail)  # 文件

        if dir_sort_list:
            dir_sort_list.sort(key=lambda x: x["real_name"].lower())
        if file_sort_list:
            file_sort_list.sort(key=lambda x: x["real_name"].lower())

        # filter 关键字过滤查询, 不区分大小写，支持中文
        if keyword:
            if dir_sort_list:
                for key1 in dir_sort_list:
                    if re.search(keyword, key1["file_name"], re.IGNORECASE) or \
                            re.search(keyword, key1["real_name"], re.IGNORECASE):
                        final_list.append(key1)
            if file_sort_list:
                for key2 in file_sort_list:
                    if re.search(keyword, key2["file_name"], re.IGNORECASE) or \
                            re.search(keyword, key2["real_name"], re.IGNORECASE):
                        final_list.append(key2)
        else:
            final_list.extend(dir_sort_list)
            final_list.extend(file_sort_list)

        file_list_count = len(final_list)
        # 根据 start length 返回数据   0-5   5-10   10-15
        return_data = final_list[start: start + length]

        result_data = {
            "file_list_count": file_list_count,
            "start": start,
            "file_list": return_data
        }
        return result_data

    def load_thread(self, download_url, filename, success_data, failed_data, websocket):
        load_status = self.load_and_start(download_url, filename)
        if load_status:
            websocket.send_text(success_data)
            # _logger.info("send a print start message to cloud: {}".format(success_data))
        else:
            # 下载文件失败
            if not self.manual:
                websocket.send_text(failed_data)
                # _logger.info("send download remote file error message to cloud: {}".format(failed_data))
            self.manual = False
            self.task_id = "not_remote_tasks"

    def check_folder_exists(self, create=False):
        raisecloud_folder = self.plugin._file_manager.path_on_disk("local", self.folder)
        if not os.path.exists(raisecloud_folder):
            if create:
                self.plugin._file_manager.add_folder("local", self.folder)
            return False
        return True

    def load_and_start(self, download_url, filename):
        self.downloading = True
        try:
            download_file_path = self.download_zip_file(download_url, self.zip_url, self.unzip_url)
            self.downloading = False
            if download_file_path:
                self.check_folder_exists(create=True)
                file_object = octoprint.filemanager.util.DiskFileWrapper(filename=filename,
                                                                         path=download_file_path)
                canonPath, canonFilename = self.plugin._file_manager.canonicalize("local", filename)
                futurePath = self.plugin._file_manager.sanitize_path("local", self.folder)  # uploads/Raisecloud-File
                futureFilename = self.plugin._file_manager.sanitize_name("local", canonFilename)
                futureFullPath = self.plugin._file_manager.join_path("local", futurePath,
                                                                     futureFilename)  # uploads/Raisecloud-File/filename
                futureFullPathInStorage = self.plugin._file_manager.path_in_storage("local",
                                                                                    futureFullPath)  # Raisecloud-File/filename

                added_file = self.plugin._file_manager.add_file("local", futureFullPathInStorage, file_object,
                                                                allow_overwrite=True, display=canonFilename)

                absFilename = self.plugin._file_manager.path_on_disk("local", added_file)
                self.plugin._printer.select_file(absFilename, sd=False, printAfterSelect=True)

                return True
            return False
        except Exception as e:
            self.downloading = False
            _logger.error("Load and select file for printing error ...")
            _logger.error(e)
            return False
        finally:
            # 清理解压文件
            import shutil
            shutil.rmtree(self.unzip_url)

    def get_current_file(self):
        current_job = self.plugin._printer.get_current_job()
        if current_job is not None and "file" in current_job.keys() and "path" in current_job["file"] and "origin" in current_job["file"]:
            return current_job["file"]["origin"], current_job["file"]["path"]
        else:
            return None, None

    def is_busy(self, target, path):
        currentOrigin, currentPath = self.get_current_file()
        if currentPath is not None and currentOrigin == target and self.plugin._file_manager.file_in_path("local", path, currentPath) and (self.plugin._printer.is_printing() or self.plugin._printer.is_paused()):
            return True

        return any(target == x[0] and self.plugin._file_manager.file_in_path("local", path, x[1]) for x in self.plugin._file_manager.get_busy_files())

    def clean_file(self):
        # 文件不存在，不清理
        if not self.check_folder_exists():
            return
        clean_folder = self.plugin._file_manager.sanitize_path('local', self.folder)  # uploads/Raisecloud-File
        size = get_dir_size(clean_folder)
        if size >= 500:  # 500M
            data = self.plugin._file_manager.list_files(path=self.folder, filter=None, recursive=False)
            if not data:
                return
            clean_file_name = None
            key = data["local"].keys()[0]
            last_print_time = data["local"][key]["history"][-1]["timestamp"] if "history" in data["local"][key] else \
                data["local"][key]["date"]
            for detail in data["local"].values():
                tmp_time = detail["history"][-1]["timestamp"] if "history" in detail else detail["date"]
                if tmp_time <= last_print_time:
                    clean_file_name = detail["name"]
                    last_print_time = tmp_time
            clean_file = os.path.join(self.folder + "/{}".format(clean_file_name))
            # clean_file = os.path.join("Raisecloud-File", clean_file_name)

            if self.is_busy("local", clean_file):
                _logger.info("Trying to delete a file that is currently in use: %s" % clean_file)
                return
            # deselect the file if it's currently selected
            currentOrigin, currentPath = self.get_current_file()
            if currentPath is not None and currentOrigin == "local" and clean_file == currentPath:
                self.plugin._printer.unselect_file()
            self.plugin._file_manager.remove_file("local", clean_file)
            _logger.info("Clean RaiseCloud file success.")

    def download_zip_file(self, download_url, zip_url, unzip_url):
        if not os.path.exists(unzip_url):
            os.makedirs(unzip_url)
        if not os.path.exists(zip_url):
            os.makedirs(zip_url)
        compress_path = os.path.join(zip_url, 'tmp.tar.gz')
        gcode_name = ""

        status = self.retry_download(3, download_url, compress_path)
        self.cancel = False
        if not status:
            _logger.info("Download file failed.")
            return status
        _logger.info("Download file success. ")
        try:
            tar = tarfile.open(compress_path, "r:gz")
            download_file_names = tar.getnames()
            for value in download_file_names:
                if str(value).endswith(".gcode"):
                    gcode_name = str(value)
            tar.extract(gcode_name, unzip_url)
            tar.close()

            download_path = os.path.join(unzip_url, gcode_name)
            return download_path
        except Exception as e:
            _logger.error("Open file error.")
            _logger.error(e)
            return False
        finally:
            # 清理压缩文件
            os.remove(compress_path)

    def retry_download(self, retry_times, download_url, compress_path):
        # retry 上行retry消息
        status = False
        if self.cancel:
            return False
        while retry_times > 0:
            status = self.retry(download_url, compress_path)
            if status:
                break
            if self.cancel:
                break
            retry_times -= 1
            _logger.info("An error occurred, retry download.")
        return status

    def retry(self, download_url, compress_path):
        try:
            r = requests.get(download_url, stream=True, timeout=(10.0, 60.0))
            if r.status_code == 200:
                with open(compress_path, "wb") as compress_file:
                    for chunk in r.iter_content(chunk_size=100000):  # 100kb
                        if self.cancel:
                            # os.remove(compress_path)
                            return False
                        compress_file.write(chunk)
            return True
        except Exception as e:
            _logger.info("Download file from remote error.")
            _logger.error(e)
            # os.remove(compress_path)
            return False


def timestamp_2_str(timestamp):
    try:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
    except Exception as e:
        _logger.info("timestamp to strtime error.")
        return ""


def get_dir_size(folder):
    import os
    from os.path import join, getsize
    size_long = 0
    for root, dirs, files in os.walk(folder):
        size_long += sum([getsize(join(root, name)) for name in files])
    return size_long / 1024 / 1024  # MB
