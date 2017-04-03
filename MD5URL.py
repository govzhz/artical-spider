import hashlib


def MD5(url):
    m = hashlib.md5()
    m.update(url.encode('utf-8'))
    return m.hexdigest()

# print(type(md5('https://www.baidu.com/')))