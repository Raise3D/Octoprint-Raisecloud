# coding=utf-8
import os
import time
import json
import hashlib
import logging
import requests
import threading
from webcam import webcam_instance
from websocket_server import WebsocketServer
from printer_manage import PrinterInfo, printer_manager_instance
from sqlite_util import SqliteServer
from policy import ReconnectionPolicy

_logger = logging.getLogger('octoprint.plugins.raisecloud')


class CloudTask(object):

    def __init__(self, plugin):
        self.plugin = plugin
        self.websocket = None
        self.printer = None
        self.printer_info = PrinterInfo(plugin)
        self.printer_manager = printer_manager_instance(plugin)
        self.sqlite_server = SqliteServer(plugin)

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
        fetchone_sql = 'SELECT machine_id FROM profile WHERE ID = ? '
        res = self.sqlite_server.fetchone(fetchone_sql, 1)
        return {"machine_id": res[0]} if res else {}

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
            "raise_touch_version": "1.0.1",
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
            _logger.error("get printer info error ...")

    def on_event(self, state):
        if state == 2:
            # update task_id
            self.printer_manager.task_id = "not_remote_tasks"
            # reboot 消息
            reboot_data = {
                "message_type": 11,
                "machine_id": self._get_machine_id()["machine_id"],
                "token": self._get_token()["token"],
                "data": {
                    "machine_id": self._get_machine_id()["machine_id"],
                    "reboot": True}
            }
            self.websocket.send_text(reboot_data)
            _logger.info("reboot remote raisecloud.")
            return

        if state == 1:
            process_data = {
                "message_type": 1,
                "machine_id": self._get_machine_id()["machine_id"],
                "token": self._get_token()["token"],
                "data": {
                    "machine_id": self._get_machine_id()["machine_id"],
                    "print_progress": "100.00"}
            }
            self.websocket.send_text(process_data)
            _logger.info("remote task printing process completed.")
        if self.printer_manager.task_id == "not_remote_tasks":
            return
        result = {
            "message_type": 3,
            "machine_id": self._get_machine_id()["machine_id"],
            "token": self._get_token()["token"],
            "state": state,
            "data": {
                "task_id": self.printer_manager.task_id,
                "continue_code": "complete",
                "machine_id": self._get_machine_id()["machine_id"],
            }
        }
        _logger.info("remote task printing completed")
        self.websocket.send_text(result)
        # clean up task_id
        self.printer_manager.task_id = "not_remote_tasks"

    def task_event_run(self):
        try:
            self.event_loop()
        except Exception as e:
            _logger.error("task event error...")
            _logger.error(e)

    def event_loop(self):
        policy = ReconnectionPolicy()
        disconnect_status = False
        while True:
            _logger.info("websocket connecting ...")
            try:
                self.websocket = WebsocketServer(url="wss://api.raise3d.com/octo-v1.1/websocket",
                                                 on_server_ws_msg=self._on_server_ws_msg,
                                                 on_client_ws_msg=self._on_client_ws_msg)
                wst = threading.Thread(target=self.websocket.run)
                wst.daemon = True
                wst.start()
                time.sleep(2)

                while self.websocket.connected():
                    status = self.sqlite_server.check_login_status()
                    if status == "logout":
                        _logger.info("user has logged out, websocket is about to disconnect ...")
                        disconnect_status = True
                        self.websocket.disconnect()
                        wst.join()
                        break
                    policy.reset()
                    time.sleep(5)
            finally:
                try:
                    self.websocket.disconnect()
                    if self.sqlite_server.check_login_status() == "logout":
                        break
                except:
                    pass
                policy.more()
            # if disconnect_status:
            #     break

    def _send_heart_beat_event(self):
        index = 0
        while True:
            try:
                if self.websocket.connected():
                    time.sleep(5)
                    index += 1
                else:
                    _logger.info("raisecloud heartbeat over.")
                    break
                if index % 60 == 0:
                    _logger.info("ping to raisecloud.")
                    self.websocket.send_text(data="ping", ping=True)
            except Exception as e:
                _logger.error("socket printer ping error ...")
                _logger.error(e)
                time.sleep(5)

    def _send_printer_info_event(self):
        diff_dict = dict()
        previous_dict = dict()
        while True:
            try:
                if not self.websocket.connected():
                    _logger.info("raisecloud printer info over.")
                    break
                send_data = self._get_send_data()
                tmp_data = send_data["data"]
                if previous_dict:
                    for key, value in send_data["data"].items():
                        if key == "storage_avl_kb" and abs(previous_dict[key] - value) < 1024:
                            continue  # 变化小于1M
                        # profile 更改配置，增加属性nozzle等
                        if key not in previous_dict:
                            diff_dict[key] = value
                            continue
                        if previous_dict[key] != value:
                            diff_dict[key] = value
                    if diff_dict:
                        send_data["data"] = diff_dict
                        send_data["data"].update({"machine_id": self._get_machine_id()["machine_id"]})
                        # 防止网络异常丢失当前状态
                        if "cur_print_state" not in send_data["data"].keys():
                            send_data["data"]["cur_print_state"] = tmp_data["cur_print_state"]
                        #_logger.info("update printer info to raisecloud.")
                        self._send_ws_data(send_data)
                        diff_dict = {}

                else:
                    # _logger.info("update printer info to raisecloud.")
                    self._send_ws_data(send_data)
                previous_dict = tmp_data
                time.sleep(5)
            except Exception as e:
                _logger.error("socket printer info error ...")
                _logger.error(e)
                time.sleep(5)

    def _on_client_ws_msg(self, ws):
        send_heart_beat_thread = threading.Thread(target=self._send_heart_beat_event)
        send_heart_beat_thread.daemon = True
        send_heart_beat_thread.start()

        send_printer_info_thread = threading.Thread(target=self._send_printer_info_event)
        send_printer_info_thread.daemon = True
        send_printer_info_thread.start()

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
                    download_url = mes["data"]["download_url"].encode('utf-8')
                    self.printer_manager.task_id = mes["data"]["task_id"].encode('utf-8')
                    filename = hex_str_2_unicode(mes["data"]["print_file"].encode('utf-8'))  # display name
                    self._load_thread(download_url, filename)
            except Exception as e:
                _logger.error("cloud file printing error ...")
                _logger.error(e)

        if mes["message_type"] == 4:
            # 接受 终止 暂停
            try:
                command = mes["data"]["push_down"].encode('utf-8')
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
                _logger.info("printer pause or resume or stop done.")
                self.websocket.send_text(result)
            except Exception as e:
                _logger.error("printer setting push down error ...")
                _logger.error(e)

        if mes["message_type"] == 5:
            try:
                data = mes["data"]
                if data:
                    invalid = "0.00"
                    if "bed_temp" in data:
                        bed_temp = data["bed_temp"].encode('utf-8')
                        if bed_temp != invalid:
                            self.plugin._printer.set_temperature("bed", int(bed_temp[:-3]))
                    if "nozzle_temp_1" in data:
                        temp_1 = data["nozzle_temp_1"].encode('utf-8')
                        if temp_1 != invalid:
                            self.plugin._printer.set_temperature("tool0", int(temp_1[:-3]))
                    if "nozzle_temp_2" in data:
                        temp_2 = data["nozzle_temp_2"].encode('utf-8')
                        if temp_2 != invalid:
                            self.plugin._printer.set_temperature("tool1", int(temp_2[:-3]))

                    if "flow_rate_1" in data:  # 挤出机挤出速率
                        flow_rate1 = data["flow_rate_1"].encode('utf-8')
                        if flow_rate1 != invalid:
                            self.plugin._printer.change_tool("tool0")
                            self.plugin._printer.flow_rate(int(flow_rate1[:-3]))
                    if "flow_rate_2" in data:
                        flow_rate2 = data["flow_rate_2"].encode('utf-8')
                        if flow_rate2 != invalid:
                            self.plugin._printer.change_tool("tool1")
                            self.plugin._printer.flow_rate(int(flow_rate2[:-3]))

                    if "fan_speed" in data:
                        fan_speed = data["fan_speed"].encode('utf-8')
                        command = "M106 S{}".format(int(fan_speed[:-3]))
                        self.plugin._printer.commands(command)  # args str

                    if "print_speed" in data:  # printer head移动速度
                        feed_rate = data["print_speed"].encode('utf-8')
                        if feed_rate != invalid:
                            self.plugin._printer.feed_rate(int(feed_rate[:-3]))

                    if "jog" in data:
                        jog = data["jog"]
                        if jog:
                            self.plugin._printer.jog(jog)  # args dict

                    if "home" in data:
                        axes = []
                        if "x" in data["home"] and data["home"]["x"].encode('utf-8') == "reset":
                            axes.append("x")
                        if "y" in data["home"] and data["home"]["y"].encode('utf-8') == "reset":
                            axes.append("y")
                        if "z" in data["home"] and data["home"]["z"].encode('utf-8') == "reset":
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
                _logger.info("printer setting parameters done.")
                self.websocket.send_text(result)
            except Exception as e:
                _logger.error("printer setting error,")
                _logger.error(e)

        if mes["message_type"] == 6:
            start = int(mes["data"]["start"])
            length = int(mes["data"]["length"])
            keyword = mes["data"]["keyword"]
            if keyword:
                keyword = keyword.encode('utf-8')
            dir_path = mes["data"]["dir_path"].encode('utf-8')
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
                _logger.info("synchronization file message to remote.")
                self.websocket.send_text(result)
            except Exception as e:
                _logger.error("get file data error ...")
                _logger.error(e)

        if mes["message_type"] == 7:
            if self._get_receive_job()["status"] == "accept":  # 状态为接受状态
                print_file = mes["data"]["print_file"].encode('utf-8').replace("/local/", "")
                try:
                    self.printer_manager.task_id = ""
                    local_abs_path = self.plugin._file_manager.path_on_disk("local", "").encode('utf-8')  # local绝对路径
                    path = os.path.join(local_abs_path, print_file)
                    self.plugin._printer.select_file(path, sd=False, printAfterSelect=True)
                    result = {
                        "message_type": "7",
                        "state": 1,
                        "machine_id": self._get_machine_id()["machine_id"],
                        "data": {
                            "machine_id": self._get_machine_id()["machine_id"]
                        }
                    }
                    _logger.info("printing local files remotely .")
                    self.websocket.send_text(result)

                except Exception as e:
                    _logger.error("start print local file error ...")
                    _logger.error(e)

        if mes["message_type"] == 8:
            try:
                receive = int(mes["data"]["receive_job_set"].encode('utf-8'))
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

                _logger.info("set up remote task acceptance .")
                self.websocket.send_text(reply_message)

            except Exception as e:
                _logger.error("set accept or refuse job error ...")
                _logger.error(e)

        if mes["message_type"] == 10:
            webcam = webcam_instance(self.plugin)
            webcam.upload_snapshot(self._get_machine_id()["machine_id"], self._get_token()["token"])

        if mes["message_type"] == 11:
            try:
                error_code = int(mes["data"]["error_code"])
                if error_code == 5:
                    # 强制下线
                    self.plugin.status = "logout"
                    self.sqlite_server.delete_content()
                    _logger.info("remotely force users to go offline .")
                    self.plugin._logout()

                if error_code == 2:
                    # 刷新token
                    _logger.info("remotely force users to flash token .")
                    token = flash_token(machine_id=self._get_machine_id()["machine_id"])
                    # 写入token
                    if token:
                        self._set_token(token.encode('utf-8'))
            except Exception as e:
                _logger.error(e)


