# coding=utf-8
from __future__ import absolute_import, unicode_literals
import time


class ReconnectionPolicy(object):

    def __init__(self):
        self.policy = [2, 2, 4, 10, 20, 30, 60, 120]
        self.retry = -1

    def reset(self):
        self.retry = -1

    def more(self):
        self.retry += 1
        if self.retry > len(self.policy) - 1:
            delay = self.policy[-1]
        else:
            delay = self.policy[self.retry]
        time.sleep(delay)
