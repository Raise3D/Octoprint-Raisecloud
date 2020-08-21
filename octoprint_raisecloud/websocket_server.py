# coding=utf-8
import ssl
import logging
import websocket
_logger = logging.getLogger('octoprint.plugins.raisecloud')
websocket.enableTrace(False)


class WebsocketServer(object):

    def __init__(self, url, on_server_ws_msg):

        def on_message(ws, message):
            on_server_ws_msg(ws, message)

        def on_error(ws, error):
            # _logger.error("Raisecloud route error ...")
            # _logger.error(error)
            pass

        def on_close(ws):
            _logger.error("Raisecloud route closed ...")

        self.ws = websocket.WebSocketApp(url=url,
                                         on_message=on_message,
                                         on_close=on_close,
                                         on_error=on_error)

    def run(self):
        self.ws.run_forever(sslopt={"cert_reqs": ssl.CERT_NONE})

    def send_text(self, data, ping=False):
        import json
        if self.connected():
            if ping:
                self.ws.send(data)
            else:
                self.ws.send(json.dumps(data))

    def connected(self):
        return self.ws.sock and self.ws.sock.connected

    def disconnect(self):
        self.ws.keep_running = False
        self.ws.close()


if __name__ == "__main__":
    pass
