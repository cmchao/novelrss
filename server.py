#!/usr/bin/env python
# -*- coding: utf-8 -*-
from gevent import monkey; monkey.patch_all()

import bottle
import email.utils
import logging
import lxml.html
import os
import pymongo
import PyRSS2Gen
import random
import re
import requests
import sys
reload(sys) 
sys.setdefaultencoding('utf8') 
import tempfile
import time
import traceback

def validate_url(url):
    what = re.search("ck101.com/thread-(\d+)-\d+-\d+.html", url)
    if what:
        return what.group(1)
    else:
        raise Exception("illeage url '%s'" % (url))

def convert_to_rfc822(newtime):
    try:
        tm = time.strptime(newtime, "%Y-%m-%d %H:%M:%S")
        return email.utils.formatdate(time.mktime(tm))
    except :
        return ""

def get_collections():
    """ get default collection from mongodb """
    ### Standard URI format: mongodb://[dbuser:dbpassword@]host:port/dbname
    ### MONGOLAB_URL is default environemnt variable pass by heroku
    mongodb_url = os.environ.get("MONGOLAB_URI", "mongodb://localhost:27017/test")
    client = pymongo.MongoClient(mongodb_url)
    db = client.get_default_database()
    return db['novels']

def convert_to_page(url, page_num):
    """ convert any comment page to its first page """
    what = re.match("http://ck101.com/thread-(\d+)-\d+-\d+.html", url)
    if what:
        url = "http://ck101.com/thread-%s-%d-1.html" % (what.group(1), page_num)
        return url
    else:
        return ""

def get_page(url = None):
    if not url:
        logging.error("empty url")
        return ""

    page = requests.get(url)
    return page.text

def parse_page_info(url = None):
    """ return title : novel_name
               link  : to the last page
               post  : postid_1 : {'title' :
                                   'pubDate' :
                                   'description' : }


    """
    ret_data = {'title' : "un-implemented",
                'lastBuildDate' : email.utils.formatdate(),
                'first_link' : None,
                'last_link' : None,
                'description' : "un-implemented",
                'post' : {}}

    if not url:
        raise Exception("empty url")

    #get total page number
    url = convert_to_page(url=url, page_num = 1)
    page = get_page(url)
    if not page:
        raise Exception("can't get page. '%s', '%d'" % (url, 1))

    ret_data['first_link'] = url

    page_tree = lxml.html.fromstring(page)
    items = page_tree.xpath("//a[@class = 'last']")
    if not items:
        raise Exception("can't find page number")

    num_str = items[0].text
    for idx, char in enumerate(num_str):
        if char != ".":
            break

    total_page_num = int(num_str[idx:])

    # get all comment on the last page
    url = convert_to_page(url=url, page_num=total_page_num)
    page = get_page(url)
    if not page:
        raise Exception("can't get page. '%s', '%d'" % (url, total_page_num))

    ret_data['last_link'] = url

    page_tree = lxml.html.fromstring(page)

    title_items = page_tree.xpath("//title")
    if not title_items:
        raise Exception("can't novel title. '%s'" % (url))

    ret_data['title'] = title_items[0].text.split("-")[0]

    post_items = page_tree.xpath("//td[@class = 't_f']")
    if not post_items:
        raise Exception("can't find any comment on last page. '%s'" % (url))

    for entry in post_items:
        if not entry.text or (entry.text and len(entry.text) < 5):
            for tag in entry.iterdescendants():
                if tag.text and len(tag.text) > 5:
                    post_title = tag.text
        else:
            post_title = entry.text

        post_content = lxml.html.tostring(entry, encoding="utf-8")
        postid = entry.attrib['id'].split("_")[1]

        time_items = page_tree.xpath("//em[@id = 'authorposton%s']" % (postid))
        if not time_items:
            raise Exception("can't find related published data. postid '%s', url '%s'" %
                                postid,  url)
        for tag in time_items[0].iterchildren():
            ret_data['post'][postid] = {"title" : post_title,
                                        "pubDate" : convert_to_rfc822(tag.attrib['title']),
                                        "description" : post_content}
            break

    logging.debug("%s:%s\n%s" % (ret_data['title'], ret_data['last_link'],
                                 ",".join(sorted(ret_data['post'].keys()))))
            
    return ret_data


