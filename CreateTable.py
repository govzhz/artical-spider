from sqlalchemy.ext.declarative import declarative_base
from sqlalchemy import Column, create_engine, VARCHAR
import json

Base = declarative_base()


def creteTable():
    """创建所有表"""
    with open('data.conf') as json_file:
        mysql = json.load(json_file)['mysql']
        username = mysql['username']
        password = mysql['password']
        host = mysql['host']
        port = mysql['port']
        db = mysql['db']

        # mysql+pymysql://<username>:<password>@<host>/<dbname>[?<options>] 【pymysql】
        # mysql+mysqldb://<user>:<password>@<host>[:<port>]/<dbname>  【MySQL-Python】
        # http://docs.sqlalchemy.org/en/latest/dialects/index.html --> mysql --> *
        engine = create_engine("mysql+pymysql://" + username + ":" + password + "@" +
                               host + ":" + port + "/" + db + "?charset=utf8", echo=True)
        Base.metadata.create_all(engine)


# 用户表
class Artical(Base):
    __tablename__ = 'artical'

    # id = Column(Integer, primary_key=True)
    content = Column(VARCHAR(10000))
    title = Column(VARCHAR(500))
    description = Column(VARCHAR(500))
    keyword = Column(VARCHAR(500))
    url = Column(VARCHAR(500))
    md5 = Column(VARCHAR(32), primary_key=True)

    def __repr__(self):
        return '<md5=%s, url=%s>' % (self.md5, self.url)

creteTable()
