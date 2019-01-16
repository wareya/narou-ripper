#!python

from bs4 import BeautifulSoup
import urllib
from urllib.parse import urljoin
import sys

sys.stdout.reconfigure(encoding='utf-8')

import aiohttp
import asyncio

import os.path
import re

import sqlite3

database = sqlite3.connect("naroudb.db")
c = database.cursor()

c.execute("create table if not exists narou (ncode text, title text, chapcode text, chapter int, chaptitle text, datetime text, content text)")
c.execute("create unique index if not exists idx_chapcode on narou (chapcode)")

c.execute("create table if not exists ranks (ncode text, rank text)")
c.execute("create unique index if not exists idx_ncode on ranks (ncode)")

arguments = []
if len(sys.argv) < 2:
    import yomou
    arguments = yomou.get_top_300("http://yomou.syosetu.com/rank/list/type/total_total/")
elif sys.argv[1] == "--titles":
    titles = c.execute("select ncode, title from narou where chapter=1").fetchall()
    if titles != None:
        for title in titles:
            print(f"{title[0]}; {title[1]}")
    exit()
elif sys.argv[1] == "--ranklist":
    titles = c.execute("select ncode, rank from ranks").fetchall()
    if titles != None:
        for title in titles:
            print(f"{title[0]};{title[1]}")
    exit()
elif sys.argv[1] == "--text":
    data = c.execute("select ncode, title, chapter, chaptitle, content from narou where ncode=?", (sys.argv[2],)).fetchall()
    data.sort(key=lambda x:x[2])
    print(f"{data[0][1]}")
    for chapter in data:
        print(f"\n\n----{chapter[3]}----\n\n")
        print(f"{chapter[4]}")
    exit()
elif sys.argv[1] == "--chapters":
    data = c.execute("select ncode, title, chapter, chaptitle from narou where ncode=?", (sys.argv[2],)).fetchall()
    data.sort(key=lambda x:x[2])
    print(f"{data[0][1]} ({data[0][0]})")
    for chapter in data:
        print(f"{chapter[2]} - {chapter[3]}")
    exit()
else:
    arguments = []
    for arg in sys.argv[1:]:
        arguments += [[arg, None]]
    

print("note: chapter downloads aren't persistent until all updates are downloaded")
for argument in arguments:
    print(f"ripping {argument}")
    
    mainurl = argument[0]
    rank = argument[1]
    if "https://" not in mainurl and "http://" not in mainurl:
        mainurl = "https://ncode.syosetu.com/" + mainurl
    
    ncode = mainurl.rstrip("/").rsplit('/', 1)[-1]
    
    data = None
    failing = True
    while failing:
        try:
            r = urllib.request.urlopen(mainurl)
            data = r.read()
            r.close()
            failing = False
        except:
            from time import sleep
            print("(retrying)")
            sleep(1) 
    soup = BeautifulSoup(data, "html.parser")
    
    title = soup.select("#novel_color .novel_title")[0].get_text().strip()
    
    chapterurls = []
    chaptertimes = []
    chaptertitles = []
    for li in soup.select(".index_box .novel_sublist2 .subtitle a"):
        chapterurls += [urljoin(mainurl, li.get("href"))]
        chaptertitles += [li.get_text()]
    for dt in soup.select(".index_box .novel_sublist2 .long_update"):
        chaptertimes += [re.search("([0-9]{4}/[0-1][0-9]/[0-9]{2} [0-2][0-9]:[0-5][0-9])", dt.get_text())[1]]
    
    if len(chaptertimes) != len(chapterurls) or len(chaptertimes) != len(chaptertitles):
        print("Assert: chapter data lists are not all of same length")
        exit()
    
    if False:
        nofetch = []
        count = len(chapterurls)
        for i in range(len(chapterurls)):
            url = chapterurls[i]
            chapter = url.rstrip("/").rsplit('/', 1)[-1]
            chapcode = ncode+"-"+chapter
            time = chaptertimes[i]
            knowntime = c.execute("select datetime from narou where chapcode=?", (chapcode,)).fetchone()
            if knowntime != None:
                knowntime = knowntime[0]
                if knowntime == time and time != None:
                    nofetch += [url]
        
        for delete in nofetch:
            index = chapterurls.index(delete)
            del chapterurls[index]
            del chaptertimes[index]
    
    datas = [""] * len(chapterurls)
    texts = [""] * len(chapterurls)
    
    retrycount = 0
    
    async def fetch(session, url):
        i = 0
        while i < retrycount or retrycount <= 0:
            try:
                # depending on how far you are from japan and how bad your internet is, you might need to raise this 3 to something like a 5 or an 8 - but the higher it is, the greater the number of connections that get trapped
                async with session.get(url, timeout=3) as response:
                    return await response.text()
            except asyncio.TimeoutError:
                #print("retrying a connection")
                continue
    
    async def load_chapter(session, url, index):
        data = await fetch(session, url)
        print(f"loaded {url}")
        datas[index] = data
    
    async def load_all_chapters():
        connector = aiohttp.TCPConnector(ttl_dns_cache=100000000, limit=100, force_close=True, enable_cleanup_closed=True)
        async with aiohttp.ClientSession(connector=connector) as session:
            tasks = []
            i = 0
            for url in chapterurls:
                tasks.append(load_chapter(session, url, i))
                i += 1
            responses = asyncio.gather(*tasks)
            await responses
    
    loop = asyncio.get_event_loop()
    
    future = asyncio.ensure_future(load_all_chapters())
    loop.run_until_complete(future)
    
    for index in range(len(datas)):
        soup = BeautifulSoup(datas[index], "html.parser")
        for entry in soup.select("#novel_honbun"):
            [rt.extract() for rt in entry.findAll("rt")]
            [rp.extract() for rp in entry.findAll("rp")]
            texts[index] = entry.get_text()
    
    print("writing to database...")
    for index in range(len(chapterurls)):
        url = chapterurls[index]
        chapter = url.rstrip("/").rsplit('/', 1)[-1]
        chapcode = ncode+"-"+chapter
        time = chaptertimes[index]
        text = texts[index]
        chaptitle = chaptertitles[index]
        c.execute("insert or replace into narou values (?,?,?,?,?,?,?)", (ncode, title, chapcode, int(chapter), chaptitle, time, text))
    database.commit()
    
    c.execute("delete from ranks where rank=(?)", (rank,))
    c.execute("insert or replace into ranks values (?,?)", (ncode, rank))
    database.commit()
    
    print("done. writing to file...")
    outputs = c.execute("select * from narou where ncode=? order by chapter asc", (ncode,)).fetchall()
    if outputs != None:
        realoutputs = []
        for output in outputs:
            realoutputs += [output[-1]]
        f = open("scripts/"+ncode+".txt", "w", encoding="utf-8", newline="\n")
        f.write("\n\n\n".join(realoutputs).replace("《", "«").replace("》", "»").replace("〈", "‹").replace("〉", "›"))
        f.close()
    print("done.")

database.commit()
c.close()
database.close()
