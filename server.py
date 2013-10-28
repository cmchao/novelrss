#!/usr/bin/env python
# -*- coding: utf-8 -*-
import email.utils
import logging
import lxml.html
import os
import pymongo
import PyRSS2Gen
import re
import requests
import sys
import time

def convert_to_rfc822(newtime):
    try:
        tm = time.strptime(newtime, "%Y-%m-%d %H:%M:%S")
        return email.utils.formatdate(time.mktime(tm))
    except :
        return ""

def get_collections():
    """ get default collection from mongodb """
    ### Standard URI format: mongodb://[dbuser:dbpassword@]host:port/dbname
    ### MONGODB_URL is default environemnt variable pass by heroku
    mongodb_url = os.environ.get("MONGODB_URI", "mongodb://localhost:27017/test")
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
                'lastBuildData' : email.utils.formatdate(),
                'first_link' : None,
                'last_link' : None,
                'description' : "un-implemented",
                'post' : {}}

    if not url:
        logging.error("empty url")
        return None

    #get total page number
    url = convert_to_page(url=url, page_num = 1)
    page = get_page(url)
    if not page:
        logging.error("can't get page. '%s', '%d'" % (url, 1))
        return None

    ret_data['first_link'] = url

    page_tree = lxml.html.fromstring(page)
    items = page_tree.xpath("//a[@class = 'last']")
    if not items:
        logging.error("can't find page number")
        return None

    num_str = items[0].text
    for idx, char in enumerate(num_str):
        if char != ".":
            break

    total_page_num = int(num_str[idx:])

    # get all comment on the last page
    url = convert_to_page(url=url, page_num=total_page_num)
    page = get_page(url)
    if not page:
        logging.error("can't get page. '%s', '%d'" % (url, total_page_num))
        return None

    ret_data['last_link'] = url

    page_tree = lxml.html.fromstring(page)

    title_items = page_tree.xpath("//title")
    if not title_items:
        logging.error("can't novel title. '%s'" % (url))

    ret_data['title'] = title_items[0].text.split("-")[0]

    post_items = page_tree.xpath("//td[@class = 't_f']")
    if not post_items:
        logging.error("can't find any comment on last page. '%s'" % (url))

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
            logging.error("can't find related published data. postid '%s', url '%s'" %
                                postid,  url)
        for tag in time_items[0].iterchildren():
            ret_data['post'][postid] = {"title" : post_title,
                                        "pubDate" : convert_to_rfc822(tag.attrib['title']),
                                        "description" : post_content}
            break


    ret_data

    return ret_data


def generate_rss2(novel_data):
    items = []
    for post in novel_data['post'].values():
        items.append(PyRSS2Gen.RSSItem(
                             title=post['title'], link=novel_data['last_link'],
                             description = post['description'], pubDate=post['pubDate'])
                    )

    rss = PyRSS2Gen.RSS2(title=novel_data['title'], lastBuildDate=novel_data['lastBuildData'],
                         link=novel_data['first_link'], description=novel_data['description'],
                         items=items)

    rss.write_xml(open("/tmp/tt.xml", "w"), encoding="utf-8")


def run():
    url = "http://ck101.com/thread-2510702-30-3.html"
    novel_data = parse_page_info(url)
    if not novel_data:
        logging.error("can't parse page '%s'" % (url))

    generate_rss2(novel_data)


if __name__ == "__main__":
    logging.basicConfig(level=logging.INFO, filename="server.log")
    run()
