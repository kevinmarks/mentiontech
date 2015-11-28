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

from google.appengine.api import urlfetch
from google.appengine.api import memcache
from google.appengine.api import taskqueue


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


class MainHandler(webapp2.RequestHandler):
    def get(self,path):
        if path is None:
            path=""
        page=path.strip().split('.')[0]
        if page not in ('main','about'):
            page='main'
        mentionquery = Mention.query().order(-Mention.updated)
        mentions = mentionquery.fetch(20)
        for mention in mentions:
            mention.humancreated = humanize.naturaltime(mention.created)
            mention.humanupdated = humanize.naturaltime(mention.updated)
        template_values={'mentions':mentions}
        
        template = JINJA_ENVIRONMENT.get_template(page+'.html')
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
            template = JINJA_ENVIRONMENT.get_template('response.html')
        self.response.write(template.render(template_values))

class VerifyMention(webapp2.RequestHandler):
    def post(self,mentionkey):
        mention_key = ndb.Key(urlsafe=mentionkey)
        logging.info("VerifyMention got key %s " % (mention_key))
        mention = mention_key.get()
        if mention:
            logging.info("VerifyMention got mention %s " % (mention))
            result = urlfetch.fetch(mention.source)
            if result.status_code == 200:
                logging.info("VerifyMention result.content %s " % (result.content[:500]))
                logging.info("VerifyMention result.headers %s " % (result.headers))
                mention.sourceHTML = unicode(result.content,'utf-8')
                if mention.target in mention.sourceHTML:
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
                self.response.write("Fetch fail - error: "+result.status_code) 
        else:
            self.response.write("No mention")


class SendMention(webapp2.RequestHandler):
    def post(self,mentionkey):
        mention_key = ndb.Key(urlsafe=mentionkey)
        logging.info("SendMention got key %s " % (mention_key))
        mention = mention_key.get()
        if mention:
            logging.info("SendMention got mention %s " % (mention))
            result = urlfetch.fetch(mention.target)
            if result.status_code == 200:
                endpoints=set([])
                logging.info("SendMention result.headers %s " % (result.headers))
                logging.info("SendMention result.content %s " % (result.content[:500]))
                links = result.headers.get('link','').split(',')
                for link in links:
                    if "webmention" in link:
                        url=link.split(';')[0].strip('<> ')
                        logging.info("SendMention found endpoint '%s' in %s " % (url,link))
                        endpoints.add(url)
                #TODO grep html next
                mention.targetHTML = unicode(result.content,'utf-8')
                mention.put()
                for endpoint in endpoints:
                    params = {"source":mention.source,"target":mention.target}
                    if mention.property:
                        params["property"]=mention.property
                    url = endpoint+"?"+urllib.urlencode(params)
                    logging.info("SendMention calling '%s' " % (url))
                    try:
                        result = urlfetch.fetch(url,method='POST')
                    except:
                        logging.info("SendMention barfed fetching '%s' " % (url))
                    logging.info("SendMention got '%s' %s" % (result.status_code,result.content))
                self.response.write("OK") 
            else:
                logging.info("SendMention could not fetch %s to check for webmention" % (mention.target))
                self.response.write("Fetch fail - error: "+result.status_code) 
        else:
            self.response.write("No mention")



class ListMentions(webapp2.RequestHandler):
    def get(self):
        target,targetdomain= geturlanddomain(self.request.get('target'))
        targetkey = ndb.Key('Domain', targetdomain)
        logging.info("ListMentions target:%s targetdomain %s" % (target,targetdomain))
        mentionquery = Mention.query(ancestor = targetkey).order(-Mention.updated)
        mentions = mentionquery.fetch(20)
        for mention in mentions:
            mention.humancreated = humanize.naturaltime(mention.created)
            mention.humanupdated = humanize.naturaltime(mention.updated)
        template_values={'mentions':mentions}
        
        template = JINJA_ENVIRONMENT.get_template('main.html')
        self.response.write(template.render(template_values))

app = webapp2.WSGIApplication([
    ('/webmention', WebmentionHandler),
    ('/verifymention/(.*)', VerifyMention),
    ('/sendmention/(.*)', SendMention),
    ('/listmentions',ListMentions),
    ('/([^/]+)?', MainHandler),
], debug=True)