def generate_rss2(novel_data):
    items = []
    for post_id, post in sorted(novel_data['post'].items(), key=lambda k: k[0]):
        items.append(PyRSS2Gen.RSSItem(
                             title=post['title'], link=novel_data['last_link'],
                             description = post['description'], pubDate=post['pubDate'])
                    )

    logging.debug("generate_rss2: " + novel_data['lastBuildData'])
    rss = PyRSS2Gen.RSS2(title=novel_data['title'], lastBuildDate=novel_data['lastBuildDate'],
                         link=novel_data['first_link'], description=novel_data['description'],
                         items=items)

    return rss.to_xml(encoding="utf-8")

def setup_log():
    log_format="%(asctime)-15s:%(levelname)-8s:%(message)s"
    debug_level=os.environ.get("DEBUG_LEVEL", "info")
    if debug_level == "debug":
        debug_level = logging.DEBUG
    else:
        debug_level = logging.INFO



    if os.environ.get("USE_HEROKU", None):
        logging.basicConfig(level=debug_level,
                            format="%(levelname)-8s:%(message)s",
                            stream=sys.stdout)
    else:
        logging.basicConfig(level=debug_level, format=log_format, filename="server.log")

    requests_log = logging.getLogger("requests")
    requests_log.setLevel(logging.WARNING)

def get_rss(novel_id):
    kUpdatePeriod = int(os.environ.get("REFRASH_SEC", 6 * 60 + random.randint(-10, 10)))
    
    try:
        novels = get_collections()
        novel_data = novels.find_one({"_id" : novel_id})

        do_update = False
        
        if novel_data:
            last_time = time.mktime(email.utils.parsedate(novel_data['lastBuildDate']))
            cur_time = time.mktime(time.gmtime()) 
            if cur_time - last_time > kUpdatePeriod:
                do_update = True

            logging.debug(novel_data['lastBuildData'])
            logging.debug("cur_time : %d,  last_time : %s" % (cur_time, last_time))
        else:
            do_update = True

        if do_update:
            logging.info("update '%s'" % (novel_id))
            url = "http://ck101.com/thread-%s-1-1.html" % (novel_id)
            novel_data = parse_page_info(url)
            novel_data["_id"] = novel_id
            novels.update({'_id':novel_id}, novel_data, upsert=True)

        return generate_rss2(novel_data)
    except Exception as exp:
        logging.error(str(exp))
        logging.error(traceback.format_exc())

#
# web main part
#
@bottle.get('/novel')
@bottle.post('/novel')
def novel_main():
    novel_url = bottle.request.forms.get('novel_url')
    if novel_url:
        logging.info("req : '%s'" % (novel_url))
        novel_id = validate_url(novel_url)
        return bottle.redirect('/novel/%s' % (novel_id))

    else:
        novels = get_collections().find()

        form_str = u'''
            <form action="/novel" method="post">
                ck101 小說網址 (查詢 or 新增) <input name="novel_url" type="text" />
            </form>
        '''

        table_str = "<table>\n"
        for item in novels:
            table_str += u'''
            現有小說
            <tr>
                <td><a href="%s">%s</td>
                <td><a href="novel/%s">rss</td>
            </tr>''' % (item['first_link'], item['title'], item["_id"])

        outstr = "<html><title>ck101 novel rss</title><body>" + \
                form_str + "\n<hr>\n" + table_str + \
                "</body></html>"
        return outstr

@bottle.route('/novel/<novel_id:re:\d+>')
def novel_xml(novel_id):
    rss = get_rss(novel_id)
    fd, filename = tempfile.mkstemp(suffix=".xml")
    os.write(fd, rss)
    os.close(fd)
    logging.info("id:tempfile - %s:%s" % (novel_id, filename))

    return bottle.static_file(os.path.basename(filename), root="/tmp")

if __name__ == "__main__":
    setup_log()

    # foreman default return 5000 as port number
    bottle.run(host='0.0.0.0', port=int(os.environ.get("PORT", 5000)))
