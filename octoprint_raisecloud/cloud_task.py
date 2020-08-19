# coding=utf-8
from __future__ import absolute_import, unicode_literals
import os
import time
import json
import socket
import hashlib
import logging
import requests
import threading
from .webcam import webcam_instance
from .websocket_server import WebsocketServer
from .printer_manage import PrinterInfo, printer_manager_instance
from .sqlite_util import SqliteServer
from .policy import ReconnectionPolicy

_logger = logging.getLogger('octoprint.plugins.raisecloud')


class CloudTask(object):

    def __init__(self, plugin):
        self.plugin = plugin
        self.websocket = None
        self.printer = None
        self.printer_info = PrinterInfo(plugin)
        self.printer_manager = printer_manager_instance(plugin)
        self.sqlite_server = SqliteServer(plugin)
        self.diff_dict = dict()
        self.previous_dict = dict()

    def _send_ws_data(self, data, message_type=None):
        if not self.websocket:
            return
        try:
            self.websocket.send_text(data)
        except:
            import traceback
            traceback.print_exc()

    def _set_token(self, token):
        """
    status: receive job status
    """
        sql = 'UPDATE profile SET token = ? WHERE id = ? '
        data = [(token, 1)]
        self.sqlite_server.update(sql, data)

    def _get_token(self):
        """
        :return: "{}
        token": cloud_api_token,
        """
        fetchone_sql = 'SELECT token FROM profile WHERE ID = ? '
        res = self.sqlite_server.fetchone(fetchone_sql, 1)
        return {"token": res[0]} if res else {}

    def _get_machine_id(self):
        """
        :return: {}
        "machine_id": machine_id,
        """
        return {"machine_id": str(self.plugin._settings.get(["machine_id"]))}

    def _set_receive_job(self, status):
        """
        status: receive job status
        """
        sql = 'UPDATE profile SET receive_job = ? WHERE id = ? '
        data = [(status, 1)]
        self.sqlite_server.update(sql, data)

    def _get_receive_job(self):
        """
        :return: receive job status  accept or refuse
        """
        sql = 'SELECT receive_job FROM profile WHERE ID = ? '
        res = self.sqlite_server.fetchone(sql, 1)
        return {"status": res[0]} if res and res[0] else {"status": "accept"}

    def _other_info(self):
        """
        :return: {}
        raise_touch_version
        queue_state
        """
        return {
            "raise_touch_version": "1.0.2",
            "queue_state": 1 if self._get_receive_job()["status"] == "accept" else 0,
            "machine_id": self._get_machine_id()["machine_id"],
            "token": self._get_token()["token"]
        }

    def _get_send_data(self):
        """
        send_dict = {
        "message_type": 1,
        "machine_id": machine_id,
        "token": cloud_api_token,
        "data" :
            {
                "machine_id": machine_id,
                "token": cloud_api_token,
                "raise_touch_version": "",
                "queue_state":"",
                self.get_printer_info
            }
        }
        :return: send_dict
        """
        try:
            data = self.printer_info.get_printer_info()
            if self.printer_manager.downloading:
                data["cur_print_state"] = "busy"
            data.update(self._other_info())
            return {
                "message_type": 1,
                "machine_id": self._get_machine_id()["machine_id"],
                "token": self._get_token()["token"],
                "data": data
            }
        except Exception as e:
            _logger.error(e)
            _logger.error("Get printer info error ...")

    def on_event(self, state, continue_code="complete"):
        if state == 2:
            # update task_id
            self.printer_manager.task_id = "not_remote_tasks"
            # reboot 消息
            reboot_data = {
                "message_type": 12,
                "machine_id": self._get_machine_id()["machine_id"],
                "token": self._get_token()["token"],
                "data": {
                    "machine_id": self._get_machine_id()["machine_id"],
                    "reboot": True}
            }
            self.websocket.send_text(reboot_data)
            # _logger.info("send reboot message to cloud {}".format(reboot_data))
            return

        if state == 1:
            process_data = {
                "message_type": 1,
                "machine_id": self._get_machine_id()["machine_id"],
                "token": self._get_token()["token"],
                "data": {
                    "machine_id": self._get_machine_id()["machine_id"],
                    "print_progress": "100.00",
                    "left_time": 0}
            }
            self.websocket.send_text(process_data)
            # _logger.info("send complete process to cloud {}".format(process_data))
        if self.printer_manager.task_id == "not_remote_tasks":
            return
        result = {
            "message_type": 3,
            "machine_id": self._get_machine_id()["machine_id"],
            "token": self._get_token()["token"],
            "state": state,
            "data": {
                "task_id": self.printer_manager.task_id,
                "continue_code": continue_code,
                "machine_id": self._get_machine_id()["machine_id"],
            }
        }
        # _logger.info("send complete message to cloud {}".format(result))
        self.websocket.send_text(result)
        # clean up task_id
        self.printer_manager.task_id = "not_remote_tasks"

    def task_event_run(self):
        try:
            self.event_loop()
        except Exception as e:
            _logger.error("Task event error...")
            _logger.error(e)

    def resolve_addr(self, domain):
        result = socket.getaddrinfo(domain, None)
        return result[0][4][0]

    def event_loop(self):
        last_heartbeat = 0
        policy = ReconnectionPolicy()

        while True:
            _logger.info("Raisecloud connecting ...")
            try:
                addr = "wss://api.raise3d.com/octoprod-v1.1/websocket"
                self.websocket = WebsocketServer(url=addr,
                                                 on_server_ws_msg=self._on_server_ws_msg)
                wst = threading.Thread(target=self.websocket.run)
                wst.daemon = True
                wst.start()
                time.sleep(2)

                while self.websocket.connected():
                    status = self.sqlite_server.check_login_status()
                    if status == "logout":
                        _logger.info("User quit, Raisecloud will disconnect ...")
                        break

                    if time.time() - last_heartbeat > 60:
                        self.send_heartbeat()
                        last_heartbeat = time.time()

                    self.send_printer_info()

                    policy.reset()
                    time.sleep(5)
            finally:
                try:
                    self.websocket.disconnect()
                    # _logger.info("come into finally , current ws status: {}".format(self.websocket.connected()))
                    if self.sqlite_server.check_login_status() == "logout":
                        break
                except:
                    pass

                self.diff_dict = dict()
                self.previous_dict = dict()
                policy.more()

    def send_printer_info(self):
        try:
            send_data = self._get_send_data()
            tmp_data = send_data["data"]
            if self.previous_dict:
                for key, value in send_data["data"].items():
                    if key == "storage_avl_kb" and abs(self.previous_dict[key] - value) < 1024:
                        continue  # 变化小于1M
                    # profile 更改配置，增加属性nozzle等
                    if key not in self.previous_dict:
                        self.diff_dict[key] = value
                        continue
                    if self.previous_dict[key] != value:
                        self.diff_dict[key] = value
                if self.diff_dict:
                    send_data["data"] = self.diff_dict
                    send_data["data"].update({"machine_id": self._get_machine_id()["machine_id"]})
                    # 防止网络异常丢失当前状态
                    if "cur_print_state" not in send_data["data"].keys():
                        send_data["data"]["cur_print_state"] = tmp_data["cur_print_state"]
                    self._send_ws_data(send_data)
                    # _logger.info("current printer info message: {}".format(send_data))
                    self.diff_dict = {}

            else:
                self._send_ws_data(send_data)
                # _logger.info("current printer info message: {}".format(send_data))
            self.previous_dict = tmp_data
        except Exception as e:
            # _logger.error("socket printer info error ...")
            _logger.error(e)

    def send_heartbeat(self):
        try:
            # _logger.info("ping to raisecloud.")
            self.websocket.send_text(data="ping", ping=True)
        except Exception as e:
            # _logger.error("Raisecloud ping error ...")
            _logger.error(e)

    def _load_thread(self, download_url, filename):
        success_data = {
            "state": 1,
            "message_type": 2,
            "machine_id": self._get_machine_id()["machine_id"],
            "token": self._get_token()["token"],
            "data": {
                "task_id": self.printer_manager.task_id,
                "print_state": 1,
                "machine_id": self._get_machine_id()["machine_id"],
            }
        }
        failed_data = {
            "state": 0,
            "message_type": 9,
            "machine_id": self._get_machine_id()["machine_id"],
            "token": self._get_token()["token"],
            "data": {
                "task_id": self.printer_manager.task_id,
                "download_state": 0,
                "machine_id": self._get_machine_id()["machine_id"],
            }
        }
        load_thread = threading.Thread(target=self.printer_manager.load_thread, args=(download_url, filename, success_data, failed_data, self.websocket))
        load_thread.daemon = True
        load_thread.start()

    def _on_server_ws_msg(self, ws, message):
        # 处理远程消息
        # _logger.info("receive message from raisecloud: %s" % message)
        mes = json.loads(message)
        if mes["message_type"] == 2:
            try:
                if self._get_receive_job()["status"] == "accept":  # 状态为接受状态
                    # 多任务时，只处理一个任务
                    if self.printer_manager.downloading or self.plugin._printer.get_state_string() == "Printing":
                        _logger.info("Current task is in progress ...")
                        return

                    download_url = mes["data"]["download_url"]
                    self.printer_manager.task_id = mes["data"]["task_id"]
                    filename = hex_2_str(mes["data"]["print_file"])  # display name
                    self._load_thread(download_url, filename)
            except Exception as e:
                _logger.error("Raisecloud file printing error ...")
                _logger.error(e)

        if mes["message_type"] == 4:
            # 接受 终止 暂停
            try:
                command = mes["data"]["push_down"]
                if command == "pause":
                    self.plugin._printer.pause_print()
                if command == "resume":
                    self.plugin._printer.resume_print()
                if command == "stop":
                    self.plugin._printer.cancel_print()

                result = {
                    "message_type": 4,
                    "state": 1,
                    "machine_id": self._get_machine_id()["machine_id"],
                    "token": self._get_token()["token"],
                    "data": {
                        "machine_id": self._get_machine_id()["machine_id"]
                    }
                }
                # _logger.info("send {} message to cloud: {}".format(command, result))
                self.websocket.send_text(result)
            except Exception as e:
                _logger.error("Raisecloud setting push down error ...")
                _logger.error(e)

        if mes["message_type"] == 5:
            try:
                data = mes["data"]
                if data:
                    invalid = "0.00"
                    if "bed_temp" in data:
                        bed_temp = data["bed_temp"]
                        if bed_temp != invalid:
                            self.plugin._printer.set_temperature("bed", int(bed_temp[:-3]))
                    if "nozzle_temp_1" in data:
                        temp_1 = data["nozzle_temp_1"]
                        if temp_1 != invalid:
                            self.plugin._printer.set_temperature("tool0", int(temp_1[:-3]))
                    if "nozzle_temp_2" in data:
                        temp_2 = data["nozzle_temp_2"]
                        if temp_2 != invalid:
                            self.plugin._printer.set_temperature("tool1", int(temp_2[:-3]))

                    if "flow_rate_1" in data:  # 挤出机挤出速率
                        flow_rate1 = data["flow_rate_1"]
                        if flow_rate1 != invalid:
                            self.plugin._printer.change_tool("tool0")
                            self.plugin._printer.flow_rate(int(flow_rate1[:-3]))
                    if "flow_rate_2" in data:
                        flow_rate2 = data["flow_rate_2"]
                        if flow_rate2 != invalid:
                            self.plugin._printer.change_tool("tool1")
                            self.plugin._printer.flow_rate(int(flow_rate2[:-3]))

                    if "fan_speed" in data:
                        fan_speed = data["fan_speed"]
                        command = "M106 S{}".format(int(fan_speed[:-3]))
                        self.plugin._printer.commands(command)  # args str

                    if "print_speed" in data:  # printer head移动速度
                        feed_rate = data["print_speed"]
                        if feed_rate != invalid:
                            self.plugin._printer.feed_rate(int(feed_rate[:-3]))

                    if "jog" in data:
                        jog = data["jog"]
                        if jog:
                            self.plugin._printer.jog(jog)  # args dict

                    if "home" in data:
                        axes = []
                        if "x" in data["home"] and data["home"]["x"] == "reset":
                            axes.append("x")
                        if "y" in data["home"] and data["home"]["y"] == "reset":
                            axes.append("y")
                        if "z" in data["home"] and data["home"]["z"] == "reset":
                            axes.append("z")
                        self.plugin._printer.home(axes)

                result = {
                    "state": 1,
                    "message_type": 5,
                    "machine_id": self._get_machine_id()["machine_id"],
                    "token": self._get_token()["token"],
                    "data": {
                        "machine_id": self._get_machine_id()["machine_id"],
                    }
                }
                # _logger.info("send printer setting message to cloud: {}".format(result))
                self.websocket.send_text(result)
            except Exception as e:
                _logger.error("Raisecloud setting error...")
                _logger.error(e)

        if mes["message_type"] == 6:
            start = int(mes["data"]["start"])
            length = int(mes["data"]["length"])
            keyword = mes["data"]["keyword"]
            if keyword:
                keyword = keyword
            dir_path = mes["data"]["dir_path"]
            try:
                file_data = self.printer_manager.get_files(path=dir_path, keyword=keyword, start=start, length=length)
                file_data.update({"machine_id": self._get_machine_id()["machine_id"]})
                result = {
                    "state": 1,
                    "message_type": 6,
                    "machine_id": self._get_machine_id()["machine_id"],
                    "token": self._get_token()["token"],
                    "data": file_data
                }
                # _logger.info("send file data message to cloud: {}".format(result))
                self.websocket.send_text(result)
            except Exception as e:
                _logger.error("Raiseclud get file data error ...")
                _logger.error(e)

        if mes["message_type"] == 7:
            if self._get_receive_job()["status"] == "accept":  # 状态为接受状态
                print_file = mes["data"]["print_file"].replace("/local/", "")
                try:
                    self.printer_manager.task_id = ""
                    local_abs_path = self.plugin._file_manager.path_on_disk("local", "")  # local绝对路径
                    path = os.path.join(local_abs_path, print_file)
                    if "\\" in local_abs_path:
                        path = path.replace('/', '\\')
                    self.plugin._printer.select_file(path, sd=False, printAfterSelect=True)
                    result = {
                        "message_type": "7",
                        "state": 1,
                        "machine_id": self._get_machine_id()["machine_id"],
                        "data": {
                            "machine_id": self._get_machine_id()["machine_id"]
                        }
                    }
                    # _logger.info("send print local file message to the cloud: {}".format(result))
                    self.websocket.send_text(result)

                except Exception as e:
                    _logger.error("Raisecloud print local file error ...")
                    _logger.error(e)

        if mes["message_type"] == 8:
            try:
                receive = int(mes["data"]["receive_job_set"])
                self._set_receive_job("accept") if receive else self._set_receive_job("refuse")
                reply_message = {
                    "message_type": 8,
                    "source": 1,
                    "machine_id": self._get_machine_id()["machine_id"],
                    "token": self._get_token()["token"],
                    "data": {
                        "machine_id": self._get_machine_id()["machine_id"],
                        "queue_state": 1 if receive else 0,  # 0禁用 1启用
                    }
                }

                # _logger.info("send accept job message to cloud: {}".format(reply_message))
                self.websocket.send_text(reply_message)

            except Exception as e:
                _logger.error("Raisecloud set receive job error ...")
                _logger.error(e)

        if mes["message_type"] == 9:
            try:
                cancel = int(mes["data"]["cancle_download_set"])
                # 确保下载中才能执行取消操作，
                if cancel and self.printer_manager.downloading:
                    self.printer_manager.cancel = True
                    self.printer_manager.manual = True
                    # 回复消息
                    reply_data = {
                        "state": 1,
                        "message_type": 9,
                        "machine_id": self._get_machine_id()["machine_id"],
                        "token": self._get_token()["token"],
                        "data": {
                            "task_id": self.printer_manager.task_id,
                            "download_state": 1,
                            "machine_id": self._get_machine_id()["machine_id"],
                        }
                    }
                    self.websocket.send_text(reply_data)
                    _logger.info("Raiselcoud cancel downloading file.")
                    # 刷新消息
                    send_data = self._get_send_data()
                    self._send_ws_data(send_data)
                    # _logger.info("cancel download and send all data: {}".format(send_data))

                else:
                    _logger.info("Ineffective operation, no file is downloading.")

            except Exception as e:
                _logger.error("Raisecloud cancel downloading file error ...")
                _logger.error(e)

        if mes["message_type"] == 10:
            webcam = webcam_instance(self.plugin)
            webcam.upload_snapshot(self._get_machine_id()["machine_id"], self._get_token()["token"])

        if mes["message_type"] == 11:
            try:
                error_code = int(mes["data"]["error_code"])
                if error_code == 2:
                    # 刷新token
                    # _logger.info("remotely force users to flash token .")
                    token = self.flash_token(machine_id=self._get_machine_id()["machine_id"])
                    # 写入token
                    if token:
                        self._set_token(token)
                    # 刷新消息
                    send_data = self._get_send_data()
                    send_data["token"] = token
                    send_data["data"]["token"] = token
                    self._send_ws_data(send_data)
                    # _logger.info("flask token and send all data: {}".format(send_data))

                else:
                    # 强制下线, 正常解绑或者团队解散用户删除解绑
                    _logger.info("User logout ...")
                    # 添加区分退出原因
                    error_data = ""
                    self.sqlite_server.set_login_status("logout")
                    self.plugin.status = "logout"
                    self.sqlite_server.delete_content()
                    if error_code == 5:
                        error_data = "Unknown error"
                    if error_code == 6:
                        error_data = "You have unbind in RaiseCloud"
                    if error_code == 7:
                        error_data = "Your team has been disbanded"
                    if error_code == 9:
                        error_data = "User no longer exists"
                    self.plugin.send_event("Logout", data=error_data)
            except Exception as e:
                _logger.error(e)

        if mes["message_type"] == 13:
            data = mes["data"]
            # 远程更改打印机名
            if "printer_name" in data:
                printer_name = mes["data"]["printer_name"]
                self.plugin._settings.set(['printer_name'], printer_name)
                self.plugin._settings.save()
                self.plugin.send_event("ChangeName", printer_name)
                _logger.info("Change printer name success, new name: %s" % printer_name)
            # 远程更改配置文件
            if "profile" in data:
                profile = mes["data"]["profile"]
                self.printer_manager.change_printer_profile(profile)
                self.plugin.send_event("ChangeProfile")
                _logger.info("Change current profile %s" % profile)

    def flash_token(self, machine_id):
        sign, timestamp = self.get_sign(machine_id)
        content = self.sqlite_server.get_content()
        body = {"machine_id": machine_id, "timestamp": timestamp, "sign": sign, "content": content}
        headers = {"content-type": "application/json"}
        url = "https://api.raise3d.com/octoprod-v1.1/user/getToken"
        result = requests.post(url=url, data=json.dumps(body), headers=headers)
        if result.status_code == 200:
            data = json.loads(result.content)
            token = data["data"]["token"]
            return token
        _logger.error("Get token error.")
        return None

    @staticmethod
    def get_sign(machine_id):
        key = "f1143856ac3ed6286d2b55e1e0a4419b920ea25b"
        timestamp = int(round(time.time() * 1000))
        machine_id = machine_id
        secrect_key = "key={}&timestamp={}&machine_id={}".format(key, timestamp, machine_id)

        sha1_key = hashlib.sha1()
        sha1_key.update(secrect_key.encode('utf-8'))
        sk = sha1_key.hexdigest()

        md5_key = hashlib.md5()
        md5_key.update(sk.encode('utf-8'))
        ms = md5_key.hexdigest()
        return ms, timestamp

    def notify(self):
        if self.printer_manager.task_id == "not_remote_tasks" or not self.printer_manager.task_id:

            notify_data = {
                "state": 1,
                "message_type": 2,
                "machine_id": self._get_machine_id()["machine_id"],
                "token": self._get_token()["token"],
                "data": {
                    "task_id": "",
                    "print_state": 1,
                    "machine_id": self._get_machine_id()["machine_id"],
                }
            }

            # _logger.info("notify start print local file: {}".format(notify_data))
            self.websocket.send_text(notify_data)


def hex_2_str(hex_str):
    unicode_str = ""
    try:
        for i in range(0, len(hex_str) // 4):
            unicode_str += unichr(int(hex_str[i * 4:i * 4 + 4], 16))
    except NameError:
        from future.builtins import chr
        for i in range(0, len(hex_str) // 4):
            unicode_str += chr(int(hex_str[i * 4:i * 4 + 4], 16))
    return unicode_str



