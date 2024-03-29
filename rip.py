#!python



# Licensed under the Apache License, Version 2.0. So is yomou.py



# Requires a modern version of Python 3.

# Note: This tool scrapes each story's normal HTML pages, rather than using the txtdownload feature ( https://ncode.syosetu.com/txtdownload/top/ncode/108715/ ).
# This is becaue the txtdownload feature seems to have a much rougher rate limit than the normal HTML pages.
# It also requires login cookies to function, and the way the ncode is encoded is different (e.g. n8725k becomes 108715).
# Like working against individual HTML pages, it has to be done one chapter at a time, too.
# It would, actually, be ideal to get things from the txtdownload function instead of scraping HTML.
# The txtdownload function gives you special markup before it's converted to HTML, like so: "『|さまよえる剣《ワンダリング・ソード》』"

# Narou has a real API, but it does not allow downloading chapter text. https://dev.syosetu.com/man/man/ https://dev.syosetu.com/man/api/

# Narou also has an API for generating a PDF from an entire novel. https://pdfnovels.net/n8725k/



# Number of chapters to download before stopping and syncing the database / sleeping to enforce local rate limit. Should not have a significant impact on speed unless it goes below limit_connections or is so high that you get ratelimited by narou.
# default is 25
limit_chapters_at_once = 25
# Local ratelimit. Reduce this if you get ratelimited by narou.
# default is 10
chapters_per_second = 10

# Simultaneous connection limit, reduce this if opening too many connections at once is getting you ratelimited or causing other problems.
# default is 25
limit_connections = 25


# try to recover from ratelimits gracefully by waiting this many seconds.
# should be large enough that limit_chapters_at_once chapters per wait_if_ratelimited seconds is 100% definitely below the rate limit.
# default is 10
wait_if_ratelimited = 10

# Disable this if you need to be 100% certain that each individual chapter's update time is checked. Enable it for a small speed boost when doing minor updates.
# default is True
enable_per_novel_datetime_check = True
# Same but for per-chapter update time. You do not want to set this. Use --deletedatetimedata instead.
# default is True
enable_per_chapter_datetime_check = True

# Depending on how far you are from japan and how bad your internet is
# Values that are too low make connections get reset often and make it more likely to get rate limited
# Value that are too high make the scraper get "stuck" for long periods of time if a connection silently disappears or is randomly very slow
# default is 8
chapter_timeout = 8

html_header = """<!doctype html>
<html lang="ja">
<head>
<title>TITLE</title>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<link rel="stylesheet" href="narourip.css">
</head>
<body>
"""

html_footer = """
</body>
</html>"""

def sanitize_fs_name(text):
    if text == None:
        return ""
    mapping = [
      ('/', '／' ),
      ('\\', '＼' ),
      ('?', '？' ),
      ('%', '％' ),
      ('*', '＊' ),
      (':', '：' ),
      ('|', '｜' ),
      ('"', '”' ),
      ('<', '＜' ),
      ('>', '＞' )
    ]
    for m in mapping:
        text = text.replace(m[0], m[1])
    return re.sub(' +', ' ', text)

from bs4 import BeautifulSoup
import urllib
from urllib.parse import urljoin
import sys
import json
import time

sys.stdout.reconfigure(encoding='utf-8')

import aiohttp
import asyncio

import shutil
import os
import os.path
import re

import html
def html_escape(text):
    if text == None:
        return ""
    return html.escape(text, quote=True)
def url_escape(text):
    if text == None:
        return ""
    return urllib.parse.quote(text)

import sqlite3

database = sqlite3.connect("naroudb.db")
c = database.cursor()

c.execute("CREATE table if not exists narou (ncode text, title text, chapcode text, chapter int, chaptitle text, datetime text, content text)")
c.execute("CREATE unique index if not exists idx_chapcode on narou (chapcode)")

c.execute("CREATE table if not exists ranks (ncode text, rank text, datetime text)")
c.execute("CREATE unique index if not exists idx_ncode on ranks (ncode)")

