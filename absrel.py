import html5lib
import html5lib.serializer
import html5lib.treewalkers
import urlparse
import os.path

# List of (ELEMENT, ATTRIBUTE) for HTML5 attributes which contain URLs.
# Based on the list at http://www.feedparser.org/docs/resolving-relative-links.html
url_attributes = [
    ('a', 'href'),
    ('applet', 'codebase'),
    ('area', 'href'),
    ('audio', 'src'),
    ('blockquote', 'cite'),
    ('body', 'background'),
    ('del', 'cite'),
    ('form', 'action'),
    ('frame', 'longdesc'),
    ('frame', 'src'),
    ('iframe', 'longdesc'),
    ('iframe', 'src'),
    ('head', 'profile'),
    ('img', 'longdesc'),
    ('img', 'src'),
    ('img', 'usemap'),
    ('input', 'src'),
    ('input', 'usemap'),
    ('ins', 'cite'),
    ('link', 'href'),
    ('object', 'classid'),
    ('object', 'codebase'),
    ('object', 'data'),
    ('object', 'usemap'),
    ('q', 'cite'),
    ('script', 'src'),
    ('source', 'src'),
    ('video', 'poster'),
    ('video', 'src'),
    ]

linkurl_attributes = [
    ('a', 'href'),
    ('area', 'href'),
    ('blockquote', 'cite'),
    ('iframe', 'src'),
    ('q', 'cite'),
    ]



def absolutify(src, base_url):
    """absolutify(SRC, BASE_URL): Resolve relative URLs in SRC.
SRC is a string containing HTML. All URLs in SRC are resolved relative
to BASE_URL. Return the body of the result as HTML."""

    # Parse SRC as HTML.
    tree_builder = html5lib.treebuilders.getTreeBuilder('dom')
    parser = html5lib.html5parser.HTMLParser(tree = tree_builder)
    dom = parser.parse(src)

    # Handle <BASE> if any.
    head = dom.getElementsByTagName('head')[0]
    for b in head.getElementsByTagName('base'):
        u = b.getAttribute('href')
        if u:
            base_url = urlparse.urljoin(base_url, u)
            # HTML5 4.2.3 "if there are multiple base elements with href
            # attributes, all but the first are ignored."
            break

    # Change all relative URLs to absolute URLs by resolving them
    # relative to BASE_URL. Note that we need to do this even for URLs
    # that consist only of a fragment identifier, because Google Reader
    # changes href=#foo to href=http://site/#foo
    for tag, attr in url_attributes:
        for e in dom.getElementsByTagName(tag):
            u = e.getAttribute(attr)
            if u:
                e.setAttribute(attr, urlparse.urljoin(base_url, u))

    # Return the HTML5 serialization  of the result 
    body = dom.getElementsByTagName('html')[0]
    tree_walker = html5lib.treewalkers.getTreeWalker('dom')
    html_serializer = html5lib.serializer.htmlserializer.HTMLSerializer()
    return u''.join(html_serializer.serialize(tree_walker(body)))
    
def relativize(src, base_url):
    """relativize(SRC, BASE_URL): Resolve absolute URLs in SRC.
SRC is a string containing HTML. All URLs in SRC are made relative
to BASE_URL. Return the result as HTML."""

    # Parse SRC as HTML.
    tree_builder = html5lib.treebuilders.getTreeBuilder('dom')
    parser = html5lib.html5parser.HTMLParser(tree = tree_builder)
    dom = parser.parse(src)

    # Handle <BASE> if any.
    head = dom.getElementsByTagName('head')[0]
    for b in head.getElementsByTagName('base'):
        u = b.getAttribute('href')
        if u:
            base_url = urlparse.urljoin(base_url, u)
            # HTML5 4.2.3 "if there are multiple base elements with href
            # attributes, all but the first are ignored."
            break
    if not base_url.endswith('/'):
        base_url = base_url+'/' # make urlparse.urljoin handle nested dirs right
    rel_basebits = urlparse.urlsplit(base_url)
    basepath = rel_basebits.path or '/'
    #print "basebits.path: '%s' basepath:'%s'" %(rel_basebits.path,basepath)
    # Change all absolute URLs to relative URLs by resolving them
    # relative to BASE_URL, then removing BASE_URL 
    for tag, attr in url_attributes:
        for e in dom.getElementsByTagName(tag):
            u = e.getAttribute(attr)
            if u:
                ubits = urlparse.urlsplit(urlparse.urljoin(base_url, u))
                path = ubits.path or '/'
                #print "base_url: '%s' ubits.path: '%s' path:'%s'" %(base_url,ubits.path,path)
                if ubits.netloc == rel_basebits.netloc:
                    newpath= os.path.relpath(path,basepath)
                    if newpath == ".":
                        newpath = ""
                    newu = urlparse.urlunsplit(('','',newpath,ubits.query,ubits.fragment))
                    #print "path: '%s', basepath: '%s', newpath: '%s', newu: '%s'" %(path,basepath,newpath,newu)
                    e.setAttribute(attr, newu)

    body = dom.getElementsByTagName('html')[0]
    tree_walker = html5lib.treewalkers.getTreeWalker('dom')
    html_serializer = html5lib.serializer.htmlserializer.HTMLSerializer()
    return u''.join(html_serializer.serialize(tree_walker(body)))

def geturls(src, base_url):
    """return all outbound URLs so you can webmention them"""    # Parse SRC as HTML.
    tree_builder = html5lib.treebuilders.getTreeBuilder('dom')
    parser = html5lib.html5parser.HTMLParser(tree = tree_builder)
    dom = parser.parse(src)
    urls=[]
    # Handle <BASE> if any.
    head = dom.getElementsByTagName('head')[0]
    for b in head.getElementsByTagName('base'):
        u = b.getAttribute('href')
        if u:
            base_url = urlparse.urljoin(base_url, u)
            # HTML5 4.2.3 "if there are multiple base elements with href
            # attributes, all but the first are ignored."
            break
    if not base_url.endswith('/'):
        base_url = base_url+'/' # make urlparse.urljoin handle nested dirs right
    rel_basebits = urlparse.urlsplit(base_url)
    basepath = rel_basebits.path or '/'
    # Change all relative URLs to absolute URLs by resolving them
    # relative to BASE_URL. Note that we need to do this even for URLs
    for tag, attr in linkurl_attributes:
        for e in dom.getElementsByTagName(tag):
            u = e.getAttribute(attr)
            if u:
                fullurl = urlparse.urljoin(base_url, u)
                urls.append(fullurl)
    return urls

    