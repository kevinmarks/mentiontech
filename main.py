#!/usr/bin/env python
# -*- coding: utf-8 -*-
#
# Copyright 2015 Kevin Marks

from __future__ import with_statement
import os
import urllib
import urlparse
import jinja2
import webapp2
import logging
import humanize
import mf2py
import requests
import json
import mf2tojf2
import cassis
import ssl
import absrel

import cloudstorage as gcs

from google.appengine.api import urlfetch
from google.appengine.api import memcache
from google.appengine.api import taskqueue

urlfetch.set_default_fetch_deadline(180)

useragent = 'mention.tech/0.1 like Mozilla'


from google.appengine.ext import ndb

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)+"/templates/"),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

class Mention(ndb.Model):
    """ model received webmentions"""
    source = ndb.StringProperty(indexed=True)
    target = ndb.StringProperty(indexed=True)
    property = ndb.StringProperty(indexed=False)
    sourcedomain = ndb.StringProperty(indexed=True)
    targetdomain = ndb.StringProperty(indexed=True)
    sourceHTML = ndb.TextProperty(indexed=False)
    targetHTML = ndb.TextProperty(indexed=False)
    sourcejf2 = ndb.TextProperty(indexed=False)
    targetjf2 = ndb.TextProperty(indexed=False)
    created = ndb.DateTimeProperty(auto_now_add=True) #creation date
    updated = ndb.DateTimeProperty(auto_now=True) #updated date
    verified = ndb.BooleanProperty(indexed=True,default=None)
    sendOnState = ndb.StringProperty(indexed=False)

def geturlanddomain(url):
    if url:
        if "://" not in url:
            url = "http://"+url
    urlbits= list(urlparse.urlsplit(url))
    domain = urlbits[1]
    return url, domain
        
        

def htmltomfjf(html,url,mf2=None):
    if not mf2:
        mf2 = mf2py.Parser(html, url).to_dict()
    jf2 = mf2tojf2.mf2tojf2(mf2)
    return mf2,jf2


class MainHandler(webapp2.RequestHandler):
    def get(self,path):
        if path is None:
            path=""
        page=path.strip().split('.')[0]
        if page not in ('main','about','testing'):
            page='main'
        mentionquery = Mention.query().order(-Mention.updated)
        mentions = mentionquery.fetch(20)
        for mention in mentions:
            mention.humancreated = humanize.naturaltime(mention.created)
            mention.humanupdated = humanize.naturaltime(mention.updated)
            mention.prettytarget=cassis.auto_link(mention.target,do_embed=True,maxUrlLength=80)
            mention.prettysource=cassis.auto_link(mention.source,do_embed=True,maxUrlLength=80)
        template_values={'mentions':mentions}
        
        template = JINJA_ENVIRONMENT.get_template(page+'.html')
        self.response.write(template.render(template_values))

class Publish(webapp2.RequestHandler):
    def get(self):
        template_values={'micropub_url':''}
        template = JINJA_ENVIRONMENT.get_template('publish.html')
        self.response.write(template.render(template_values))
    def post(self):
        site,sitedomain= geturlanddomain(self.request.get('site'))
        reply_to,replydomain= geturlanddomain(self.request.get('in-reply-to'))
        name = self.request.get('name')
        result = urlfetch.fetch(site,deadline=60)
        if result.status_code == 200:
            endpoints=set([])
            logging.info("Publish result.headers %s " % (result.headers))
            links = result.headers.get('link','').split(',')
            for link in links:
                if "micropub" in link:
                    url = urlparse.urljoin(site,link.split(';')[0].strip('<> '))
                    logging.info("Publish found endpoint '%s' in %s " % (url,link))
                    endpoints.add(url)
            mf2,jf2 = htmltomfjf(result.content, url=site)
            for url in mf2.get("rels",{}).get("micropub",[]):
                logging.info("Publish found endpoint '%s' in rels " % (url))
                endpoints.add(url)
        template_values={'micropub_url':list(endpoints)[0],'site':site,'reply_to':reply_to,'name':name}
        template = JINJA_ENVIRONMENT.get_template('publish.html')
        self.response.write(template.render(template_values))

def findCardFeedEntries(item,hcard,hfeed,hentries):
    if not hcard and item["type"][0].startswith('h-card'):
        hcard = item
    if not hcard and "author" in item["properties"] and type(item["properties"]["author"][0]) is dict and item["properties"]["author"][0]["type"][0].startswith('h-card'):
        hcard= item["properties"]["author"][0]
    if not hfeed and item["type"][0].startswith('h-feed'):
        hfeed=item
    if item["type"][0].startswith('h-entry') or item["type"][0].startswith('h-cite'):
        hentries.append(item)
    return hcard,hfeed,hentries

