#!python

from bs4 import BeautifulSoup
import urllib
import urllib.request
from urllib.parse import urljoin
import sys

def get_top_300(url):
    r = urllib.request.urlopen(url)
    data = r.read()
    r.close()
    soup = BeautifulSoup(data, "html.parser")

    novels = []
    for div in soup.select(".ranking_list .rank_h"):
        rank = div.select(".ranking_number")[0].getText().replace("位", "")
        link = div.select("a")[0]
        novels += [[link.get("href"), rank]]

    novels = [[entry[0], entry[1].rstrip("/").rsplit('/', 1)[-1]] for entry in novels]
    return novels

if __name__ == "__main__":
    novels = get_top_300(sys.argv[1])
    print(novels)
