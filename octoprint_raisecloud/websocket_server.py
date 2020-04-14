# coding=utf-8
import logging
import websocket
_logger = logging.getLogger('octoprint.plugins.raisecloud')
websocket.enableTrace(False)


class WebsocketServer(object):

    def __init__(self, url, on_server_ws_msg, on_client_ws_msg):

        def on_message(ws, message):
            on_server_ws_msg(ws, message)

        def on_open(ws):
            on_client_ws_msg(ws)

        def on_error(ws, error):
            _logger.error("websocket server error ...")

        def on_close(ws):
            _logger.info("websocket closed ...")

        self.ws = websocket.WebSocketApp(url=url,
                                         on_message=on_message,
                                         on_open=on_open,
                                         on_close=on_close,
                                         on_error=on_error)

    def run(self):
        self.ws.run_forever()

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
