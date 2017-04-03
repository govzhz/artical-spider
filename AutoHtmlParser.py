import requests
import re
import math
import chardet


class HtmlParser(object):
    """智能网页文章解析类

    影响结果的参数：
        extract_title：标题仅由'_'分割，可以再添加
        extract_content：
            1. 抛弃置信度低于1000的行块（即使最大）
            2. 在上下搜索时，对于行块字符长度低于30的直接抛弃，不进行添加
        get_blocks：
            1. 当前行的正文长度不小于30才将改行设为行块起点
            2. 当前行的正文长度不小于30，且接下去两行行正文长度均小于30才将改行设为行块终点
    """
    def __init__(self):
        # re.I: 忽略大小写，re.S: '.'可以代表任意字符包括换行符
        self._title = re.compile(r'<title>(.*?)</title>', re.I | re.S)  # 匹配标题
        self._keyword = re.compile(r'<\s*meta\s*name="?Keywords"?\s+content="?(.*?)"?\s*[/]?>', re.I | re.S)  # 匹配关键词
        self._description = re.compile(r'<\s*meta\s*name="?Description"?\s+content="?(.*?)"?\s*[/]?>', re.I | re.S)  # 匹配描述
        self._link = re.compile(r'<a(.*?)>|</a>')  # 匹配<a>，</a>标签
        self._link_mark = '|ABC|'  # 标记<a>，</a>  【在extract_content中会删除改标记，所以这里修改，那也得改】
        self._space = re.compile(r'\s+')  # 匹配所有空白字符，包括\r, \n, \t, " "
        self._stopword = re.compile(
            r'备\d+号|Copyright\s*©|版权所有|all rights reserved|广告|推广|回复|评论|关于我们|链接|About|广告|下载|href=|本网|言论|内容合作|法律法规|原创|许可证|营业执照|合作伙伴|备案',
            re.I | re.S)
        self._punc = re.compile(r',|\?|!|:|;|。|，|？|！|：|；|《|》|%|、|“|”', re.I | re.S)
        self._special_list = [(re.compile(r'&quot;', re.I | re.S), '\"'),  # 还原特殊字符
                         (re.compile(r'&amp;', re.I | re.S), '&'),
                         (re.compile(r'&lt;', re.I | re.S), '<'),
                         (re.compile(r'&gt;', re.I | re.S), '>'),
                         (re.compile(r'&nbsp;', re.I | re.S), ' '),
                         (re.compile(r'&#34;', re.I | re.S), '\"'),
                         (re.compile(r'&#38;', re.I | re.S), '&'),
                         (re.compile(r'&#60;', re.I | re.S), '<'),
                         (re.compile(r'&#62;', re.I | re.S), '>'),
                         (re.compile(r'&#160;', re.I | re.S), ' '),
                         ]

    def extract_offline(self, html):
        """离线解析html页面"""
        title = self.extract_title(html)
        description = self.extract_description(html)
        keyword = self.extract_keywords(html)
        content = self.extract_content(html, title)
        return {
            'title': title,
            'description': description,
            'keyword': keyword,
            'content': content
        }

    def extract_online(self, url):
        """在线解析html页面"""
        r = requests.get(url)
        if r.status_code == 200:
            if r.encoding == 'ISO-8859-1':
                r.encoding = chardet.detect(r.content)['encoding']  # 确定网页编码
            html = r.text
            title = self.extract_title(html)
            description = self.extract_description(html)
            keyword = self.extract_keywords(html)
            content = self.extract_content(html, title)
            return {
                'title': title,
                'description': description,
                'keyword': keyword,
                'content': content
            }
        return {}

    def extract_title(self, html):
        """解析文章标题

        :param html: 未处理tag标记的html响应页面
        :return: 字符串，如果没有找到则返回空字符串
        """
        title = self._title.search(html)
        if title: title = title.groups()[0]
        else: return ''
        # 如果标题由'_'组合而成，如"习近平告诉主要负责人改革抓什么_新闻_腾讯网"，则取字数最长的字符串作为标题
        titleArr = re.split(r'_', title)
        newTitle = titleArr[0]
        for subTitle in titleArr:
            if len(subTitle) > len(newTitle):
                newTitle = subTitle
        return newTitle

    def extract_keywords(self, html):
        """解析文章关键词

        :param html: 未处理tag标记的html响应页面
        :return: 字符串，如果没有找到则返回空字符串
        """
        keyword = self._keyword.search(html)
        if keyword: keyword = keyword.groups()[0]
        else: return ''
        # 将\n, \t, \r都转为一个空白字符
        keyword = self._space.sub(' ', keyword)
        return keyword

    def extract_description(self, html):
        """解析文章描述

        :param html: 未处理tag标记的html响应页面
        :return: 字符串，如果没有找到则返回空字符串
        """
        description = self._description.search(html)
        if description: keyword = description.groups()[0]
        else: return ''
        # 将\n, \t, \r都转为一个空白字符
        keyword = self._space.sub(' ', keyword)
        return keyword

    def extract_content(self, html, title):
        """解析正文"""
        lines = self.remove_tag(html)
        blocks = self.get_blocks(lines)
        blockScores = self.block_scores(lines, blocks, title)
        res = ""
        if len(blockScores) != 0:
            maxScore = max(blockScores)
            if maxScore > 1000:  # 置信度低于1000的抛弃
                blockIndex = blockScores.index(maxScore)
                lineStart, lineEnd = blocks[blockIndex]

                # 搜索该行块的下一块，如果出现更大的置信度则加入，否则退出
                nextIndex = blockIndex + 1
                while nextIndex < len(blocks):
                    # 如果区块字符低于30个字符，直接抛弃【这个可以根据需要改变，如果希望尽可能的捕捉所有内容可以注释改行】
                    if self.detBlockLenght(lines, blocks, nextIndex) < 30: break
                    newBlock = (lineStart, blocks[nextIndex][1])
                    score = self.block_scores(lines, [newBlock], title)[0]
                    if score > maxScore:
                        lineEnd = blocks[nextIndex][1]
                        maxScore = score
                    else: break

                # 搜索该行块的上一块，如果出现更大的置信度则加入，否则退出
                lastIndex = blockIndex - 1
                while lastIndex >= 0:
                    # 如果区块字符低于30个字符，直接抛弃【这个可以根据需要改变，如果希望尽可能的捕捉所有内容可以注释改行】
                    if self.detBlockLenght(lines, blocks, nextIndex) < 30: break
                    newBlock = (blocks[lastIndex][0], lineEnd)
                    score = self.block_scores(lines, [newBlock], title)[0]
                    if score > maxScore:
                        lineEnd = blocks[nextIndex][1]
                        maxScore = score
                    else: break

                res += ''.join(lines[lineStart:lineEnd])
                res = re.sub('\|ABC\|(.*?)\|ABC\|', '', res, 0, re.I | re.S)  # 去除<a>内容
        return res

    def detBlockLenght(self, lines, blocks, index):
        """检测区块中字符长度"""
        if len(blocks) <= index: return 0  # 索引越界
        lineStart, lineEnd = blocks[index]
        block = ''.join(lines[lineStart:lineEnd])
        block = re.sub('\|ABC\|(.*?)\|ABC\|', '', block, 0, re.I | re.S)  # 去除<a>内容
        return len(block)

    def get_blocks(self, lines):
        """得到所有含有正文的区块

         - 区块起始点的确定：当前行的正文长度不小于30
         - 区块终点的缺点：当前行的正文长度不小于30，且接下去两行行正文长度均小于30
        :param lines: 输入一个列表，每一项为一行
        :return: 返回一个列表，每一项为一个区块
        """
        linesLen = [len(line) for line in lines]
        totalLen = len(lines)

        blocks = []
        indexStart = 0
        while indexStart < totalLen and linesLen[indexStart] < 30: indexStart += 1
        for indexEnd in range(totalLen):
            if indexEnd > indexStart and linesLen[indexEnd] == 0 and \
                                    indexEnd + 1 < totalLen and linesLen[indexEnd + 1] <= 30 and \
                                    indexEnd + 2 < totalLen and linesLen[indexEnd + 2] <= 30:
                blocks.append((indexStart, indexEnd))
                indexStart = indexEnd + 3
                while indexStart < totalLen and linesLen[indexStart] <= 30: indexStart += 1
        '''
        for s, e in blocks:
            print(''.join(lines[s:e]))
        '''
        return blocks

    def block_scores(self, lines, blocks, title):
        """计算区块的置信度

         - A： 当前区块<a> 标记占区块总行数比例  （标记越多，比例越高）【0.01 - 5】
         - B： 起始位置占总行数的比例 （起始位置越前面越有可能是正文）【0 - 1】
         - C： 诸如广告，版权所有，推广等词汇数占区块总行数比例 【比较大】
         - D： 当前区块中与标题重复的字占标题的比例 【0 - 1】
         - E： 当前区块标点符号占区块总行数比例 【比较大】
         - F:  当前区块去除<a>标签后的正文占区块总行数比例 【比较大】
         - G:  当前区块中文比例 【0 - 1】

         公式： scores = G * F * B * pow(E) * （1 + D） / A / pow(C)

        :param lines: 列表，每一项为一行
        :param blocks: 列表，每一项为一个区块
        :param title: 字符串
        :return: 列表，每一项为一个区块的置信度
        """
        blockScores = []
        for indexStart, indexEnd in blocks:
            blockLinesLen = indexEnd - indexStart + 1.0
            block = ''.join(lines[indexStart:indexEnd])
            cleanBlock = block.replace(self._link_mark, '')

            linkScale = (block.count(self._link_mark) + 1.0) / blockLinesLen
            lineScale = (len(lines) - indexStart + 1.0) / (len(lines) + 1.0)
            stopScale = (len(self._stopword.findall(block)) + 1.0) / blockLinesLen
            titleMatchScale = len(set(title) & set(cleanBlock)) / (len(title) + 1.0)
            puncScale = (len(self._punc.findall(block)) + 1.0) / blockLinesLen
            textScale = (len(cleanBlock) + 1.0) / blockLinesLen
            chineseScale = len(re.findall("[\u4e00-\u9fa5]", block)) / len(block)

            score = chineseScale * textScale * lineScale * puncScale * (1.0 + titleMatchScale) / linkScale / math.pow(stopScale, 0.5)
            blockScores.append(score)
        ''' 输出当前最大置信度的行块
        index = blockScores.index(max(blockScores))
        start, end = blocks[index]
        print(''.join(lines[start:end]))
        print(blockScores)
        '''
        return blockScores

    def remove_tag(self, html):
        """去除html的tag标签

        :param html: 未处理tag标记的html响应页面
        :return: 返回列表，每一项为一行
        """
        for r, c in self._special_list: text = r.sub(c, html)  # 还原特殊字符
        text = re.sub(r'<script(.*?)>(.*?)</script>', '', text, 0,  re.I | re.S)  # 去除javascript
        text = re.sub(r'<!--(.*?)-->', '', text, 0, re.I | re.S)  # 去除注释
        text = re.sub(r'<style(.*?)>(.*?)</style>', '', text, 0, re.I | re.S)  # 去除css
        text = re.sub(r"&.{2,6};|&#.{2,5};", '', text)  # 去除如&nbsp等特殊字符
        # text = re.sub(r"<a(.*?)>(.*?)</a>", '', text, 0, re.S)  # 去除链接标记
        text = re.sub(r'<a(.*?)>|</a>', self._link_mark, text, 0, re.I | re.S)  # 将<a>, </a>标记换为|ATAG|
        text = re.sub(r'<[^>]*?>', '', text, 0, re.I | re.S)  # 去除tag标记
        lines = text.split('\n')
        for lineIndex in range(len(lines)):  # 去除所有空白字符，包括\r, \n, \t, " "
            lines[lineIndex] = re.sub(r'\s+', '', lines[lineIndex])
        return lines


if __name__ == '__main__':
    # http://news.qq.com/  腾讯新闻主页
    # http://news.163.com/ 网易新闻主页
    # 网易新闻某一页
    # http://news.163.com/17/0330/22/CGQD3QLH000189FH.html
    # http://news.163.com/17/0329/00/CGLENELR0001885B.html
    # 腾讯新闻某一页
    # http://news.qq.com/a/20170331/001219.htm
    # 17K小说网主页
    # http://www.17k.com/
    # 17K小说网某一页
    # http://www.17k.com/chapter/2332704/27581745.html
    '''
    urls = [
        'http://news.qq.com/',
        'http://news.163.com/17/0330/22/CGQD3QLH000189FH.html',
        'http://news.163.com/17/0329/00/CGLENELR0001885B.html',
        'http://news.163.com/',
        'http://news.qq.com/a/20170331/001219.htm'
    ]
    '''
    urls = [
        'http://www.17k.com/'
    ]
    parser = HtmlParser()
    for url in urls:
        print(parser.extract_online(url))