c.execute("CREATE table if not exists volumes (ncode text, title text, volcode text, volume int, chapters text)")
c.execute("CREATE unique index if not exists idx_volcode on volumes (volcode)")

c.execute("CREATE table if not exists summaries (ncode text, summary text)")
c.execute("CREATE unique index if not exists idx_summary_ncode on summaries (ncode)")

goodranks = False

arguments = []
if len(sys.argv) < 2:
    print("--yomou to get the top 300 from the yomou 'total_total' page")
    print("--updateknown to update all known stories")
    print("--updateandyomou to update all known stories and the rank list at the same time")
    print("--titles to list the ncodes and titles of all stories in the database")
    print("--ranklist to get the rankings of all stories in the database")
    print("--text <ncode> [start, end] to get the complete stored text of the given story (optional: from chapter 'start' (inclusive) to chapter 'end' (exclusive))")
    print("--htmlvolumes <ncode> - makes html files out of each 'volume' of a story, in a folder named after it")
    print("--htmlchapters <ncode> (or --htmlchapters_nonums) - makes html files out of each 'chapter' of a story, in a folder named after it. using --htmlchapters_nonums prevents the chapter number from being added, useful if chapters are numbered by the author.")
    print("--chapters <ncode> to get the list of chapters stored for the given story")
    print("--charcount <ncode> to get the length of the story in characters (newlines and leading/trailing spaces ignored)")
    print("--charcount <ncode> <chapter number> same, for chapters")
    print("--charcount <ncode> <first chapter> <last chapter> same, for a range of chapters (inclusive)")
    print("--dumpall dumps the entire database to e.g. scripts/n1701bm.txt")
    print("anything else will be interpreted as a list of ncodes or urls to rip into the database (this is how you download just one story)")
    exit()
elif sys.argv[1] == "--yomou":
    import yomou
    arguments = yomou.get_top_300("http://yomou.syosetu.com/rank/list/type/total_total/")
    goodranks = True
elif sys.argv[1] == "--updateknown":
    ncodes = c.execute("SELECT distinct ncode from narou").fetchall()
    arguments = []
    for ncode in ncodes:
        arguments += [[ncode[0], None]]
elif sys.argv[1] == "--updateandyomou":
    import yomou
    ranks = yomou.get_top_300("http://yomou.syosetu.com/rank/list/type/total_total/")
    known_ncodes = set()
    arguments = []
    for info in ranks:
        ncode = re.search("ncode.syosetu.com/([^/]*)[/]?", info[0])[1]
        known_ncodes.add(ncode)
        arguments += [info]
    
    ncodes = c.execute("SELECT distinct ncode from narou").fetchall()
    for ncode in ncodes:
        if ncode[0] not in known_ncodes:
            arguments += [[ncode[0], None]]
    
    goodranks = True
elif sys.argv[1] == "--titles":
    titles = c.execute("SELECT ncode, title from narou where chapter=1").fetchall()
    if titles != None:
        for title in titles:
            print(f"{title[0]}; {title[1]}")
    exit()
elif sys.argv[1] == "--ranklist":
    titles = c.execute("SELECT ncode, rank from ranks").fetchall()
    if titles != None:
        for title in titles:
            print(f"{title[0]};{title[1]}")
    exit()
elif sys.argv[1] == "--text":
    data = c.execute("SELECT ncode, title, chapter, chaptitle, content from narou where ncode=?", (sys.argv[2],)).fetchall()
    data.sort(key=lambda x:x[2])
    if len(sys.argv) == 4:
        data = data[int(sys.argv[3])-1:]
    if len(sys.argv) >= 5:
        data = data[int(sys.argv[3])-1:int(sys.argv[4])-1]
    print(f"{data[0][1]}")
    for chapter in data:
        print(f"\n\n----{chapter[3]}----\n\n")
        text = chapter[4]
        if text.startswith("<div"):
            soup = BeautifulSoup(text, "html.parser")
            text = soup.get_text()
        print(f"{text}")
    exit()