def getTextOrHTML(item):
    if len(item) <1:
        return '' 
    if type(item[0]) is dict:
        return item[0]["html"]
    else:
        return " ".join(item)

def getTextOrValue(item):
    if len(item) <1:
        return '' 
    if type(item[0]) is dict:
        return item[0]["value"]
    else:
        return " ".join(item)

class MentionAll(webapp2.RequestHandler):
    def get(self):
        template = JINJA_ENVIRONMENT.get_template('mentionall.html')
        template_values = {"url":'',"content":'',"links":[]}
        self.response.write(template.render(template_values))
        
    def post(self):
        linkedurls=[]
        url,urldomain= geturlanddomain(self.request.get('url'))
        result = urlfetch.fetch(url,deadline=60)
        if result.status_code == 200:
            mf2,jf = htmltomfjf(result.content, url=url)
            hcard=None
            hfeed=None
            hentries=[]
            linkedurls=[]
            contents=[]
            if mf2:
                for item in mf2["items"]:
                    hcard,hfeed,hentries = findCardFeedEntries(item,hcard,hfeed,hentries)
                    for subitem in item.get("children",[]):
                        hcard,hfeed,hentries = findCardFeedEntries(subitem,hcard,hfeed,hentries)
                if hfeed:
                    if not hentries:
                        for item in hfeed.get("children",[]):
                            hcard,hfeed,hentries = findCardFeedEntries(item,hcard,hfeed,hentries)
                if hentries:
                    for entry in hentries:
                        content=getTextOrHTML(entry["properties"].get("content",[]))
                        linkedurls.extend(absrel.geturls(content,url))
                        contents.append(content)
            logging.info("MentionAll links %s " % (linkedurls))
            for link in linkedurls:
                taskqueue.add(url='/webmention',params={'source':url,'target':link})
        template = JINJA_ENVIRONMENT.get_template('mentionall.html')
        template_values = {"url":url,"content":"<p>".join(contents),"links":linkedurls}
        self.response.write(template.render(template_values))


class WebmentionHandler(webapp2.RequestHandler):
    def post(self):
        source,sourcedomain = geturlanddomain(self.request.get('source'))
        target,targetdomain= geturlanddomain(self.request.get('target'))
        property = self.request.get('property')
        logging.info("source: '%s' from %s target: '%s' from %s" % (source,sourcedomain,target,targetdomain))
        errortext=''
        if not source:
            errortext = errortext + "Source URL not found "
        if not target:
            errortext = errortext + "Target URL not found "
        template_values={'source':source,'target':target,'errortext':errortext}
        if errortext:
            self.response.status = '400 '+ errortext
            template = JINJA_ENVIRONMENT.get_template('error.html')
        else:
            targetkey = ndb.Key('Domain', targetdomain)
            mentionquery = Mention.query(ancestor = targetkey
            ).filter(Mention.source==source, Mention.target==target)
            mentions = mentionquery.fetch(1)
            if len(mentions)<1:
                mention = Mention(parent=targetkey)
                mention.source = source
                mention.sourcedomain = sourcedomain
                mention.target = target
                mention.targetdomain = targetdomain
                if property:
                    mention.property = property
            else:
                mention = mentions[0]
                mention.verified = False
                if property:
                    mention.property = property
            mentionkey = mention.put()
            taskurl = '/verifymention/'+mentionkey.urlsafe()
            logging.info("WebmentionHandler: - queuing task '%s'"  % (taskurl))
            taskqueue.add(url=taskurl)
            taskqueue.add(url='/sendtoarchive',params={'url':source})
            taskqueue.add(url='/sendtoarchive',params={'url':target})
            template = JINJA_ENVIRONMENT.get_template('response.html')
        self.response.write(template.render(template_values))

class VerifyMention(webapp2.RequestHandler):
    def post(self,mentionkey):
        mention_key = ndb.Key(urlsafe=mentionkey)
        logging.info("VerifyMention got key %s " % (mention_key))
        mention = mention_key.get()
        if mention:
            result = urlfetch.fetch(mention.source,deadline=240)
            if result.status_code == 200:
                logging.info("VerifyMention result.content %s " % (result.content[:200]))
                logging.info("VerifyMention result.headers %s " % (result.headers))
                mention.sourceHTML = '/mention-tech-cache/' + urllib.quote(mention.source.encode('utf-8'),'')
