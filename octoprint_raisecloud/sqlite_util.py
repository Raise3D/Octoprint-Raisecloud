# coding=utf-8
from __future__ import absolute_import, unicode_literals
import sqlite3
import os
import logging

_logger = logging.getLogger('octoprint.plugins.raisecloud')


def exception_wrapper(actual_do):
    def add_robust(*args, **kwargs):
        try:
            return actual_do(*args, **kwargs)
        except Exception as e:
            _logger.error("Exec sql error ...: %s" % e)
            return None

    return add_robust


class SqliteServer(object):

    def __init__(self, plugin):
        self.path = os.path.join(plugin.get_plugin_data_folder(), "raisecloud.sqlite")

    def get_conn(self):
        # 获取数据库连接
        try:
            conn = sqlite3.connect(self.path)
            conn.text_factory = str
            if os.path.exists(self.path) and os.path.isfile(self.path):
                return conn
        except sqlite3.OperationalError as e:
            _logger.error("Connect to sqlite error ...")
            raise e

    def get_cursor(self, conn):
        #  获取数据库的游标对象，参数为数据库的连接对象
        if conn is not None:
            return conn.cursor()
        else:
            return self.get_conn().cursor()

    def close_all(self, conn, cu):
        # 关闭数据库游标对象和数据库连接对象
        try:
            cu.close()
            conn.close()
        except sqlite3.OperationalError as e:
            _logger.error("Close sqlite cur error ...")
            raise e

    def exec_sql(self, sql):
        # 创建数据库表
        if sql is not None and sql != '':
            conn = self.get_conn()
            cu = self.get_cursor(conn)
            cu.execute(sql)
            conn.commit()
            self.close_all(conn, cu)
        else:
            _logger.error('Exec sql [{}] error!'.format(sql))

    def create_table(self, sql):
        # 创建数据库表
        try:
            conn = self.get_conn()
            cu = self.get_cursor(conn)
            cu.execute(sql)
            conn.commit()
            self.close_all(conn, cu)
        except sqlite3.Error as e:
            _logger.error('Create table [{}] error!'.format(sql))
            raise e

    def drop_table(self, table):
        # 如果表存在,则删除表
        try:
            sql = 'DROP TABLE IF EXISTS ' + table
            conn = self.get_conn()
            cu = self.get_cursor(conn)
            cu.execute(sql)
            conn.commit()
            _logger.info('Drop [{}] table success'.format(table))
            cu.close()
            conn.close()
        except sqlite3.Error:
            _logger.error('Drop table [{}] error'.format(table))

    def insert(self, sql, data):
        # 插入数据
        try:
            if data is not None:
                conn = self.get_conn()
                cu = self.get_cursor(conn)
                for d in data:
                    cu.execute(sql, d)
                    conn.commit()
                self.close_all(conn, cu)
        except sqlite3.Error:
            _logger.error('Insert [{}] wrong!'.format(sql))

    def fetchall(self, sql):
        # 查询所有数据
        try:
            conn = self.get_conn()
            cu = self.get_cursor(conn)
            cu.execute(sql)
            r = cu.fetchall()
            if len(r) > 0:
                return r
            self.close_all(conn, cu)
        except sqlite3.Error as e:
            _logger.error('Fetchall [{}] error!'.format(sql))
            _logger.error(e)
            return None

    def fetchone(self, sql, data):
        # 查询一条数据
        try:
            if data is not None:
                d = (data,)
                conn = self.get_conn()
                cu = self.get_cursor(conn)
                cu.execute(sql, d)
                r = cu.fetchall()
                if len(r) > 0:
                    return r[0]
                self.close_all(conn, cu)
        except sqlite3.Error as e:
            _logger.error('Fetchone [{}] error!'.format(sql))
            _logger.error(e)
            return None

    def update(self, sql, data):
        # 更新数据
        try:
            if data is not None:
                conn = self.get_conn()
                cu = self.get_cursor(conn)
                for d in data:
                    cu.execute(sql, d)
                    conn.commit()
                self.close_all(conn, cu)
        except sqlite3.Error as e:
            _logger.error('Update [{}] error!'.format(sql))
            _logger.error(e)

    def delete(self, sql, data):
        # 删除数据
        try:
            if data is not None:
                conn = self.get_conn()
                cu = self.get_cursor(conn)
                for d in data:
                    cu.execute(sql, d)
                    conn.commit()
                self.close_all(conn, cu)
        except sqlite3.Error as e:
            _logger.error('Delete [{}] error!'.format(sql))
            _logger.error(e)

    def init_db(self):
        # 初始化数据库
        create_tb_sql = '''CREATE TABLE IF NOT EXISTS `profile` (
                             `id` int,
                             `user_name` varchar(30),
                             `group_name` varchar(30),
                             `group_owner` varchar(30),
                             `token` varchar(50),
                             `machine_id` varchar(30),
                             `content` varchar(256),
                             `printer_name` varchar(30),
                             `login_status` varchar(30),
                             `task_id` varchar(30),
                             `receive_job` varchar(30)
                           )'''
        try:
            self.create_table(create_tb_sql)
        except sqlite3.Warning as e:
            _logger.error('Delete [{}] error!'.format(create_tb_sql))
            raise e

    def check_user_status(self, user_name):
        result = self.fetchone('SELECT user_name FROM profile WHERE id = ? ', 1)
        return True if result and result[0] == user_name else False

    def update_user_data(self, user_name, group_name, group_owner, token, machine_id, content):
        fetchone_sql = 'SELECT user_name, group_name, group_owner, token, machine_id, content FROM profile WHERE ID = ? '
        query_res = self.fetchone(fetchone_sql, 1)
        if query_res:
            update_sql = 'UPDATE profile SET user_name = ?, group_name = ?, group_owner = ?, token = ?, machine_id = ?, content = ? WHERE id = ?'
            update_data = [(user_name, group_name, group_owner, token, machine_id, content, 1)]
            self.update(update_sql, update_data)
        else:
            insert_sql = '''INSERT INTO profile values (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)'''
            insert_data = [(1, user_name, group_name, group_owner, token, machine_id, content, None, None, None, None)]
            self.insert(insert_sql, insert_data)

    def check_login_status(self):
        fetchone_sql = 'SELECT login_status FROM profile WHERE ID = ? '
        status = self.fetchone(fetchone_sql, 1)
        return status[0] if status else status

    def set_login_status(self, status):
        update_sql = 'UPDATE profile SET login_status = ? WHERE id = ? '
        update_data = [(status, 1)]
        self.update(update_sql, update_data)

    def get_content(self):
        fetchone_sql = 'SELECT content FROM profile WHERE ID = ? '
        content = self.fetchone(fetchone_sql, 1)
        return content[0] if content else content

    def set_content(self, content):
        update_sql = 'UPDATE profile SET content = ? WHERE id = ? '
        update_data = [(content, 1)]
        self.update(update_sql, update_data)

    def delete_content(self):
        update_sql = 'UPDATE profile SET content = ? WHERE id = ? '
        update_data = [(None, 1)]
        self.update(update_sql, update_data)

    def get_user_name(self):
        fetchone_sql = 'SELECT user_name FROM profile WHERE ID = ? '
        user_name = self.fetchone(fetchone_sql, 1)
        return user_name[0] if user_name else user_name

    def get_current_info(self):
        fetchone_sql = 'SELECT user_name, group_name, group_owner FROM profile WHERE ID = ? '
        res = self.fetchone(fetchone_sql, 1)
        return res if res else None