elif sys.argv[1] == "--htmlvolumes":
    noveltitle = c.execute("SELECT title from narou where ncode=?", (sys.argv[2],)).fetchone()[0]
    noveltitle_fs = sanitize_fs_name(noveltitle)
    noveltitle = html_escape(noveltitle)
    if not os.path.exists(noveltitle_fs):
        os.mkdir(noveltitle_fs)
    shutil.copyfile("data/narourip.css", f"{noveltitle_fs}/narourip.css")
    summary = c.execute("SELECT summary from summaries where ncode=?", (sys.argv[2],)).fetchone()
    if summary == None:
        summary = ""
    else:
        summary = summary[0]
    volumes = c.execute("SELECT * from volumes where ncode=?", (sys.argv[2],)).fetchall()
    volumes.sort(key=lambda x:x[3])
    i = 0
    for vol in volumes:
        i += 1
        page = html_header.replace("TITLE", html_escape(noveltitle))
        
        ncode = vol[0]
        vol_title = vol[1]
        volume = vol[3]
        chapters = vol[4].split("\n")
        texts = []
        
        for chapter in chapters:
            chapcode = ncode+"-"+chapter
            data = c.execute("SELECT chaptitle, content from narou where chapcode=?", (chapcode,)).fetchone()
            if data == None:
                print(f"failed to find chapter {chapter} of story {ncode}")
            title = html_escape(data[0])
            content = data[1]
            if not content.startswith("<div"):
                content = f"<div class=preformat>{content}</div>"
            texts += [[title, content]]
        
        page += f"\n<h1>{html_escape(noveltitle)}</h1>"
        if vol_title.strip() != "":
            page += f"\n<h2>{html_escape(vol_title)}</h2>"
        page += f"\n<p>{summary}</p>"
        
        page += f"\n<hr>"
        
        page += "\n<div id=toc>"
        for text in texts:
            chaptitle = text[0]
            page += f"\n<div><a href=\"#{url_escape(chaptitle)}\">{html_escape(chaptitle)}</a></div>"
        page += "\n</div>"
        
        page += f"\n<hr>"
        
        for text in texts:
            chaptitle = text[0]
            page += f"\n<div id='{url_escape(chaptitle)}'><h3><a href=\"#{html_escape(chaptitle)}\">{html_escape(chaptitle)}</a></h3>{text[1]}</div>"
            page += f"\n<hr>"
        
        page += html_footer
        
        page = page.replace(""" src="//""", """ src="http://""");
        
        fs_vol_title = sanitize_fs_name(vol_title).strip()
        if fs_vol_title != "":
            fs_vol_title = " - " + fs_vol_title
        
        if len(volumes) > 1:
            vol_num = f" - {i}"
        else:
            vol_num = ""
        
        fname = f"{noveltitle_fs}/{noveltitle_fs}{vol_num}{fs_vol_title}.html"
        
        with open(fname, "w", encoding='utf-8') as f:
            f.write(page)
    
    exit()
