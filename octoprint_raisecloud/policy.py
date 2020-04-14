# coding=utf-8
import time


class ReconnectionPolicy(object):

    def __init__(self):
        self.policy = [2, 2, 4, 10, 20, 30, 60, 120, 240, 480, 3600]
        self.retry = -1

    def reset(self):
        self.retry = -1

    def more(self):
        self.retry += 1
        delay = self.policy[self.retry]
        if self.retry > len(self.policy) - 1:
            delay = len(self.policy) - 1
        time.sleep(delay)
