from sqlalchemy.orm import sessionmaker, scoped_session
from sqlalchemy import create_engine
import json

from CreateTable import Artical


class SQLManager(object):
    def __init__(self):
        with open('data.conf') as json_file:
            mysql = json.load(json_file)['mysql']
            username = mysql['username']
            password = mysql['password']
            host = mysql['host']
            port = mysql['port']
            db = mysql['db']
            engine = create_engine("mysql+pymysql://" + username + ":" + password + "@" +
                                   host + ":" + port + "/" + db + "?charset=utf8", echo=False)
            Session = sessionmaker(bind=engine)
            self.session = scoped_session(Session)

    def insert(self, artical):
        """每个工作者插入数据库"""
        self.session().add(artical)
        self.session().commit()

    def getAllMd5(self):
        """以字典形式返回数据库所有md5"""
        obj = self.session().query(Artical)
        md5Dict = {o.md5: True for o in obj}
        return md5Dict

if __name__ == '__main__':
    sqlManager = SQLManager()
    print(sqlManager.getAllMd5())