elif sys.argv[1] == "--htmlchapters" or sys.argv[1] == "--htmlchapters_nonums":
    noveltitle = c.execute("SELECT title from narou where ncode=?", (sys.argv[2],)).fetchone()[0]
    noveltitle_fs = sanitize_fs_name(noveltitle)
    noveltitle = html_escape(noveltitle)
    if not os.path.exists(noveltitle_fs):
        os.mkdir(noveltitle_fs)
    shutil.copyfile("data/narourip.css", f"{noveltitle_fs}/narourip.css")
    summary = c.execute("SELECT summary from summaries where ncode=?", (sys.argv[2],)).fetchone()
    if summary == None:
        summary = ""
    else:
        summary = summary[0]
    volumes = c.execute("SELECT * from volumes where ncode=?", (sys.argv[2],)).fetchall()
    volumes.sort(key=lambda x:x[3])
    dummymode = False
    if len(volumes) == 0:
        dummymode = True
        data = c.execute("SELECT chapter from narou where ncode=?", (sys.argv[2],)).fetchall()
        data.sort(key=lambda x:x[0])
        data = map(lambda x:str(x[0]), data)
        volumes = [[]]
    for (i, vol) in enumerate(volumes):
        i += 1
        
        if not dummymode:
            ncode = vol[0]
            vol_title = vol[1]
            volume = vol[3]
            chapters = vol[4].split("\n")
        else:
            ncode = sys.argv[2]
            vol_title = ""
            volume = 1
            chapters = data
        texts = []
        
        fs_vol_title = sanitize_fs_name(vol_title).strip()
        if fs_vol_title != "":
            fs_vol_title = " - " + fs_vol_title
        
        if len(volumes) > 1:
            vol_num = f" - {i}"
        else:
            vol_num = ""
        
        for chapter in chapters:
            chapcode = ncode+"-"+chapter
            data = c.execute("SELECT chaptitle, content from narou where chapcode=?", (chapcode,)).fetchone()
            if data == None:
                print(f"failed to find chapter {chapter} of story {ncode}")
            chaptitle = data[0]
            content = data[1]
            if not content.startswith("<div"):
                content = f"<div class=preformat>{content}</div>"
            texts += [[chaptitle, content]]
        
        def get_chapter_fname(j):
            chaptitle = texts[j][0]
            
            fs_chaptitle = sanitize_fs_name(chaptitle).strip()
            if fs_chaptitle != "":
                fs_chaptitle = " - " + fs_chaptitle
                
            if sys.argv[1] == "--htmlchapters_nonums":
                chap_num = ""
            else:
                chap_num = f" - {j+1}"
            
            return f"{noveltitle_fs}{vol_num}{fs_vol_title}{chap_num}{fs_chaptitle}.html"
        
        for (j, text) in enumerate(texts):
            chaptitle = text[0]
            content = text[1]
            
            page = html_header.replace("TITLE", html_escape(noveltitle))
        
            page += f"\n<h1>{html_escape(noveltitle)}</h1>"
            if vol_title.strip() != "":
                page += f"\n<h2>{html_escape(vol_title)}</h2>"
            page += f"\n<p>{summary}</p>"
            
            page += f"\n<hr>"
            
            page += f"\n<div style='display: flex; justify-content: center; width: 100%'>"
            if j > 0:
                prev_ = texts[j-1][0]
                if prev_ == None:
                    prev_ = str(j)
                page += f"\n<div style='width: 30%; text-align: right'><a href='{url_escape(get_chapter_fname(j-1))}'>← {prev_}</a></div>"
            else:
                page += f"\n<div style='width: 30%'></div>"
            page += f"\n<div style='width: 40%; text-align: center'>{html_escape(chaptitle)}</div>"
            if j+1 < len(texts):
                next_ = texts[j+1][0]
                if next_ == None:
                    next_ = str(j+2)
                page += f"\n<div style='width: 30%; text-align: left'><a href='{url_escape(get_chapter_fname(j+1))}'>{next_}→</a></div>"
            else:
                page += f"\n<div style='width: 30%'></div>"
            page += f"\n</div>"
            
            page += f"\n<hr>"
            
            page += f"\n<div id='{url_escape(chaptitle)}'><h3>{html_escape(chaptitle)}</h3>{content}</div>"
            
            page += html_footer
            
            page = page.replace(""" src="//""", """ src="http://""");
            
            partial_fname = get_chapter_fname(j)
            
            fname = f"{noveltitle_fs}/{partial_fname}"
            
            with open(fname, "w", encoding='utf-8') as f:
                f.write(page)
    
    exit()
elif sys.argv[1] == "--chapters":
    data = c.execute("SELECT ncode, title, chapter, chaptitle from narou where ncode=?", (sys.argv[2],)).fetchall()
    data.sort(key=lambda x:x[2])
    print(f"{data[0][1]} ({data[0][0]})")
    for chapter in data:
        print(f"{chapter[2]} - {chapter[3]}")
    exit()