#                gcs_file = gcs.open(mention.sourceHTML, 'w', content_type='text/html')
#                gcs_file.write(result.content)
#                gcs_file.close()
                mf2,jf2 = htmltomfjf(result.content, url=mention.source)
                mention.sourcejf2 = json.dumps(jf2)
                if mention.target in unicode(result.content,'utf-8'):
                    mention.verified = True
                    logging.info("VerifyMention %s does link to %s" % (mention.source,mention.target))
                else:
                    mention.verified = False
                    logging.info("VerifyMention %s does not link to %s" % (mention.source,mention.target))
                mentionkey = mention.put()
                if mention.verified:
                    taskurl = '/sendmention/'+mentionkey.urlsafe()
                    logging.info("VerifyMention: - queuing task '%s'"  % (taskurl))
                    taskqueue.add(url=taskurl)
                self.response.write("OK") 
            else:
                logging.info("VerifyMention could not fetch %s to check for %s" % (mention.source,mention.target))
                self.response.write("Fetch fail - error: %s" % (result.status_code)) 
        else:
            self.response.write("No mention")


class SendMention(webapp2.RequestHandler):
    def post(self,mentionkey):
        mention_key = ndb.Key(urlsafe=mentionkey)
        logging.info("SendMention got key %s " % (mention_key))
        mention = mention_key.get()
        if mention:
            result = urlfetch.fetch(mention.target,deadline=240)
            if result.status_code == 200:
                endpoints=[]
                logging.info("SendMention target result.headers %s " % (result.headers))
                logging.info("SendMention target result.content %s " % (result.content[:200]))
                links = result.headers.get('link','').split(',')
                for link in links:
                    if "webmention" in link:
                        url = urlparse.urljoin(mention.target,link.split(';')[0].strip('<> '))
                        logging.info("SendMention found endpoint '%s' in %s " % (url,link))
                        endpoints.append(url)
                mf2,jf2 = htmltomfjf(result.content, url=mention.target)
                mention.targetjf2 = json.dumps(jf2)
                for url in mf2.get("rels",{}).get("webmention",[]):
                    logging.info("SendMention found endpoint '%s' in rels " % (url))
                    endpoints.append(url)
                mention.targetHTML = '/mention-tech-cache/' + urllib.quote(mention.target,'')
#                gcs_file = gcs.open(mention.targetHTML, 'w', content_type='text/html')
#                gcs_file.write(result.content)
#                gcs_file.close()
                mention.put()
                postworked = False
                logging.info("endpoints %s" % endpoints)
                for endpoint in endpoints:
                    if 'mention-tech' in endpoint:
                        logging.info("SendMention skipping '%s' " % (endpoint))
                        pass
                    else:
                        params = {"source":mention.source,"target":mention.target}
                        if mention.property:
                            params["property"]=mention.property
                        if not postworked:
                            form_data = urllib.urlencode(params)
                            result = urlfetch.fetch(url=endpoint, deadline=240,
                                payload=form_data,
                                method=urlfetch.POST,
                                headers={'Content-Type': 'application/x-www-form-urlencoded'})
                            logging.info("SendMention POST to %s got '%s'" % (endpoint,result.status_code))
                            logging.info("SendMention POST to %s result.content %s " % (endpoint,result.content[:1000]))
                            mention.sendOnState = "mention sent '%s' " % (result.status_code)
                            if result.status_code < 300:
                                postworked = True
                            mention.put()
                        else:
                            logging.info("SendMention skipped posting to '%s' " % (url))
                self.response.write("OK") 
            else:
                logging.info("SendMention could not fetch %s to check for webmention" % (mention.target))
                self.response.write("Fetch fail - error: %s" % (result.status_code)) 
                mention.sendOnState = "could not fetch %s '%s' %s" % (mention.target,result.status_code,result.reason)
                mention.put()
        else:
            self.response.write("No mention")



