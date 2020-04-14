# coding=utf-8
from __future__ import absolute_import
import time
import socket
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
        self.clean_file = None

    def send_event(self, event, data=None):
        event = {'event': event, 'data': data}
        self._plugin_manager.send_plugin_message(self._plugin_name, event)

    def get_settings(self):
        return self._settings

    def get_settings_defaults(self):
        printer_name = socket.gethostname()

        return dict(
            printer_name=printer_name,
        )

    def get_template_vars(self):

        return dict(
            printer_name=self._settings.get(["printer_name"])
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
        if self._settings.get(["printer_name"]) == socket.gethostname():
            profile = self._printer_profile_manager.get_current_or_default()
            self._settings.set(['printer_name'], profile["name"] + "-" + profile["model"])
            self._settings.save()
        self.sqlite_server = SqliteServer(self)
        self.sqlite_server.init_db()
        # check
        content = self.sqlite_server.get_content()
        if content:
            user_name = self.sqlite_server.get_user_name()
            result = self._login(user_name, content)
            if result["status"] == "success":
                self.status = "login"
                self._logger.info("user: %s login success ..." % user_name)

    def on_event(self, event, payload):
        if not hasattr(self, 'cloud_task'):
            return

        if event in [Events.PRINT_DONE, Events.PRINT_FAILED]:
            # 完成消息
            state = 1 if event == Events.PRINT_DONE else 0
            self.cloud_task.on_event(state)
            # 完成文件
            self.clean_file = payload["name"].decode("utf-8")

        if event == Events.CONNECTED:
            # reboot消息
            self._logger.info("notify remote reboot ...")
            self.cloud_task.on_event(state=2)

        if event == Events.PRINTER_STATE_CHANGED:
            if payload["state_id"] == "OPERATIONAL":
                printer_manger = printer_manager_instance(self)
                if printer_manger.delete_flag:
                    # 清理文件
                    printer_manger.clean_file(self.clean_file)
                    printer_manger.delete_flag = False

    def _task_event(self):
        self.cloud_task = CloudTask(self)
        self.cloud_task.task_event_run()

    def websocket_connect(self):
        try:
            self.main_thread = threading.Thread(target=self._task_event)
            self.main_thread.daemon = True
            self.main_thread.start()
        except Exception:
            import traceback
            traceback.print_exc()

    def websocket_disconnect(self):
        try:
            if self.main_thread:
                self.main_thread.join()
        except Exception:
            import traceback
            traceback.print_exc()

    def _ws_alive(self):
        if hasattr(self.main_thread, 'isAlive'):
            status = self.main_thread.isAlive()
            #self._logger.info("Websocket isAlive : (%s)" % status)
            return status
        return False

    def _login(self, user_name, content):
        rc = RaiseCloud()
        data = rc.login_cloud(content)
        if data["state"] == 1:
            # 更新信息
            self.sqlite_server.update_user_data(user_name, data["group_name"], data["group_owner"], data["token"], data["machine_id"], content)
            self.sqlite_server.set_login_status("login")
            printer_name = self._settings.get(["printer_name"])
            if not self._ws_alive():  # 再次登录
                self.websocket_connect()
            return {"status": "success", "user_name": user_name, "group_name": data["group_name"], "group_owner": data["group_owner"],
                    "printer_name": printer_name, "msg": data["msg"]}
        return {"status": "failed", "msg": data["msg"]}

    def _logout(self):
        self.sqlite_server.set_login_status("logout")
        # if self._ws_alive():  # 再次退出
        #     self.websocket_disconnect()
        self._disconnect()
        self.send_event("Logout")

    def _disconnect(self):
        if self._ws_alive():  # 再次退出
            self.disconnect_thread = threading.Thread(target=self.websocket_disconnect)
            self.disconnect_thread.daemon = True
            self.disconnect_thread.start()

    @octoprint.plugin.BlueprintPlugin.route("/login", methods=["GET", "POST"])
    @admin_permission.require(403)
    def login_cloud(self):
        if request.method == "POST":
            data = request.form.to_dict(flat=False)
            file_path = data["file.path"][0].encode('utf-8')
            file_name = data["file.name"][0].encode('utf-8')
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
        self._logout()
        self.status = "logout"
        self.sqlite_server.delete_content()
        self._logger.info("user logout ...")
        result = {"status": "logout"}
        time.sleep(2)
        return jsonify(result), 200, {'ContentType': 'application/json'}

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
            printer_name = request.json["printer_name"].encode('utf-8')
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
                user="Reachy",
                repo="Octoprint-Raisecloud",
                current=self._plugin_version,
                pip="https://github.com/ReachY/Octoprint-Raisecloud/archive/{target_version}.zip"
            )
        )


__plugin_name__ = "RaiseCloud"


def __plugin_load__():
    global __plugin_implementation__
    __plugin_implementation__ = RaisecloudPlugin()

    global __plugin_hooks__
    __plugin_hooks__ = {
        "octoprint.plugin.softwareupdate.check_config": __plugin_implementation__.get_update_information
    }