elif sys.argv[1] == "--charcount":
    ncode = sys.argv[2]
    if len(sys.argv) == 3:
        data = c.execute("SELECT content from narou where ncode=?", (ncode,)).fetchall()
        length = 0
        for entry in data:
            text = entry[0]
            if text.startswith("<div"):
                soup = BeautifulSoup(text, "html.parser")
                text = soup.get_text()
            for line in text.splitlines(False):
                length += len(line.strip())
        print(length)
    elif len(sys.argv) == 4:
        chapnum = sys.argv[3]
        chapcode = ncode+"-"+chapnum
        data = c.execute("SELECT content from narou where chapcode=?", (chapcode,)).fetchone()
        if data == None:
            print("no such chapter for that story")
        
        text = data[0]
        length = 0
        if text.startswith("<div"):
            soup = BeautifulSoup(text, "html.parser")
            text = soup.get_text()
            for line in text.splitlines(False):
                length += len(line.strip())
        print(length)
    elif len(sys.argv) > 4:
        first = sys.argv[3]
        last = sys.argv[4]
        data = c.execute("SELECT content from narou where ncode=? and chapter>=? and chapter<=?", (ncode, first, last)).fetchall()
        length = 0
        for entry in data:
            text = entry[0]
            if text.startswith("<div"):
                soup = BeautifulSoup(text, "html.parser")
                text = soup.get_text()
            for line in text.splitlines(False):
                length += len(line.strip())
        print(length)
elif sys.argv[1] == "--dumpall":
    from datetime import datetime
    ncodes = c.execute("SELECT distinct ncode from narou").fetchall()
    target = len(ncodes)
    done = 0
    skipping = False
    for ncode in ncodes:
        ncode = ncode[0]
        writepath = f"scripts/{ncode}.txt"
        if os.path.exists(writepath):
            otherdata = c.execute("SELECT datetime from ranks where ncode=?", (ncode,)).fetchall()
            #print(F"????? {otherdata} {ncode}")
            if len(otherdata) != 0 and otherdata[0][0] != None:
                from_fs = datetime.fromtimestamp(os.path.getmtime(writepath)).astimezone()
                from_narou = datetime.strptime(otherdata[0][0] + ' +0900', '%Y-%m-%d %H:%M:%S %z').astimezone()
                #print("---")
                #print(f"from fs (formatted): {from_fs}")
                #print(f"from narou: {from_narou}")
                if from_fs > from_narou:
                    if not skipping:
                        print("skipping some stories because we already (apparently) dumped this version of them")
                    skipping = True
                    done += 1
                    continue
        skipping = False
        data = c.execute("SELECT ncode, title, chapter, chaptitle, content from narou where ncode=?", (ncode,)).fetchall()
        data.sort(key=lambda x:x[2])
        out_text = ""
        for chapter in data:
            text = chapter[4]
            if text.startswith("<div"):
                soup = BeautifulSoup(text, "html.parser")
                text = soup.get_text()
            out_text += f"{text}\n\n\n"
        
        with open(writepath, "w", encoding='utf-8', newline='\n') as f:
            f.write(out_text)
        done += 1
        print(f"{done}/{target} ({ncode})")
    exit()
elif sys.argv[1] == "--dumpnames":
    print("dumping names")
    with open("other_stats.txt", "w", encoding='utf-8', newline='\n') as f:
        ncodes = c.execute("SELECT distinct ncode from narou").fetchall()
        for ncode in ncodes:
            ncode = ncode[0]
            try:
                rank = c.execute("SELECT rank from ranks where ncode=?", (ncode,)).fetchall()[0][0]
            except:
                rank = None
            if rank == None:
                rank = "x"
            title = c.execute("SELECT title from narou where ncode=? limit 1", (ncode,)).fetchall()[0][0]
            
            tabchar = '\t'
            newline = '\n'
            f.write(f"{ncode}\t{rank}\t{title.replace(tabchar, ' ').replace(newline, ' ')}\n")
    exit()
