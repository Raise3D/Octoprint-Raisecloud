# coding=utf-8
import json
import uuid
import base64
import logging
import requests
from Crypto.Cipher import AES


_logger = logging.getLogger('octoprint.plugins.raisecloud')


class RaiseCloud(object):

    def __init__(self):
        self.endpoint = "https://api.raise3d.com/octoprod-v1.1"
        self.url = "/user/keyLogin"
        self.machine_id = self.get_machine_id()
        self.machine_type = "other"

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

    def login_cloud(self, content):
        body = {
            "machine_id": str(self.machine_id),
            "machine_type": self.machine_type,
            "key": content
        }
        url = "{}{}".format(self.endpoint, self.url)
        result = requests.post(url=url, json=body, verify=True)
        if result.status_code == 200:
            data = json.loads(result.text)
            state = data["state"]  # state 0-绑定到达上线， 1-正常返回token， 3-用户名密码不匹配
            message = data["msg"].encode('utf-8')
            if state == 1:
                token = data["data"]["token"].encode('utf-8')
                group_name = data["data"]["group_name"].encode('utf-8')
                if data["data"]["team_owner"]:
                    group_owner = data["data"]["team_owner"].encode('utf-8')
                else:
                    group_owner = ""
                return {"state": 1, "msg": message, "token": token, "group_name": group_name,
                        "machine_id": self.machine_id, "group_owner": group_owner}
            return {"state": state, "msg": message}
        else:
            return {"state": -1, "msg": "Login error"}


class Util(object):
    @staticmethod
    def allowed_file(filename):
        return '.' in filename and filename.rsplit('.', 1)[1].lower() in ["raisepem"]

    @staticmethod
    def decrypt(content):
        if content:
            key = 'raiseqwertyuiopa'
            decode = base64.b64decode(content)
            cryptor = AES.new(key.encode("utf8"), AES.MODE_ECB)
            plain_text = cryptor.decrypt(decode)
            unpad = lambda s: s[0:-ord(s[-1:])]
            data = json.loads(bytes.decode(unpad(plain_text)))
            return {"user_name": data["user_name"]}
        return {"user_name": ""}

    def access_key(self, file_name, file_path):
        """
        :return: content  user_name
        """
        try:
            if self.allowed_file(file_name):
                with open(file_path, 'r') as load_f:
                    content = json.load(load_f)["content"].encode('utf-8')  # to bytes
                    content = str.encode(content)
                    result = self.decrypt(content)
                    return result["user_name"].encode('utf-8'), content
            return "", ""
        except Exception as e:
            _logger.error(e)
            return "", ""


def get_access_key(file_name, file_path):
    util = Util()
    return util.access_key(file_name, file_path)
