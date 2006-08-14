#!/usr/bin/env python
# Copyright 2006 Canonical Ltd.  All rights reserved.

"""Helper to convert our schema.xml to a .ini file."""

__metaclass__ = type

from elementtree.ElementTree import ElementTree
from textwrap import dedent


def get_sectiontype(name):
    return [e for e in root.findall('sectiontype') if e.get('name') == name][0]

def print_sectiontype(root, sectiontype, sectiontype_name, parents=None):
    if parents is None:
        parents = []
    for key in sectiontype.findall('key'):
        for description in key.findall('description'):
            print
            description = dedent(description.text).split('\n')
            for line in description:
                if line.strip():
                    print '# %s' % line
        if key.get('default'):
            value = key.get('default')
        else:
            value = ''
        name = '.'.join(parents + [sectiontype_name, key.get('name')])
        name = name[len('canonical.'):]
        print '%s=%s' % (name,value)
    for section in sectiontype.findall('section'):
        type = section.get('type')
        attribute = section.get('attribute')
        for sub_sectiontype in root.findall('sectiontype'):
            if sub_sectiontype.get('name') == type:
                print_sectiontype(
                        root, sub_sectiontype, type,
                        parents + [sectiontype_name or sectiontype.get('name')]
                        )

if __name__ == '__main__':
    tree = ElementTree(file='../lib/canonical/config/schema.xml')
    root = tree.getroot()
    canonical = get_sectiontype('canonical')

    print '[canonical]'
    
    print_sectiontype(root, canonical, 'canonical')