elif sys.argv[1] == "--deletedatetimedata":
    # undocumented, for debugging/repair only
    print("Setting ALL datetime data to NULL. This is only for debugging/repair.")
    c.execute("UPDATE ranks set datetime=null")
    c.execute("UPDATE narou set datetime=null")
    database.commit()
    exit()
else:
    arguments = []
    for arg in sys.argv[1:]:
        arguments += [[arg, -1]]

def response_text_indicates_ratelimit(string):
    return "Too many access!" in string

def response_code_indicates_ratelimit(code):
    return code == 503

dead = []

class Volume:
    def __init__(self, name):
        self.name = name
        self.chapters = []
    def stringify(self):
        string = f"{self.name}"
        for chapter in self.chapters:
            string += f"\n  {chapter}"
        return string

def update_volumes(ncode, soup):
    volume_list = []
    latest_volume = Volume("")
    for entry in soup.select(".index_box > *"):
        if entry.name == "div":
            if len(latest_volume.chapters) != 0:
                volume_list += [latest_volume]
            latest_volume = Volume(entry.get_text())
        else:
            li = entry.select(".subtitle a")[0]
            dt = entry.select(".long_update")[0]
            suburl = li.get("href")
            updates = dt.select("span")
            if len(updates) > 0:
                datetime = updates[0].get("title")
            else:
                datetime = dt.get_text()
            datetime = re.search("([0-9]{4}/[0-1][0-9]/[0-9]{2} [0-2][0-9]:[0-5][0-9])", datetime)
            
            if ncode not in suburl or datetime is None:
                continue
            
            chapurl = suburl.rstrip("/").rsplit('/', 1)[-1]
            latest_volume.chapters += [chapurl]
    if len(latest_volume.chapters) != 0:
        volume_list += [latest_volume]
    
    for i in range(len(volume_list)):
        volume = volume_list[i]
        title = volume.name
        chapters = "\n".join(map(lambda x: str(x), volume.chapters))
        c.execute("INSERT or replace into volumes values (?,?,?,?,?)", (ncode, title, ncode+"-"+str(i), i, chapters))
    
    pass

def get_http_data(url):
    data = None
    failing = True
    while failing:
        try:
            headers = { 'User-Agent' : 'Mozilla/5.0' }
            req = urllib.request.Request(url, None, headers)
            
            r = urllib.request.urlopen(req)
            data = r.read()
            r.close()
            failing = False
        except urllib.request.HTTPError as e:
            if response_code_indicates_ratelimit(e.code):
                print("you've been ratelimited by narou. if you keep seeing this warning, wait a while and try again")
                time.sleep(wait_if_ratelimited)
            else:
                print(f"(exception `{e}`; retrying)")
                time.sleep(1)
        except Exception as e:
            print(f"(exception `{e}`; retrying)")
            time.sleep(1)
    return data

if goodranks:
    for argument in arguments:
        mainurl = argument[0]
        ncode = mainurl.rstrip("/").rsplit('/', 1)[-1]
        rank = argument[1]
        if rank != None and int(rank) < 1:
            rank = None
        c.execute("UPDATE ranks set rank=null where rank=(?)", (rank,))
        c.execute("UPDATE ranks set rank=? where ncode=?", (rank, ncode))

print("checking update dates")