def hex_str_2_unicode(hex_str):
    unicode_str = ""
    for i in range(0, len(hex_str) // 4):
        unichr(int(hex_str[i * 4:i * 4 + 4], 16))
        unicode_str += unichr(int(hex_str[i * 4:i * 4 + 4], 16))
    return unicode_str.encode("utf-8")


def flash_token(machine_id):
    sign, timestamp = get_sign(machine_id)
    body = {"machine_id": machine_id, "timestamp": timestamp, "sign": sign}
    headers = {"content-type": "application/json"}
    url = "https://api.raise3d.com/octo-v1.1/user/getToken"
    result = requests.post(url=url, data=json.dumps(body), headers=headers)
    if result.status_code == 200:
        content = json.loads(result.content)
        token = content["data"]["token"]
        return token
    return None


def get_sign(machine_id):
    key = "f1143856ac3ed6286d2b55e1e0a4419b920ea25b"
    timestamp = int(round(time.time() * 1000))
    machine_id = machine_id
    secrect_key = "key={}&timestamp={}&machine_id={}".format(key, timestamp, machine_id)

    sha1_key = hashlib.sha1()
    sha1_key.update(secrect_key)
    sk = sha1_key.hexdigest()

    md5_key = hashlib.md5()
    md5_key.update(sk)
    ms = md5_key.hexdigest()
    return ms, str(timestamp)
