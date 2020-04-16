# coding=utf-8
import os
import re
import time
import socket
import requests
import urlparse
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
    def unicode_2_hex_str(unicde_str):
        if not isinstance(unicde_str, unicode):
            unicde_str = unicode(unicde_str, "utf-8")
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
            if state == "Printing":
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
            _logger.error("get printer state error ...")
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
                        job_info["print_file"] = self.unicode_2_hex_str(data["job"]["file"]["display"].encode('utf-8'))
                if data["progress"]["completion"]:
                    job_info["print_progress"] = ('%.2f' % (int(data["progress"]["completion"])))
                if data["progress"]["printTimeLeft"]:  # 如果存在printTimeLeft，则有printTime
                    job_info["left_time"] = data["progress"]["printTimeLeft"]
                    job_info["print_time_count"] = data["progress"]["printTimeLeft"] + data["progress"]["printTime"]
            return job_info
        except Exception as e:
            _logger.error(e)
            _logger.error("get printer job file error ...")
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
            _logger.error("get printer temperature error ...")
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
            _logger.error("get printer profile error ...")
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
                tmp = urlparse.urlparse(webcam_url)
                webcam["video_url"] = "http://" + self.get_ip_addr() + webcam_url if not tmp.scheme else webcam_url
                webcam["cur_camera_state"] = "connected"
            return webcam
        except Exception as e:
            _logger.error(e)
            _logger.error("get printer webcam error ...")
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
            _logger.error("get printer storage error ...")
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
            _logger.error("get printer name error ...")
            return {"machine_name": ""}

    def get_printer_info(self):
        return dict(self.printer_state().items() + self.job_file().items() +
                    self.printer_temperature().items() + self.printer_profile().items() +
                    self.printer_webcam().items() + self.printer_storage().items() +
                    self.printer_name().items())


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
        self.delete_flag = False
        self.task_id = "not_remote_tasks"

    def change_printer_profile(self, new_profile):
        """
        new_profile = {
                          "volume": {depth": 300}
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
            _logger.error("Could not save profile: %s" % str(e))
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
                "file_type": "dir" if content_data["typePath"][0].encode('utf-8') == "folder" else "file",
                "file_name": content_data["display"].encode('utf-8'),
                "real_name": content_data["name"].encode('utf-8'),
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
            _logger.info("start print file .")
        else:
            # 下载文件失败
            websocket.send_text(failed_data)
            _logger.info("download remote file error .")
            self.task_id = "not_remote_tasks"

    def load_and_start(self, download_url, filename):
        self.downloading = True
        try:
            download_file_path = download_zip_file(download_url, self.zip_url, self.unzip_url)
            self.downloading = False
            if download_file_path:
                self.delete_flag = True
                file_object = octoprint.filemanager.util.DiskFileWrapper(filename=filename,
                                                                         path=download_file_path)
                self.plugin._file_manager.add_file("local", filename, file_object,
                                                   allow_overwrite=True)

                canonPath, canonFilename = self.plugin._file_manager.canonicalize('local', filename,)
                local_path = self.plugin._file_manager.sanitize_path("local", canonPath)  # local绝对路径
                display_name = self.plugin._file_manager.sanitize_name("local", canonFilename)  # display name

                select_path = os.path.join(local_path, display_name)
                self.plugin._printer.select_file(select_path, sd=False, printAfterSelect=True)
                return True
            return False
        except Exception as e:
            self.downloading = False
            _logger.error("load and select file for printing error ...")
            _logger.error(e)
            return False
        finally:
            # 清理解压文件
            import shutil
            shutil.rmtree(self.unzip_url)

    def clean_file(self, clean_file):
        canonPath, canonFilename = self.plugin._file_manager.canonicalize('local', clean_file)
        local_path = self.plugin._file_manager.sanitize_path("local", canonPath)  # local绝对路径
        display_name = self.plugin._file_manager.sanitize_name("local", canonFilename)  # display name
        select_path = os.path.join(local_path, display_name)
        self.plugin._printer.unselect_file(select_path, sd=False, printAfterSelect=True)
        self.plugin._file_manager.remove_file(destination="local", path=clean_file)
        self.delete_flag = False
        _logger.info("clean file %s success ..., " % clean_file)


def timestamp_2_str(timestamp):
    try:
        return time.strftime('%Y-%m-%d %H:%M:%S', time.localtime(timestamp))
    except Exception as e:
        _logger.info("timestamp to strtime error.")
        return ""


def download_zip_file(download_url, zip_url, unzip_url):
    if not os.path.exists(unzip_url):
        os.makedirs(unzip_url)
    if not os.path.exists(zip_url):
        os.makedirs(zip_url)
    compress_path = os.path.join(zip_url, 'tmp.tar.gz')
    gcode_name = ""

    status = retry_download(3, download_url, compress_path)
    if not status:
        return status
    _logger.info("download file success. ")
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
        _logger.error("tar file open error.")
        _logger.error(e)
        return False
    finally:
        # 清理压缩文件
        os.remove(compress_path)


def retry_download(retry_times, download_url, compress_path):
    status = False
    while retry_times > 0:
        status = retry(download_url, compress_path)
        if status:
            break
        retry_times -= 1
    return status


def retry(download_url, compress_path):
    try:
        r = requests.get(download_url, stream=True, timeout=(10.0, 60.0))
        if r.status_code == 200:
            with open(compress_path, "wb") as compress_file:
                for chunk in r.iter_content(chunk_size=100000):  # 100kb
                    compress_file.write(chunk)
        return True
    except Exception as e:
        _logger.info("retry download，status code {}, error: {}".format(r.status_code, e))
        os.remove(compress_path)
        return False