newargs = []
for asdf in range(0, len(arguments), 20):
    group = arguments[asdf:asdf+20]
    ncode_list = "-".join(map(lambda x: x[0].rstrip("/").rsplit('/', 1)[-1], group))
    
    info_json = get_http_data(f"http://api.syosetu.com/novelapi/api/?out=json&ncode={ncode_list}&of=n-nu-s")
    info = json.loads(info_json)
    info_map = {}
    for etc in info[1:]:
        info_map[etc["ncode"].lower()] = etc
        
    for argument in group:
        mainurl = argument[0]
        ncode = mainurl.rstrip("/").rsplit('/', 1)[-1]
        rank = argument[1]
        # check if it's up to date or not
        if ncode not in info_map:
            print(f"story {ncode} does not exist, or no longer exists on narou. skipping")
            dead += [ncode]
            continue
        
        novel_datetime = info_map[ncode]["novelupdated_at"]
        novel_summary = info_map[ncode]["story"]
        c.execute("INSERT or replace into summaries values (?,?)", (ncode, novel_summary))
        
        if enable_per_novel_datetime_check and c.execute("SELECT datetime from ranks where ncode=? and datetime=?", (ncode, novel_datetime)).fetchone() != None:
            print(f"{ncode} is up to date, skipping")
            continue
        
        print(f"adding {ncode}")
        newargs += [argument]

for asdf in dead:
    # double-checking dead stories goes here

arguments = newargs