class ListMentions(webapp2.RequestHandler):
    def get(self):
        target,targetdomain= geturlanddomain(self.request.get('target'))
        unverified = self.request.get('unverified','off') == 'on'
        jsonformat = self.request.get('json','off') == 'on'
        targetkey = ndb.Key('Domain', targetdomain)
        
        logging.info("ListMentions target:%s targetdomain %s unverified %s json %s" % (target,targetdomain,unverified,json))
        if unverified:
            mentionquery = Mention.query(ancestor = targetkey).order(-Mention.updated)
        else:
            mentionquery = Mention.query(ancestor = targetkey).filter(Mention.verified==True).order(-Mention.updated)
        rawmentions = mentionquery.fetch(100)
        mentions=[]
        logging.info("listmentions got %s mentions for %s" % (len(rawmentions),target))
        for mention in rawmentions:
            logging.info("rawmention.target '%s' target '%s' %s" % (mention.target,target,mention.target.startswith(target)))
            if mention.target.startswith(target):
                mentions.append(mention)
        if jsonformat:
            jsonout={'type':'feed','children':[]}
            for mention in mentions:
                post ={"type": "entry","published": mention.created.isoformat(),"url": mention.source}
                if mention.sourcejf2:
                    post=json.loads(mention.sourcejf2)
                    post['url'] = post.get('url',mention.source)
                    for key in post:
                        if post[key]==mention.target or (isinstance(post[key],dict) and post[key].get('url','')==mention.target):
                            post['wm-property']=key
                            break
                    
                jsonout['children'].append(post)
            self.response.headers['Content-Type'] = 'application/json'
            self.response.headers['Access-Control-Allow-Origin'] = '*'
            self.response.write(json.dumps(jsonout))
        else:
            for mention in mentions:
                mention.humancreated = humanize.naturaltime(mention.created)
                mention.humanupdated = humanize.naturaltime(mention.updated)
                mention.prettytarget=cassis.auto_link(mention.target,do_embed=True,maxUrlLength=80)
                if mention.sourcejf2:
                    post={}
                    name=mention.source
                    jf = json.loads(mention.sourcejf2)
                    logging.info("ListMentions type %s " % (jf.get("type","")))
                    if jf.get("type","") == "feed":
                        kids= jf.get("children",[{}])
                        logging.info("ListMentions children %s " % (kids[0]))
                        post = kids[0]
                    elif jf.get("type","") == "entry":
                        logging.info("ListMentions entry %s " % (jf))
                        post= jf
                    name= post.get("name",mention.source)
                    content = post.get("content",name)
                    
                    mention.prettysource=cassis.auto_link(content,do_embed=True,maxUrlLength=80)
                else:
                    mention.prettysource=cassis.auto_link(mention.source,do_embed=True,maxUrlLength=80)
            template_values={'mentions':mentions,'targetdomain':targetdomain}
        
            template = JINJA_ENVIRONMENT.get_template('main.html')
            self.response.write(template.render(template_values))

class ArchiveHandler(webapp2.RequestHandler):
  def post(self):
    status="pending"
    sendurl,domain = geturlanddomain(self.request.get('url'))
    if not sendurl:
        status="no url"
    else:
        url = "https://web.archive.org/save/" + sendurl.encode('utf-8')
        logging.info("ArchiveHandler save url is '%s' " % url)
        urlfetch.set_default_fetch_deadline(180)
        result = urlfetch.fetch(url)
        if result.status_code == 200:
          status="saved to archive.org"
        else:
            status="error from service: %s" %(result.status_code)
    logging.info("ArchiveHandler "+ sendurl +" status: " + status)
    self.response.write("ArchiveHandler "+ sendurl +" status: " + status) 

class ArchivePullHandler(webapp2.RequestHandler):
  def get(self):
    status="pending"
    sendurl,domain = geturlanddomain(self.request.get('url'))
    if not sendurl:
        status="no url"
    else:
        url = "http://archive.org/wayback/available?url=" + sendurl
        logging.info("ArchiveHandler get url is '%s' " % url)
        urlfetch.set_default_fetch_deadline(180)
        result = urlfetch.fetch(url)
        if result.status_code == 200:
            status="archive checked"
            output =result.content
            snapshot = json.loads(result.content)
            url = snapshot.get("archived_snapshots",{}).get("closest",{}).get("url")
            if url:
                bits = list(url.split('/'))
                bits[4]=bits[4]+'id_'
                rawurl = '/'.join(bits)
                res2 = urlfetch.fetch(rawurl)
                if res2.status_code == 200:
                    status="found in archive"
                    output =res2.content
                    self.response.headers['Content-Type'] = res2.headers['Content-Type']
            else:
                status="archive missed"
                output ="ArchivePullHandler "+ sendurl +" status: " + status
                self.response.status_int = 404
        else:
            status="error from service: %s" %(result.status_code)
            output ="ArchivePullHandler "+ sendurl +" status: " + status
    logging.info("ArchivePullHandler "+ sendurl +" status: " + status)
    self.response.write(output) 

app = webapp2.WSGIApplication([
    ('/webmention', WebmentionHandler),
    ('/verifymention/(.*)', VerifyMention),
    ('/sendmention/(.*)', SendMention),
    ('/listmentions',ListMentions),
    ('/mentionall',MentionAll),
    ('/publish',Publish),
    ('/sendtoarchive', ArchiveHandler),
    ('/getfromarchive', ArchivePullHandler),
    ('/([^/]+)?', MainHandler),
], debug=True)
