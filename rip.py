#!python



# Licensed under the Apache License, Version 2.0. So is yomou.py



# Requires a modern version of Python 3.

# Note: This tool scrapes each work's normal HTML pages, rather than using the txtdownload feature ( https://ncode.syosetu.com/txtdownload/top/ncode/108715/ ).
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



from bs4 import BeautifulSoup
import urllib
from urllib.parse import urljoin
import sys
import json
import time

sys.stdout.reconfigure(encoding='utf-8')

import aiohttp
import asyncio

import os.path
import re

import sqlite3

database = sqlite3.connect("naroudb.db")
c = database.cursor()

c.execute("CREATE table if not exists narou (ncode text, title text, chapcode text, chapter int, chaptitle text, datetime text, content text)")
c.execute("CREATE unique index if not exists idx_chapcode on narou (chapcode)")

c.execute("CREATE table if not exists ranks (ncode text, rank text, datetime text)")
c.execute("CREATE unique index if not exists idx_ncode on ranks (ncode)")

arguments = []
if len(sys.argv) < 2:
    print("--yomou to get the top 300 from the yomou 'total_total' page")
    print("--updateknown to update all known works")
    print("--titles to list the ncodes and titles of all works in the database")
    print("--ranklist to get the rankings of all works in the database")
    print("--text <ncode> [start, end] to get the complete stored text of the given work (optional: from chapter 'start' (inclusive) to chapter 'end' (exclusive))")
    print("--chapters <ncode> to get the list of chapters stored for the given work")
    print("anything else will be interpreted as a list of ncodes or urls to rip into the database (this is how you download just one work)")
    exit()
elif sys.argv[1] == "--yomou":
    import yomou
    arguments = yomou.get_top_300("http://yomou.syosetu.com/rank/list/type/total_total/")
elif sys.argv[1] == "--updateknown":
    ncodes = c.execute("SELECT distinct ncode from narou").fetchall()
    arguments = []
    for ncode in ncodes:
        arguments += [[ncode[0], -1]]
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
        print(f"{chapter[4]}")
    exit()
elif sys.argv[1] == "--chapters":
    data = c.execute("SELECT ncode, title, chapter, chaptitle from narou where ncode=?", (sys.argv[2],)).fetchall()
    data.sort(key=lambda x:x[2])
    print(f"{data[0][1]} ({data[0][0]})")
    for chapter in data:
        print(f"{chapter[2]} - {chapter[3]}")
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
    
    info_json = None
    failing = True
    while failing:
        try:
            myurl = f"http://api.syosetu.com/novelapi/api/?out=json&ncode={ncode}&of=nu"
            
            headers = { 'User-Agent' : 'Mozilla/5.0' }
            req = urllib.request.Request(myurl, None, headers)

            r = urllib.request.urlopen(req)
            
            info_json = r.read()
            r.close()
            failing = False
        except urllib.request.HTTPError as e:
            if response_code_indicates_ratelimit(e.code):
                print("you've been ratelimited by narou. if you keep seeing this warning, wait a while and try again")
                time.sleep(wait_if_ratelimited)
                exit()
            print(f"(exception `{e}`; retrying)")
            time.sleep(1)
        except Exception as e:
            print(f"(exception `{e}`; retrying)")
            time.sleep(1)
    
    info = json.loads(info_json)
    
    if len(info) == 1:
        print(f"work {ncode} does not exist, or no longer exists on narou. skipping")
        dead += [ncode]
        continue
    
    novel_datetime = info[1]["novelupdated_at"]
    
    if enable_per_novel_datetime_check and c.execute("SELECT datetime from ranks where ncode=? and datetime=?", (ncode, novel_datetime)).fetchone() != None:
        print(f"up to date, skipping")
        continue
    
    print("getting chapter listing...")
    
    data = None
    failing = True
    while failing:
        try:
            headers = { 'User-Agent' : 'Mozilla/5.0' }
            req = urllib.request.Request(mainurl, None, headers)
            
            r = urllib.request.urlopen(mainurl)
            data = r.read()
            r.close()
            failing = False
        except urllib.request.HTTPError as e:
            if response_code_indicates_ratelimit(e.code):
                print("you've been ratelimited by narou. if you keep seeing this warning, wait a while and try again")
                time.sleep(wait_if_ratelimited)
                exit()
            print(f"(exception `{e}`; retrying)")
            time.sleep(1)
        except Exception as e:
            print(f"(exception `{e}`; retrying)")
            time.sleep(1)
    
    soup = BeautifulSoup(data, "html.parser")
    
    if response_text_indicates_ratelimit(soup.get_text()):
        print("you've been ratelimited by narou. wait a while and try again")
        exit()
    
    
    
    title = soup.select("#novel_color .novel_title")
    
    if len(title) == 0:
        print(f"work {ncode} does not have a coherent page, skipping.")
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
        
        datetime = datetime[1]
        
        if enable_per_chapter_datetime_check:
            chapurl = suburl.rstrip("/").rsplit('/', 1)[-1]
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
            for entry in soup.select("#novel_honbun"):
                text += entry.get_text()
            
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
        
        print(f"{len(chapterstuff)} chapters left to go for this story.")
        
    
    if rank == -1:
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
c.close()
database.close()

if len(dead) > 0:
    print("You tried to rip the following stories, but they do not exist on narou. If they existed before, they were probably deleted.")
    print(" ".join(dead))