print("note: chapter downloads aren't persistent until all updates are downloaded")
for asdf in range(len(arguments)):
    argument = arguments[asdf]
    mainurl = argument[0]
    rank = argument[1]
    if "https://" not in mainurl and "http://" not in mainurl:
        mainurl = "http://ncode.syosetu.com/" + mainurl
    
    mainurl = mainurl.replace("https://", "http://")
    
    progress_string = f"{asdf+1}/{len(arguments)}"
    
    print(f"ripping {mainurl} ({progress_string})")
    
    ncode = mainurl.rstrip("/").rsplit('/', 1)[-1]
    
    # check if it's up to date or not
    
    info_json = get_http_data(f"http://api.syosetu.com/novelapi/api/?out=json&ncode={ncode}&of=nu-s")
    info = json.loads(info_json)
    
    if len(info) == 1:
        print(f"story {ncode} does not exist, or no longer exists on narou. skipping")
        dead += [ncode]
        continue
    
    novel_datetime = info[1]["novelupdated_at"]
    
    print("getting chapter listing...")
    
    data = get_http_data(mainurl)
    
    soup = BeautifulSoup(data, "html.parser")
    
    if response_text_indicates_ratelimit(soup.get_text()):
        print("you've been ratelimited by narou. wait a while and try again")
        exit()
    
    update_volumes(ncode, soup)
    
    if enable_per_novel_datetime_check and c.execute("SELECT datetime from ranks where ncode=? and datetime=?", (ncode, novel_datetime)).fetchone() != None:
        print(f"up to date, skipping")
        continue
    
    title = soup.select("#novel_color .novel_title")
    
    if len(title) == 0:
        print(f"story {ncode} does not have a coherent page, skipping.")
        continue
        
    title = title[0].get_text().strip()
    
    chapterstuff = [] # url, title, time
    for entry in soup.select(".index_box .novel_sublist2"):
        li = entry.select(".subtitle a")[0]
        dt = entry.select(".long_update")[0]
        suburl = li.get("href")
        updates = dt.select("span")
        if len(updates) > 0:
            datetime = updates[0].get("title")
        else:
            datetime = dt.get_text()
        datetime = re.search("([0-9]{4}/[0-1][0-9]/[0-9]{2} [0-2][0-9]:[0-5][0-9])", datetime)
        
        if ncode not in suburl or datetime is None:
            continue
        
        chapurl = suburl.rstrip("/").rsplit('/', 1)[-1]
        datetime = datetime[1]
        
        if enable_per_chapter_datetime_check:
            chapcode = ncode+"-"+chapurl
            if c.execute("SELECT * from narou where chapcode=? and datetime=?", (chapcode, datetime)).fetchone() != None:
                continue
        
        chapterstuff += [[urljoin(mainurl, suburl), li.get_text(), datetime]]
    
    print(f"{len(chapterstuff)} chapters to download for this story")
    
    while len(chapterstuff) > 0:
        workarray = chapterstuff[:limit_chapters_at_once]
        chapterstuff = chapterstuff[limit_chapters_at_once:]
        
        datas = [""] * len(workarray)
        
        retrycount = 0
        
        async def fetch(session, url):
            i = 0
            while i < retrycount or retrycount <= 0:
                try:
                    async with session.get(url, timeout=chapter_timeout) as response:
                        if response.status != 200:
                            return None
                        return await response.text()
                except asyncio.TimeoutError:
                    #print("retrying a connection")
                    continue
        
        async def load_chapter(session, url, index):
            data = await fetch(session, url)
            print(f"loaded {url}")
            datas[index] = data
        
        async def load_all_chapters():
            connector = aiohttp.TCPConnector(ttl_dns_cache=100000000, limit=limit_connections, force_close=True, enable_cleanup_closed=True)
            async with aiohttp.ClientSession(connector=connector, headers={'User-Agent': 'Mozilla/5.0'}) as session:
                tasks = []
                i = 0
                for workdata in workarray:
                    url = workdata[0]
                    tasks.append(load_chapter(session, url, i))
                    i += 1
                responses = asyncio.gather(*tasks)
                await responses
        
        start_time = time.time()
        
        loop = asyncio.get_event_loop()
        
        future = asyncio.ensure_future(load_all_chapters())
        loop.run_until_complete(future)
        
        ratelimited = False
        
        print("writing to database and checking for ratelimiting errors...")
        
        for index in range(len(workarray)):
            url = workarray[index][0]
            chaptitle = workarray[index][1]
            datetime = workarray[index][2]
            
            chapternum = url.rstrip("/").rsplit('/', 1)[-1]
            chapcode = ncode+"-"+chapternum
            text = datas[index]
            datas[index] = ""
            
            if text == None:
                ratelimited = True
                chapterstuff += [[url, chaptitle, datetime]]
                continue
            
            soup = BeautifulSoup(text, "html.parser")
            
            text = ""
            for entry in soup.select(".novel_view"):
                text += str(entry)
            
            c.execute("INSERT or replace into narou values (?,?,?,?,?,?,?)", (ncode, title, chapcode, int(chapternum), chaptitle, datetime, text))
        
        database.commit()
        
        if ratelimited:
            print("you've been ratelimited by narou. if you keep seeing this warning, wait a while and try again")
            time.sleep(wait_if_ratelimited)
        
        end_time = time.time()
        difference = end_time - start_time
        actual_desired_bundle_time = len(workarray) / chapters_per_second
        want_to_sleep = actual_desired_bundle_time - difference
        if want_to_sleep > 0:
            rounded = round(want_to_sleep*1000)/1000
            print(f"sleeping for {rounded} seconds to reduce the risk of getting ratelimited...")
            time.sleep(want_to_sleep)
        
        if len(chapterstuff) != 0:
            print(f"{len(chapterstuff)} chapters left to go for this story.")
        
    
    if rank == -1:
        if goodranks:
            c.execute("INSERT or replace into ranks values (?,null,?)", (ncode, novel_datetime))
        else:
            rank = c.execute("SELECT rank from ranks where ncode=(?)", (ncode,)).fetchone()
            if rank != None:
                rank = rank[0]
            c.execute("INSERT or replace into ranks values (?,?,?)", (ncode, rank, novel_datetime))
    else:
        c.execute("UPDATE ranks set rank=null where rank=(?)", (rank,))
        c.execute("INSERT or replace into ranks values (?,?,?)", (ncode, rank, novel_datetime))
    database.commit()
    
    print("done.")

database.commit()

if len(dead) > 0:
    print("You tried to rip the following stories, but they do not exist on narou. If they existed before, they were probably deleted.")
    sql = 'SELECT ncode, title FROM narou WHERE chapter=1 and ncode in ({0})'.format(', '.join('?' for _ in dead))
    out = c.execute(sql, (dead)).fetchall()
    for (ncode, title) in out:
        print(ncode + "\t" + title)
    #print(" ".join(dead))

c.close()
database.close()
