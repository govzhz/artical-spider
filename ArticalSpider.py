import logging
import os
import re
import json
import time
import random
import pickle

import chardet
import gevent.monkey
import requests
from gevent.pool import Pool
from gevent.event import Event
from gevent.queue import Queue, Empty, Full
gevent.monkey.patch_all()

from AutoHtmlParser import HtmlParser
from CreateTable import Artical
from MD5URL import MD5
from SQLManager import SQLManager

# logging config ----------
logging.basicConfig(level=logging.INFO,
          format='%(asctime)s %(filename)s[line:%(lineno)d] %(levelname)s %(message)s',
          datefmt='%a, %d %b %Y %H:%M:%S',
          filename='Debug.log',
          filemode='a')
logger = logging.getLogger('ArticalSpider')
hdr = logging.StreamHandler()
formatter = logging.Formatter('[%(asctime)s] %(name)s:%(levelname)s: %(message)s')
hdr.setFormatter(formatter)
logger.addHandler(hdr)
# logging config ----------


class ArticalSpider(object):
    """协程捕捉URL爬虫并解析html，将结果存入数据库
    maxsize: 队列存储的最大值（默认为1000）
    poolSize：协程池最大同时激活greenlet个数（默认为5个）
    """
    def __init__(self):
        self.evt = Event()  # 等待初始化
        self.initConfig()  # 初始化配置文件
        self.initModules()  # 初始化模块

        self.q = Queue(maxsize=self.maxsize)  # 有界队列
        self.initQueue()  # 初始化队列

        self.crawlUrlsCount = 0  # 统计搜到的链接的个数
        self.crawlerID = 0  # 协程ID标志
        self.pool = Pool(self.poolSize)  # 协程池
        self.isInitializeCompletely = False  # 是否初始化完成

        self.startTime = None  # 爬虫启动时间

    def initModules(self):
        """初始化模块"""
        logger.info('Initializing modules...')
        self.htmlParser = HtmlParser()  # 加载智能解析模块
        self.sqlManager = SQLManager()  # 加载数据库模块
        logger.info('Reading url md5 from mysql...')
        self.urlDict = self.sqlManager.getAllMd5()  # 加载已解析URL字典

    def initConfig(self):
        """读取配置文件信息"""
        logger.info('Initializing config...')
        with open('data.conf') as json_file:
            data = json.load(json_file)
            self.maxsize = data['maxUrlQueueSize']  # URL队列最大存储值
            self.poolSize = data['poolSize']  # 协程池最大同时激活greenlet个数
            self.fileName = data['urlQueueFileName']  # 队列url的保存文件名
            self.startUrls = data['startUrls']  # 队列初始化url
            self.filterUrlsRegular = data['filterUrlsRegular']  # 过滤的url
            self.saveTime = data['saveTime']  # 队列url定时保存到本地文件

    def initQueue(self):
        """初始化队列，提供起始url列表

        :param urls: url列表
        :return:
        """
        self.loadLastUrlQueue()
        for url in self.startUrls[:self.maxsize]:
            self.q.put(url)
        self.isInitializeCompletely = True
        self.evt.set()

    def loadLastUrlQueue(self):
        """加载上次保存的队列url"""
        logger.info('Initializing queue...')
        hasLastUrls = False
        if not os.path.exists(self.fileName): return hasLastUrls
        with open(self.fileName, 'rb') as f:
            for url in pickle.load(f)[:self.maxsize - 100]:
                hasLastUrls = True
                self.q.put(url.strip())  # 注意把空格删除
        return hasLastUrls

    def getCrawlUrlsCount(self):
        """返回已捕捉到的URL数量"""
        return self.crawlUrlsCount

    def getQueueSize(self):
        """返回当前队列中URL数量"""
        return self.q.qsize()

    def saveQueueUrls(self):
        """将队列内容拷贝到文件"""
        # 拷贝队列进行遍历
        logger.info('Save queue urls')
        with open(self.fileName, 'wb') as f:
            urls = list(self.q.queue)
            pickle.dump(urls, f)

    def crawlURL(self, crawlerID):
        """每个工作者，搜索新的url"""
        # 为了减少协程的切换，每个新建的工作者会不断查找URL，直到队列空或满
        # 实际上因为有界队列的原因，协程仍然会不断切换
        while True:
            if not self.isInitializeCompletely:  # 还未初始化完成则等待
                self.evt.wait()
            # 定时保存队列数据，以便下次恢复
            if time.time() - self.startTime > self.saveTime:
                self.saveQueueUrls()
                self.startTime = time.time()

            gevent.sleep(random.uniform(0, 1))  # 防止爬取频率过快
            try:
                url = self.q.get(timeout=0.1)  # 当队列空时自动释放当前greenlet
                md5_url = MD5(url)
                if md5_url in self.urlDict: continue  # 如果已存在则抛弃
                self.urlDict[md5_url] = True  # 加入字典

                headers = {
                    'User-Agent': 'Mozilla/5.0 (Windows NT 10.0; WOW64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/56.0.2924.87 Safari/537.36',
                }
                r = requests.get(url, timeout=5, headers=headers)
                if r.status_code == 200:
                    if r.encoding == 'ISO-8859-1':
                        charset = self.detCharset(r.text)
                        if charset != "" and charset.lower() in ['utf-8', 'gb2312', 'gbk']: r.encoding = charset
                        else: r.encoding = chardet.detect(r.content)['encoding']  # 确定网页编码

                    # 插入数据库
                    self.insertMysql(r.text, url, MD5(url))

                    # 寻找下一个url
                    for link in re.findall('<a[^>]+href="(http.*?)"', r.text):
                        if len(self.filterUrlsRegular) != 0:
                            for filterUrl in self.filterUrlsRegular:
                                if filterUrl in link:
                                    # 仅当队列中元素小于最大队列个数添加当前url到队列
                                    self.q.put(link.strip(), timeout=0.1)  # 当队列满时自动释放当前greenlet
                                    self.crawlUrlsCount += 1
                                    break
                        else:
                            if len(link.strip()) != 0:
                                self.q.put(link.strip(), timeout=0.1)
                                self.crawlUrlsCount += 1

                else:
                    logger.warning('Request error status: ' + str(r.status_code) + ': ' + url)
                    # 这里可以进行重连（这里不写了）

            except Empty:  # q.get()时队列为空异常
                # logger.info('URL Queue is Empty! URLSpider-' + str(crawlerID) + ': stopping crawler...')
                break
            except Full:  # q.put()时队列为满异常
                # logger.info('URL Queue is Full! URLSpider-' + str(crawlerID) + ': stopping crawler...')
                break
            except requests.exceptions.ConnectionError:  # 连接数过高，程序休眠
                logger.warning('Connection refused')
                time.sleep(3)
            except requests.exceptions.ReadTimeout:  # 超时
                logger.warning('Request readTimeout')
                # 接下去可以尝试重连，这里不写了

    def insertMysql(self, html, url, md5):
        """将解析结果插入队列"""
        parseDict = self.htmlParser.extract_offline(html)
        content = parseDict['content']
        description = parseDict['description']
        keyword = parseDict['keyword']
        title = parseDict['title']
        # 插入数据库
        if content != "":
            self.sqlManager.insert(Artical(content=content, title=title, keyword=keyword, description=description, url=url, md5=md5))
            logger.info('Insert Mysql: ' + url)

    def detCharset(self, html):
        """检测网页编码"""
        charsetPattern = re.compile('<\s*meta[^>]*?charset=["]?(.*?)"?\s*[/]>?', re.I | re.S)
        charset = charsetPattern.search(html)
        if charset: charset = charset.groups()[0]
        else: charset = ""
        return charset

    def run(self):
        """开启协程池，运行爬虫，在队列中无url时退出捕获"""
        if self.q.qsize() == 0:
            logger.error('Please init Queue first (Check your .conf file)')
            return
        logger.info('Starting crawler...')
        self.startTime = time.time()
        while True:
            # 当没有任何协程在工作，且队列中无url时退出捕获
            if self.q.empty() and self.pool.free_count() == self.poolSize:
                break

            # 每次创建和队列中url个数一样的协程数
            # 如果协程池所能同时工作的协程数小于url个数，则创建协程池所能同时工作的最大协程数
            # 保证协程池总是在最多激活greenlet数状态
            for _ in range(min(self.pool.free_count(), self.q.qsize())):
                self.crawlerID += 1
                self.pool.spawn(self.crawlURL, self.crawlerID)

            # 切换协程（因为只在遇到I/O才会自动切换协程）
            gevent.sleep(0.1)
        logger.warning('All crawler stopping...')


if __name__ == '__main__':
    urlSpider = ArticalSpider()
    urlSpider.run()