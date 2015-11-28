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

from google.appengine.ext import ndb

JINJA_ENVIRONMENT = jinja2.Environment(
    loader=jinja2.FileSystemLoader(os.path.dirname(__file__)+"/templates/"),
    extensions=['jinja2.ext.autoescape'],
    autoescape=True)

class Mention(ndb.Model):
    """ model received webmentions"""
    source = ndb.StringProperty(indexed=True)
    target = ndb.StringProperty(indexed=True)
    sourcedomain = ndb.StringProperty(indexed=True)
    targetdomain = ndb.StringProperty(indexed=True)
    sourceHTML = ndb.TextProperty(indexed=False)
    created = ndb.DateTimeProperty(auto_now_add=True) #creation date
    updated = ndb.DateTimeProperty(auto_now=True) #updated date
    verified = ndb.BooleanProperty(indexed=True,default=False)

def geturlanddomain(url):
    if url:
        if "://" not in url:
            url = "http://"+url
    urlbits= list(urlparse.urlsplit(url))
    logging.info(urlbits)
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
        template_values={'mentions':mentions}
        
        template = JINJA_ENVIRONMENT.get_template(page+'.html')
        self.response.write(template.render(template_values))

class WebmentionHandler(webapp2.RequestHandler):
    def post(self):
        source,sourcedomain = geturlanddomain(self.request.get('source'))
        target,targetdomain= geturlanddomain(self.request.get('target'))
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
            else:
                mention = mentions[0]
                mention.verified = False
            mention.put()
            template = JINJA_ENVIRONMENT.get_template('response.html')
        self.response.write(template.render(template_values))


app = webapp2.WSGIApplication([
    ('/webmention', WebmentionHandler),
    ('/([^/]+)?', MainHandler),
], debug=True)
