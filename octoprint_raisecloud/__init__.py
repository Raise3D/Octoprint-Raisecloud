# coding=utf-8
from __future__ import absolute_import
import time
import uuid
import logging
import threading
import octoprint.plugin
from flask import render_template, request, jsonify
from octoprint.events import Events
from octoprint.server import admin_permission
from .printer_manage import printer_manager_instance, PrinterInfo
from .cloud_task import CloudTask
from .sqlite_util import SqliteServer
from .raisecloud import RaiseCloud, get_access_key

_logger = logging.getLogger('octoprint.plugins.raisecloud')


class RaisecloudPlugin(octoprint.plugin.StartupPlugin,
                       octoprint.plugin.TemplatePlugin,
                       octoprint.plugin.SettingsPlugin,
                       octoprint.plugin.AssetPlugin,
                       octoprint.plugin.EventHandlerPlugin,
                       octoprint.plugin.BlueprintPlugin):

    def __init__(self):
        self.main_thread = None
        self.status = None
        self.cancelled = False

    def get_settings(self):
        return self._settings

    def get_settings_defaults(self):
        printer_name = None
        machine_id = None

        return dict(
            printer_name=printer_name,
            machine_id=machine_id,
            machine_type="other"
        )

    def get_template_vars(self):

        return dict(
            printer_name=self._settings.get(["printer_name"]),
            machine_id=self._settings.get(["machine_id"]),
            machine_type=self._settings.get(["machine_type"])
        )

    def get_template_configs(self):
        return [
            dict(type="settings", custom_bindings=True)
        ]

    def get_assets(self):
        return dict(
            js=["js/raisecloud.js"],
            css=["css/raisecloud.css"]
        )

    def on_after_startup(self):
        self.set_printer_identity()
        self.sqlite_server = SqliteServer(self)
        self.sqlite_server.init_db()
        # check
        self.check_user_info()

    def on_event(self, event, payload):

        if event == Events.FIRMWARE_DATA:
            if "MACHINE_TYPE" in payload["data"]:
                machine_type = payload["data"]["MACHINE_TYPE"]
                self._logger.info("get printer types: {}".format(machine_type))
                self._settings.set(['machine_type'], machine_type)
                self._settings.save()

        if not hasattr(self, 'cloud_task'):
            return

        if event == Events.PRINT_STARTED:
            self.cloud_task.notify()

        if event == Events.PRINT_CANCELLED:
            self.cancelled = True

        if event == Events.PRINT_DONE:
            # 完成消息
            self.cloud_task.on_event(state=1)

        if event == Events.CONNECTED:
            # reboot消息
            self._logger.info("notify remote reboot ...")
            self.cloud_task.on_event(state=2)

        if event == Events.PRINTER_STATE_CHANGED:
            if payload["state_id"] == "OPERATIONAL":
                # cancelled 的任务状态变为operational时，发送完成消息
                if self.cancelled:
                    self.cloud_task.on_event(state=0, continue_code="stop")
                    self.cancelled = False
                printer_manager = printer_manager_instance(self)
                printer_manager.clean_file()

    def task_event(self):
        self.cloud_task = CloudTask(self)
        self.cloud_task.task_event_run()

    def websocket_connect(self):
        try:
            self.main_thread = threading.Thread(target=self.task_event)
            self.main_thread.daemon = True
            self.main_thread.start()
        except Exception:
            import traceback
            traceback.print_exc()

    def ws_alive(self):
        if hasattr(self.main_thread, 'isAlive'):
            status = self.main_thread.isAlive()
            self._logger.info("Websocket isAlive : (%s)" % status)
            return status
        return False

    def _login(self, user_name, content):
        rc = RaiseCloud(self._settings.get(["machine_id"]), self._settings.get(["printer_name"]), self._settings.get(["machine_type"]))
        data = rc.login_cloud(content)
        if data["state"] == 1:
            # 更新信息
            self.sqlite_server.update_user_data(user_name, data["group_name"], data["group_owner"], data["token"], data["machine_id"], content)
            self.sqlite_server.set_login_status("login")
            printer_name = self._settings.get(["printer_name"])
            if not self.ws_alive():  # 再次登录
                self.websocket_connect()
            return {"status": "success", "user_name": user_name, "group_name": data["group_name"], "group_owner": data["group_owner"],
                    "printer_name": printer_name, "msg": data["msg"]}
        return {"status": "failed", "msg": data["msg"]}

    @octoprint.plugin.BlueprintPlugin.route("/login", methods=["GET", "POST"])
    @admin_permission.require(403)
    def login_cloud(self):
        if request.method == "POST":
            data = request.form.to_dict(flat=False)
            file_path = data["file.path"][0]
            file_name = data["file.name"][0]
            user_name, content = get_access_key(file_name, file_path)   # 解密文件
            if content:
                result = self._login(user_name, content)
                if result["status"] == "success":
                    self.status = "login"
                    self._logger.info("user: %s login success ..." % user_name)
                    return jsonify(result), 200, {'ContentType': 'application/json'}

                self._logger.info("user: %s login failed ..." % user_name)
                return jsonify(result), 200, {'ContentType': 'application/json'}
            return jsonify({"status": "failed", "msg": "Binding key file error !"}), 200, {'ContentType': 'application/json'}
        return render_template('raisecloud_settings.jinja2')

    @octoprint.plugin.BlueprintPlugin.route("/logout", methods=["POST"])
    @admin_permission.require(403)
    def logout(self):
        self.sqlite_server.set_login_status("logout")
        self.status = "logout"
        self.sqlite_server.delete_content()
        self._logger.info("user logout ...")
        time.sleep(1)
        return jsonify({"status": "logout"}), 200, {'ContentType': 'application/json'}

    @octoprint.plugin.BlueprintPlugin.route("/status", methods=["GET"])
    @admin_permission.require(403)
    def login_status(self):
        self._logger.info("user current status %s" % self.status)
        if self.status == "login":
            res = self.sqlite_server.get_current_info()
            if res:
                user_name, group_name, group_owner = res
                printer_name = self._settings.get(["printer_name"])
                return jsonify({"status": "login", "user_name": user_name,
                                "printer_name": printer_name, "group_name": group_name,
                                "group_owner": group_owner}), 200, {'ContentType': 'application/json'}

        return jsonify({"status": "logout"}), 200, {'ContentType': 'application/json'}

    @octoprint.plugin.BlueprintPlugin.route("/printer", methods=["POST"])
    @admin_permission.require(403)
    def change_name(self):
        if self.status == "login":
            printer_name = request.json["printer_name"]
            self._settings.set(['printer_name'], printer_name)
            self._settings.save()
            self._logger.info("change printer name success, new name: %s" % printer_name)
            return jsonify({"status": "success"}), 200, {'ContentType': 'application/json'}
        self._logger.info("change printer name failed ...")
        return jsonify({"status": "failed", "msg": "user has logged out"}), 200, {'ContentType': 'application/json'}

    def get_update_information(self):
        return dict(
            raisecloud=dict(
                displayName="RaiseCloud",
                displayVersion=self._plugin_version,
                type="github_release",
                user="Raise3D",
                repo="Octoprint-Raisecloud",
                current=self._plugin_version,
                pip="https://github.com/Raise3D/Octoprint-Raisecloud/archive/{target_version}.zip"
            )
        )

    def send_event(self, event, data=None):
        event = {'event': event, 'data': data}
        self._plugin_manager.send_plugin_message(self._plugin_name, event)

    @staticmethod
    def get_machine_id():
        mac = uuid.UUID(int=uuid.getnode()).hex[-12:]
        mac_add = ":".join([mac[e:e + 2] for e in range(0, 11, 2)])
        tmp = []
        for i in mac_add.split(':'):
            tmp.append(i)
        new_tmp = "%s%s%s%s%s%s" % tuple(tmp)
        machine_id = int(new_tmp, 16)
        return machine_id

    def set_printer_identity(self):
        # save printer name
        if not self._settings.get(["printer_name"]):
            self._settings.set(['printer_name'], "Default")
            self._settings.save()
        # save machine id
        if not self._settings.get(["machine_id"]):
            self._settings.set(['machine_id'], self.get_machine_id())
            self._settings.save()

    def check_user_info(self):
        content = self.sqlite_server.get_content()
        if content:
            user_name = self.sqlite_server.get_user_name()
            result = self._login(user_name, content)
            if result["status"] == "success":
                self.status = "login"
                self._logger.info("user: %s login success ..." % user_name)
                self.send_event("Login")


__plugin_name__ = "RaiseCloud"
__plugin_pythoncompat__ = ">=2.7,<4"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = RaisecloudPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }
