#!/usr/bin/env python
# -*- coding: utf-8 -*-
# mf2 to jf2 converter
# licence cc0
#  2015 Kevin Marks

import logging


def flattenProperties(items):
    if len(items) <1:
        return {}
    item = items[0]
     
    if type(item) is dict:
        if item.has_key("type"):
            props ={"type":item.get("type",["-"])[0].split("-")[1:][0]}
            properties =  item.get("properties",{})
            for prop in properties:
                props[prop] = flattenProperties(properties[prop])
            return props
        elif item.has_key("value"):
            return item["value"]
        else:
            return ''
    else:
        return item
    

def mf2tojf2(mf2):
    """I'm going to have to recurse here"""
    jf2={}
    items = mf2.get("items",[])
    jf2=flattenProperties(items)
    print mf2, jf2
    return jf2