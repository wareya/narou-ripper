
Licensed under the Apache License, Version 2.0.


Requires a modern version of Python 3.

Note: This tool scrapes each work's normal HTML pages, rather than using the txtdownload feature ( https://ncode.syosetu.com/txtdownload/top/ncode/108715/ ).
This is becaue the txtdownload feature seems to have a much rougher rate limit than the normal HTML pages.
It also requires login cookies to function, and the way the ncode is encoded is different (e.g. n8725k becomes 108715).
Like working against individual HTML pages, it has to be done one chapter at a time, too.
It would, actually, be ideal to get things from the txtdownload function instead of scraping HTML.
The txtdownload function gives you special markup before it's converted to HTML, like so: "『|さまよえる剣《ワンダリング・ソード》』"

Narou has a real API, but it does not allow downloading chapter text. https://dev.syosetu.com/man/man/ https://dev.syosetu.com/man/api/

Narou also has an API for generating a PDF from an entire novel. https://pdfnovels.net/n8725k/
